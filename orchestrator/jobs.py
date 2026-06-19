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
    TOC_READY = "TOC_READY"
    INDEXING = "INDEXING"
    BUILDING_PALACE = "BUILDING_PALACE"
    PALACE_READY = "PALACE_READY"
    RAG_READY = "RAG_READY"
    DONE = "DONE"
    FAILED = "FAILED"

    TERMINAL = frozenset({DONE, FAILED})


# 프론트 로딩 바용 단계 정의. weight=가중치(합 100, 관측 소요 기반), est_seconds=대략
# 소요(활성 구간 보간용). 텍스트추출·정제는 한 백엔드 단계(preprocess)라 "전처리"로 합침.
_PROGRESS_STEPS = (
    {"key": "preprocess", "label": "전처리", "weight": 25, "est_seconds": 90},
    {"key": "indexing", "label": "인덱싱", "weight": 55, "est_seconds": 280},
    {"key": "rooms", "label": "방 생성", "weight": 20, "est_seconds": 60},
)
_STATE_ORDER = {
    State.QUEUED: 0, State.PREPROCESSING: 1, State.TOC_READY: 2,
    State.INDEXING: 3, State.BUILDING_PALACE: 4, State.PALACE_READY: 5,
    State.RAG_READY: 6, State.DONE: 7,
}
_STEP_ACTIVE_STATE = {
    "preprocess": State.PREPROCESSING,
    "indexing": State.INDEXING,
    "rooms": State.BUILDING_PALACE,
}


def _progress(state: str, toc_ready: bool, palace_ready: bool, rag_ready: bool) -> dict:
    """state(현재 활동) + 완료 플래그로 각 step 의 done/active/pending/failed 를 만든다.
    percent 는 완료 step 가중치 합(서버는 단계 내부 진행률을 모르므로, 프론트가 활성 step
    의 est_seconds + updated_at 으로 보간한다). FAILED 면 완료 못 한 첫 step 을 failed 로."""
    ordv = _STATE_ORDER.get(state, 0)
    failed = state == State.FAILED
    done_by_key = {
        "preprocess": toc_ready or palace_ready or rag_ready or ordv >= 3,
        "indexing": palace_ready or rag_ready or ordv >= 4,
        "rooms": palace_ready or rag_ready or ordv >= 5,
    }
    steps, percent, current, failed_marked = [], 0, None, False
    for s in _PROGRESS_STEPS:
        if done_by_key[s["key"]]:
            status = "done"
            percent += s["weight"]
        elif failed and not failed_marked:
            status, failed_marked, current = "failed", True, s["key"]
        elif (not failed) and state == _STEP_ACTIVE_STATE[s["key"]]:
            status, current = "active", s["key"]
        else:
            status = "pending"
        steps.append({**s, "status": status})
    if state == State.DONE:
        percent = 100
    return {"percent": percent, "current_step": current, "steps": steps}


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
    # 명시 쇼케이스 트리거. None 이면 라이브 업로드(진짜 인덱싱), 값이 있으면 그 키로
    # 프리베이크 스냅샷을 고른다(scaffold). domain 라벨과 분리돼 있어, 감지/선언된
    # domain 이 무엇이든 스냅샷 선택엔 절대 관여하지 않는다.
    showcase_key: Optional[str] = None
    # toc_ready: LLM 목차(toc_llm.json)가 인덱싱 전에 먼저 나왔는지. 프론트가 둘러보기
    # 페이지에서 방 생성 전에 목차를 보여줄 수 있게 하는 조기 플래그(palace_ready 와 독립).
    toc_ready: bool = False

    def to_status(self) -> dict:
        """GET /jobs/{id}/status 응답 모양. readiness 는 독립 플래그로 노출."""
        return {
            "job_id": self.job_id,
            "state": self.state,
            "palace_ready": self.palace_ready,
            "toc_ready": self.toc_ready,
            "rag_ready": self.rag_ready,
            "domain": self.domain,
            "showcase_key": self.showcase_key,
            "run_id": self.run_id,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            # 프론트 로딩 바용 단계 진행 정보(state+플래그에서 파생, 별도 저장 안 함).
            "progress": _progress(
                self.state, self.toc_ready, self.palace_ready, self.rag_ready
            ),
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
    updated_at    TEXT NOT NULL,
    showcase_key  TEXT,
    toc_ready     INTEGER NOT NULL DEFAULT 0
);
"""


def _row_to_job(row: sqlite3.Row) -> Job:
    keys = row.keys()
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
        # 구 DB(마이그레이션 전)에는 컬럼이 없을 수 있으므로 방어적으로 읽는다.
        showcase_key=row["showcase_key"] if "showcase_key" in keys else None,
        toc_ready=bool(row["toc_ready"]) if "toc_ready" in keys else False,
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
            # 마이그레이션: 신규 컬럼을 구 테이블에 더한다(CREATE IF NOT EXISTS 는 기존
            # 테이블 컬럼을 갱신하지 않으므로). ADD COLUMN ... TEXT 는 기본 NULL 로 안전.
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
            if "showcase_key" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN showcase_key TEXT")
            if "toc_ready" not in cols:
                conn.execute(
                    "ALTER TABLE jobs ADD COLUMN toc_ready INTEGER NOT NULL DEFAULT 0"
                )
            conn.commit()

    def create(
        self,
        *,
        job_id: str,
        domain: str,
        run_id: str,
        input_path: str,
        snapshot_path: str,
        showcase_key: Optional[str] = None,
    ) -> Job:
        ts = _now()
        with closing(self._connect()) as conn:
            conn.execute(
                """INSERT INTO jobs (
                    job_id, state, domain, run_id, input_path, snapshot_path,
                    palace_path, palace_ready, rag_ready, error,
                    created_at, updated_at, showcase_key
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, 0, 0, NULL, ?, ?, ?)""",
                (job_id, State.QUEUED, domain, run_id, input_path,
                 snapshot_path, ts, ts, showcase_key),
            )
            conn.commit()
        return self.get(job_id)  # type: ignore[return-value]

    def get(self, job_id: str) -> Optional[Job]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return _row_to_job(row) if row else None

    def delete(self, job_id: str) -> bool:
        """잡 DB row 를 지운다(잡 폴더 정리는 호출부 담당). 지워졌으면 True."""
        with closing(self._connect()) as conn:
            cur = conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            conn.commit()
        return cur.rowcount > 0

    def update(self, job_id: str, **fields) -> None:
        """임의 컬럼 갱신. updated_at 은 매번 자동으로 찍는다. 전이마다 즉시 커밋."""
        if not fields:
            return
        allowed = {
            "state", "domain", "run_id", "input_path", "snapshot_path",
            "palace_path", "palace_ready", "rag_ready", "error", "showcase_key",
            "toc_ready",
        }
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown job columns: {sorted(bad)}")
        # bool -> int (sqlite 는 bool 컬럼이 없다).
        for k in ("palace_ready", "rag_ready", "toc_ready"):
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
