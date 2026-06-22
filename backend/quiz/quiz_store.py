"""퀴즈 세션(정답 포함 원본)을 Cosmos 에 영속 — serve 재시작/재배포에도 채점이 살아남게.

문제: 생성한 퀴즈(정답 포함)는 quiz_page._SESSIONS(프로세스 RAM, 최근 50개 LRU)에만
quiz_id 로 보관된다. serve 가 재시작되면 _SESSIONS 가 소실돼 POST /quiz/grade 가 404 가
된다. Cosmos 가 설정되면 같은 DB 에 quiz_sessions 컨테이너를 더해 quiz_id 로 세션을
best-effort 로 영속하고, 채점 때 RAM miss 면 여기서 읽어 복구한다.

정답이 들어있어 클라이언트엔 못 내려간다 — 채점은 서버(graphrag)가 하므로 graphrag 쪽에
둔다. graphrag /quiz 는 익명이라 userId 는 모른다(계정 귀속은 프론트 quiz_results 가 따로 함).

계정·DB 는 Mindpalace_fork / orchestrator 와 같은 Cosmos 를 재사용한다(같은 env 관례,
cosmos_jobs.py 와 동형). 미설정/오류는 조용히 무시 — 본연 동작(RAM 채점)에 영향 0.

컨테이너 quiz_sessions (pk /id, id = quiz_id). DefaultTtl 로 오래된 세션을 자동 만료해
무한 증가를 막는다(_SESSIONS_MAX LRU 의 Cosmos 판).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

log = logging.getLogger("backend.quiz.quiz_store")

DB_NAME = os.getenv("AZURE_COSMOS_DB_NAME", "mindpalace")
SESSIONS = "quiz_sessions"
# 세션 보존 기간(초). 사용자는 보통 생성 직후 몇 분 내 채점하므로 7일이면 충분하다.
TTL_SECONDS = int(os.getenv("QUIZ_SESSION_TTL_SECONDS", str(7 * 24 * 3600)))

_client = None
_container_singleton = None


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
    """DB 생성/확보(cosmos_jobs.py 와 동형). 서버리스면 처리량 미지정."""
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
    """quiz_sessions 컨테이너(없으면 생성, 캐시). DefaultTtl 로 자동 만료. 미설정/오류 시 None."""
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
            id=SESSIONS,
            partition_key=PartitionKey(path="/id"),
            default_ttl=TTL_SECONDS,  # 신규 생성 시에만 반영(이미 있으면 기존 설정 유지).
        )
        _container_singleton = cont
        return cont
    except Exception:
        log.warning("Cosmos quiz_sessions 컨테이너 확보 실패", exc_info=True)
        return None


def save_session(quiz_id: str, quizzes: list[dict]) -> None:
    """세션(정답 포함 원본)을 quiz_id 로 영속. best-effort — 미설정/오류는 조용히 무시."""
    if not quiz_id or not quizzes:
        return
    cont = _container()
    if cont is None:
        return
    try:
        cont.upsert_item({
            "id": quiz_id,
            "quizzes": quizzes,
            "createdAt": _now(),
            "ttl": TTL_SECONDS,
        })
    except Exception:
        log.warning("퀴즈 세션 저장 실패: %s", quiz_id, exc_info=True)


def load_session(quiz_id: str) -> list[dict] | None:
    """quiz_id 로 세션을 읽는다(RAM miss 복구용). 없으면/오류면 None."""
    if not quiz_id:
        return None
    cont = _container()
    if cont is None:
        return None
    try:
        doc = cont.read_item(item=quiz_id, partition_key=quiz_id)
        quizzes = doc.get("quizzes")
        return quizzes if isinstance(quizzes, list) else None
    except Exception:
        return None  # 없음(404)/만료 등.
