"""잡 상태(JobStore)의 Cosmos 백엔드 — 재시작/재배포에도 잡 기록이 살아남게.

orchestrator 의 잡 DB 는 기본 SQLite(var/orchestrator.db)라 서버가 재시작되면 휘발한다
(config.py 참고). 그래서 재배포·크래시 뒤 GET /jobs/{id}/status 가 404 가 됐다. Cosmos 가
설정되면 같은 인터페이스의 CosmosJobStore 로 교체해 잡 상태를 영속한다.

계정·DB 는 Mindpalace_fork 와 같은 Cosmos 를 재사용한다(같은 env 관례):
    AZURE_COSMOS_CONNECTION_STRING                 # 또는
    AZURE_COSMOS_ENDPOINT + AZURE_COSMOS_KEY
    AZURE_COSMOS_DB_NAME   (기본 "mindpalace"), AZURE_COSMOS_MAX_RU, AZURE_COSMOS_SERVERLESS
그 DB 에 컨테이너 "jobs"(pk /id, id=job_id) 를 더한다(users/library/mnemonics 와 분리).
미설정이면 configured()=False 라 app 이 SQLite JobStore 로 폴백한다(로컬/하위호환).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from orchestrator.jobs import Job, State

log = logging.getLogger("orchestrator.cosmos_jobs")

DB_NAME = os.getenv("AZURE_COSMOS_DB_NAME", "mindpalace")
JOBS = "jobs"

_client = None
_container_singleton = None

# update() 가 갱신 허용하는 컬럼(JobStore 와 동일). job_id/created_at 등 불변 키는 제외.
_ALLOWED_UPDATE = {
    "state", "domain", "run_id", "input_path", "snapshot_path",
    "palace_path", "palace_ready", "rag_ready", "error", "showcase_key", "toc_ready",
}
# Job <-> 문서 직렬화 대상 필드.
_JOB_FIELDS = (
    "job_id", "state", "domain", "run_id", "input_path", "snapshot_path",
    "palace_path", "palace_ready", "rag_ready", "error", "created_at",
    "updated_at", "showcase_key", "toc_ready",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def configured() -> bool:
    if (os.getenv("AZURE_COSMOS_CONNECTION_STRING") or "").strip():
        return True
    return bool(
        (os.getenv("AZURE_COSMOS_ENDPOINT") or "").strip()
        and (os.getenv("AZURE_COSMOS_KEY") or "").strip()
    )


def _get_client():
    """CosmosClient(캐시). 미설정/오류/SDK 미설치 시 None."""
    global _client
    if _client is not None:
        return _client
    try:
        from azure.cosmos import CosmosClient

        conn = (os.getenv("AZURE_COSMOS_CONNECTION_STRING") or "").strip()
        if conn:
            _client = CosmosClient.from_connection_string(conn)
        else:
            endpoint = (os.getenv("AZURE_COSMOS_ENDPOINT") or "").strip()
            key = (os.getenv("AZURE_COSMOS_KEY") or "").strip()
            if not (endpoint and key):
                return None
            _client = CosmosClient(endpoint, credential=key)
        return _client
    except Exception:
        log.warning("Cosmos 클라이언트 초기화 실패", exc_info=True)
        return None


def _ensure_database(client):
    """DB 생성/확보(Mindpalace_fork cosmos.py 와 동형). 서버리스면 처리량 미지정."""
    serverless = (os.getenv("AZURE_COSMOS_SERVERLESS") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    if serverless:
        return client.create_database_if_not_exists(DB_NAME)
    try:
        from azure.cosmos import ThroughputProperties

        max_ru = int(os.getenv("AZURE_COSMOS_MAX_RU", "1000"))
        return client.create_database_if_not_exists(
            DB_NAME,
            offer_throughput=ThroughputProperties(auto_scale_max_throughput=max_ru),
        )
    except Exception:
        return client.create_database_if_not_exists(DB_NAME)


def _container():
    """jobs 컨테이너(없으면 생성, 캐시). 미설정/오류 시 None."""
    global _container_singleton
    if _container_singleton is not None:
        return _container_singleton
    client = _get_client()
    if client is None:
        return None
    try:
        from azure.cosmos import PartitionKey

        db = _ensure_database(client)
        cont = db.create_container_if_not_exists(
            id=JOBS, partition_key=PartitionKey(path="/id")
        )
        _container_singleton = cont
        return cont
    except Exception:
        log.warning("Cosmos jobs 컨테이너 확보 실패", exc_info=True)
        return None


def _doc_to_job(doc: dict) -> Job:
    return Job(
        job_id=doc["job_id"],
        state=doc["state"],
        domain=doc.get("domain", ""),
        run_id=doc.get("run_id", ""),
        input_path=doc.get("input_path", ""),
        snapshot_path=doc.get("snapshot_path", ""),
        palace_path=doc.get("palace_path"),
        palace_ready=bool(doc.get("palace_ready")),
        rag_ready=bool(doc.get("rag_ready")),
        error=doc.get("error"),
        created_at=doc.get("created_at", ""),
        updated_at=doc.get("updated_at", ""),
        showcase_key=doc.get("showcase_key"),
        toc_ready=bool(doc.get("toc_ready")),
    )


def _job_to_doc(job: Job) -> dict:
    doc = {f: getattr(job, f) for f in _JOB_FIELDS}
    doc["id"] = job.job_id  # Cosmos 필수 id == pk(/id) == job_id.
    return doc


class CosmosJobStore:
    """JobStore 와 동일 인터페이스의 Cosmos 백엔드. 워커/앱은 이 인터페이스만 본다.

    SQLite JobStore 와 메서드 시그니처가 같아 app.lifespan 에서 골라 끼우기만 하면 된다.
    잡 단위 갱신은 워커가 직렬로 수행하므로 read-modify-write 경합은 사실상 없다."""

    def init_db(self) -> None:
        if _container() is None:
            raise RuntimeError("Cosmos jobs 컨테이너 확보 실패 (설정 확인)")

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
        job = Job(
            job_id=job_id, state=State.QUEUED, domain=domain, run_id=run_id,
            input_path=input_path, snapshot_path=snapshot_path, palace_path=None,
            palace_ready=False, rag_ready=False, error=None,
            created_at=ts, updated_at=ts, showcase_key=showcase_key, toc_ready=False,
        )
        _container().upsert_item(_job_to_doc(job))
        return job

    def get(self, job_id: str) -> Optional[Job]:
        cont = _container()
        if cont is None:
            return None
        try:
            return _doc_to_job(cont.read_item(item=job_id, partition_key=job_id))
        except Exception:
            return None  # 없음(404) 등.

    def delete(self, job_id: str) -> bool:
        cont = _container()
        if cont is None:
            return False
        try:
            cont.delete_item(item=job_id, partition_key=job_id)
            return True
        except Exception:
            return False  # 이미 없음 등.

    def update(self, job_id: str, **fields) -> None:
        """임의 컬럼 갱신(read-modify-write). updated_at 은 매번 자동으로 찍는다."""
        if not fields:
            return
        bad = set(fields) - _ALLOWED_UPDATE
        if bad:
            raise ValueError(f"unknown job columns: {sorted(bad)}")
        cont = _container()
        if cont is None:
            return
        doc = cont.read_item(item=job_id, partition_key=job_id)
        for k in ("palace_ready", "rag_ready", "toc_ready"):
            if k in fields:
                fields[k] = bool(fields[k])
        doc.update(fields)
        doc["updated_at"] = _now()
        cont.replace_item(item=doc["id"], body=doc)

    def fail(self, job_id: str, error: str) -> None:
        self.update(job_id, state=State.FAILED, error=error)

    def list_non_terminal(self) -> list[Job]:
        """DONE/FAILED 가 아닌 잡(시작 시 복구 대상). created_at 오름차순."""
        cont = _container()
        if cont is None:
            return []
        query = (
            "SELECT * FROM c WHERE NOT ARRAY_CONTAINS(@terminal, c.state) "
            "ORDER BY c.created_at"
        )
        params = [{"name": "@terminal", "value": list(State.TERMINAL)}]
        # 잡마다 파티션(pk /id)이라 복구 조회는 cross-partition. 잡 수가 적어 비용은 미미.
        items = cont.query_items(
            query=query, parameters=params, enable_cross_partition_query=True
        )
        return [_doc_to_job(d) for d in items]


# ── LLM 사용량 기록(비용추적·사업모델 데이터) ────────────────────────────────
USAGE = "usage"
_usage_container_singleton = None


def _usage_container():
    """usage 컨테이너(pk /jobId, 없으면 생성, 캐시). 미설정/오류 시 None."""
    global _usage_container_singleton
    if _usage_container_singleton is not None:
        return _usage_container_singleton
    client = _get_client()
    if client is None:
        return None
    try:
        from azure.cosmos import PartitionKey

        db = _ensure_database(client)
        cont = db.create_container_if_not_exists(
            id=USAGE, partition_key=PartitionKey(path="/jobId")
        )
        _usage_container_singleton = cont
        return cont
    except Exception:
        log.warning("Cosmos usage 컨테이너 확보 실패", exc_info=True)
        return None


def record_usage(job_id: str, stage: str, summary: dict) -> None:
    """잡의 LLM 사용량(stage별: indexing/chat 등)을 usage 컨테이너에 기록. best-effort
    (미설정/오류는 조용히 무시 — 본연 동작에 영향 0). 유저 귀속은 Mindpalace_fork 가
    잡↔유저 매핑으로 jobId 기준 집계한다(graphrag /upload 는 익명이라 userId 를 모름)."""
    cont = _usage_container()
    if cont is None:
        return
    try:
        doc = {
            "id": f"{job_id}:{stage}",
            "jobId": job_id,
            "stage": stage,
            "ts": _now(),
            **(summary or {}),
        }
        cont.upsert_item(doc)
    except Exception:
        log.warning("usage 기록 실패 job=%s stage=%s", job_id, stage, exc_info=True)
