"""잡 상태 모델 + SQLite 저장소.

State 는 진행 마일스톤(QUEUED..DONE/FAILED)이고, palace_ready/rag_ready 는
그와 독립된 저장 플래그다. 어느 readiness 가 먼저 켜질지는 나중 인덱싱 staging
결정(병렬이면 palace 먼저, 풀인덱싱-후-빌드면 rag 먼저)에 달려 있으므로, 스키마와
조회는 특정 순서를 가정하지 않는다. STUB 워커는 순차로 켜지만 모델은 순서 불문.

sqlite3 표준 라이브러리만 쓴다(신규 의존성 0). 워커 스레드와 요청 스레드가 모두
접근하므로, 연산마다 새 커넥션을 열어 스레드 안전을 단순하게 보장한다.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class State:
    """잡 진행 상태. 문자열 상수로 두어 SQLite/JSON 직렬화를 단순화한다."""

    QUEUED = "QUEUED"
    PREPROCESSING = "PREPROCESSING"
    INDEXING = "INDEXING"
    PALACE_READY = "PALACE_READY"
    RAG_READY = "RAG_READY"
    DONE = "DONE"
    FAILED = "FAILED"

    TERMINAL = frozenset({DONE, FAILED})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    job_id: str
    state: str
    domain: str
    run_id: str
    input_path: str
    snapshot_path: str
    palace_path: Optional[str]
    palace_ready: bool
    rag_ready: bool
    error: Optional[str]
    created_at: str
    updated_at: str

    def to_status(self) -> dict:
        """GET /jobs/{id}/status 응답 모양. readiness 는 독립 플래그로 노출."""
        return {
            "job_id": self.job_id,
            "state": self.state,
            "palace_ready": self.palace_ready,
            "rag_ready": self.rag_ready,
            "domain": self.domain,
            "run_id": self.run_id,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,
    state         TEXT NOT NULL,
    domain        TEXT NOT NULL,
    run_id        TEXT NOT NULL,
    input_path    TEXT NOT NULL,
    snapshot_path TEXT NOT NULL,
    palace_path   TEXT,
    palace_ready  INTEGER NOT NULL DEFAULT 0,
    rag_ready     INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
"""


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        job_id=row["job_id"],
        state=row["state"],
        domain=row["domain"],
        run_id=row["run_id"],
        input_path=row["input_path"],
        snapshot_path=row["snapshot_path"],
        palace_path=row["palace_path"],
        palace_ready=bool(row["palace_ready"]),
        rag_ready=bool(row["rag_ready"]),
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class JobStore:
    """잡 테이블의 유일한 진입점. 워커는 이 인터페이스만 본다."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def create(
        self,
        *,
        job_id: str,
        domain: str,
        run_id: str,
        input_path: str,
        snapshot_path: str,
    ) -> Job:
        ts = _now()
        with closing(self._connect()) as conn:
            conn.execute(
                """INSERT INTO jobs (
                    job_id, state, domain, run_id, input_path, snapshot_path,
                    palace_path, palace_ready, rag_ready, error,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, 0, 0, NULL, ?, ?)""",
                (job_id, State.QUEUED, domain, run_id, input_path,
                 snapshot_path, ts, ts),
            )
            conn.commit()
        return self.get(job_id)  # type: ignore[return-value]

    def get(self, job_id: str) -> Optional[Job]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return _row_to_job(row) if row else None

    def update(self, job_id: str, **fields) -> None:
        """임의 컬럼 갱신. updated_at 은 매번 자동으로 찍는다. 전이마다 즉시 커밋."""
        if not fields:
            return
        allowed = {
            "state", "domain", "run_id", "input_path", "snapshot_path",
            "palace_path", "palace_ready", "rag_ready", "error",
        }
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown job columns: {sorted(bad)}")
        # bool -> int (sqlite 는 bool 컬럼이 없다).
        for k in ("palace_ready", "rag_ready"):
            if k in fields:
                fields[k] = 1 if fields[k] else 0
        cols = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values())
        with closing(self._connect()) as conn:
            conn.execute(
                f"UPDATE jobs SET {cols}, updated_at = ? WHERE job_id = ?",
                (*vals, _now(), job_id),
            )
            conn.commit()

    def fail(self, job_id: str, error: str) -> None:
        self.update(job_id, state=State.FAILED, error=error)

    def list_non_terminal(self) -> list[Job]:
        """DONE/FAILED 가 아닌 잡(시작 시 복구 대상)."""
        placeholders = ", ".join("?" for _ in State.TERMINAL)
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM jobs WHERE state NOT IN ({placeholders}) "
                "ORDER BY created_at",
                tuple(State.TERMINAL),
            ).fetchall()
        return [_row_to_job(r) for r in rows]
