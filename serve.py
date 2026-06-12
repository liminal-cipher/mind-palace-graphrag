"""RAG 서빙 코어: 질문 -> GraphRAG global search -> 답.

warm_query.py를 그대로 감싼다. 처음부터 다시 짜지 않고, 거기서 이미 검증된
스냅샷 warm load(parquet + LanceDB + 엔진 빌드)와 global 엔진 빌더를 재사용한다.

설계 메모:
  - warm_query는 import 시점에 asyncio.run(...)으로 parquet/LanceDB를 읽는다.
    FastAPI lifespan은 이미 이벤트 루프 안이라 거기서 import하면
    "asyncio.run() cannot be called from a running event loop"로 깨진다.
  - 그래서 GraphRAG 관련 작업(warm load + 매 검색)을 max_workers=1 전용 스레드에
    전부 몰아넣는다. 그 스레드엔 실행 중인 루프가 없어 asyncio.run이 동작하고,
    엔진을 빌드한 스레드와 검색하는 스레드가 같아 LanceDB 스레드 이슈도 없다.
  - 단일 워커라 /query는 직렬 처리된다. 서빙 코어 1차 빌드엔 충분하고
    global search 자체가 무거운 단발성 호출이라 동시성 욕심은 안 낸다.

대상 스냅샷: 국사 canonical = results/snapshots/repro_run3 (warm_query가 가리키는 곳).
합성 모델: config의 global_search.completion_model_id -> default_completion_model
           -> gpt-4.1-mini. 엔진이 config에서 알아서 읽으므로 여기선 안 박는다.
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# settings.yaml의 ${GRAPHRAG_API_KEY}/${GRAPHRAG_API_BASE} 치환은 env에서 온다.
# warm_query/graphrag는 .env를 자동 로드하지 않으므로 import 전에 먼저 채워둔다.
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("serve")

# GraphRAG 작업 전용 단일 워커. 이 스레드 위에서만 엔진을 만들고 검색한다.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="graphrag")

# 기본(그리고 현재 유일) 스냅샷 키. 멀티데이터셋은 나중 레이어.
DEFAULT_SNAPSHOT = "repro_run3"

# global search(서빙) 합성 모델만 gpt-5.4-mini로 배선한다.
# 파이프라인 공용 default_completion_model(추출/TOC/Stage B = gpt-4.1-mini)은 안 건드린다.
# 인덱스 산출물(parquet/LanceDB)은 안 바뀌므로 repro_run3 재인덱싱 없음.
RAG_SYNTHESIS_MODEL = "gpt-5.4-mini"
RAG_MODEL_ID = "rag_synthesis_model"  # config.completion_models에 추가할 in-memory 키


class _ModelCallLogger:
    """litellm이 실제로 어떤 모델로 호출하는지 매 요청 전에 찍는다.
    검증용: 서빙 합성 호출이 정말 gpt-5.4-mini로 나가는지 확인."""

    def log_pre_api_call(self, model, messages, kwargs):  # noqa: ANN001
        logger.info("llm call -> model=%s", model)

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):  # noqa: ANN001
        logger.info("llm done <- model=%s", kwargs.get("model"))


def _install_model_logger() -> None:
    try:
        import litellm

        litellm.callbacks = [*(litellm.callbacks or []), _ModelCallLogger()]
        logger.info("litellm 모델 호출 로거 설치됨")
    except Exception as e:  # noqa: BLE001  로깅 실패가 서빙을 막진 않게.
        logger.warning("litellm 모델 로거 설치 실패: %s", e)


class _State:
    """warmup 결과를 들고 있는 모듈 전역 상태."""

    ready: bool = False
    error: Optional[str] = None
    warmup_seconds: Optional[float] = None
    snapshot: Optional[str] = None
    engine: Any = None  # global search engine (warm_query._engine("global"))
    synthesis_model: Optional[str] = None  # global search가 실제로 바인딩한 모델


STATE = _State()


def _warmup_blocking() -> None:
    """전용 스레드에서 실행. warm_query를 import하면서 스냅샷을 통째로 로드하고
    global 엔진을 빌드한다. 실행 중인 이벤트 루프가 없는 스레드라 OK."""
    t0 = time.perf_counter()
    # import 자체가 parquet + LanceDB + 임베딩 스토어 + (local 엔진) warm load를 돈다.
    import warm_query as wq

    STATE.snapshot = wq.SNAPSHOT.name

    # --- global search 합성 모델을 gpt-5.4-mini로 in-memory 배선 ---
    # 디스크 settings.yaml/스냅샷은 안 건드린다. default_completion_model을 복제해
    # deployment만 gpt-5.4-mini로 바꾼 새 항목을 추가하고, global_search만 그걸 쓰게 한다.
    base = wq.config.get_completion_model_config(
        wq.config.global_search.completion_model_id
    )
    rag_model = base.model_copy(
        update={
            "model": RAG_SYNTHESIS_MODEL,
            "azure_deployment_name": RAG_SYNTHESIS_MODEL,
        }
    )
    wq.config.completion_models[RAG_MODEL_ID] = rag_model
    wq.config.global_search.completion_model_id = RAG_MODEL_ID
    logger.info(
        "global search 합성 모델 배선: %s -> deployment=%s (default_completion_model 불변)",
        RAG_MODEL_ID,
        RAG_SYNTHESIS_MODEL,
    )

    # 우리가 서빙할 건 global. 첫 호출이 콜드하지 않게 지금 빌드해 둔다.
    STATE.engine = wq._engine("global")

    # 빌드된 엔진이 실제로 바인딩한 모델을 확인해 찍는다(검증용).
    bound = getattr(STATE.engine, "model", None)
    bound_cfg = getattr(bound, "_model_config", None)
    if bound_cfg is not None:
        STATE.synthesis_model = bound_cfg.azure_deployment_name or bound_cfg.model
        logger.info(
            "global 엔진 바인딩 모델: model_id=%s, deployment=%s",
            getattr(bound, "_model_id", "?"),
            STATE.synthesis_model,
        )

    STATE.warmup_seconds = time.perf_counter() - t0
    STATE.ready = True
    logger.info(
        "warmup done: snapshot=%s, synthesis_model=%s, %.1fs",
        STATE.snapshot,
        STATE.synthesis_model,
        STATE.warmup_seconds,
    )


def _search_blocking(question: str) -> str:
    """전용 스레드에서 global search 한 번. warm_query.ask와 동일하게
    asyncio.run으로 engine.search 코루틴을 돌린다(이 스레드엔 루프가 없으므로 OK)."""
    result = asyncio.run(STATE.engine.search(question))
    return result.response if hasattr(result, "response") else str(result)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 부팅 warmup. uvicorn은 startup이 끝날 때까지 요청을 받지 않으므로
    첫 /query는 이미 로드된 엔진을 재사용한다."""
    loop = asyncio.get_running_loop()
    _install_model_logger()
    logger.info("warmup 시작 (스냅샷 로드 + global 엔진 빌드)...")
    try:
        await loop.run_in_executor(_executor, _warmup_blocking)
    except Exception as e:  # noqa: BLE001  warmup 실패해도 앱은 떠서 /health로 알린다.
        STATE.error = f"{type(e).__name__}: {e}"
        logger.exception("warmup 실패: %s", STATE.error)
    yield
    _executor.shutdown(wait=False)


app = FastAPI(title="회랑 RAG 서빙 코어", lifespan=lifespan)


class QueryRequest(BaseModel):
    question: str = Field(..., description="자연어 질문")
    # 나중 멀티데이터셋용 자리만 열어둔다. 지금은 기본 스냅샷만 서빙한다.
    snapshot: Optional[str] = Field(
        default=None,
        description="(미구현) 대상 스냅샷 키. 현재는 기본 스냅샷만 지원.",
    )


class QueryResponse(BaseModel):
    answer: str
    # related_nodes: 팰리스 노드 연결은 나중 레이어. 지금은 자리만 비워둔다.
    # related_nodes: list[dict] = []


@app.get("/health")
async def health():
    """warmup 됐는지 확인용."""
    if STATE.error:
        return {
            "status": "error",
            "ready": False,
            "error": STATE.error,
            "snapshot": STATE.snapshot,
        }
    return {
        "status": "ok" if STATE.ready else "warming",
        "ready": STATE.ready,
        "snapshot": STATE.snapshot,
        "warmup_seconds": (
            round(STATE.warmup_seconds, 1) if STATE.warmup_seconds else None
        ),
        "method": "global",
        "synthesis_model": STATE.synthesis_model,
    }


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    """질문 -> global search -> 답 텍스트."""
    if STATE.error:
        raise HTTPException(status_code=503, detail=f"warmup 실패: {STATE.error}")
    if not STATE.ready or STATE.engine is None:
        raise HTTPException(status_code=503, detail="warmup 진행 중. 잠시 후 재시도.")

    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="question이 비어 있다.")
    if req.snapshot and req.snapshot != (STATE.snapshot or DEFAULT_SNAPSHOT):
        # 멀티데이터셋 미구현. 다른 스냅샷 요청은 조용히 무시하지 말고 명시적으로 막는다.
        raise HTTPException(
            status_code=400,
            detail=(
                f"스냅샷 '{req.snapshot}' 미지원. 현재 기본 "
                f"'{STATE.snapshot or DEFAULT_SNAPSHOT}'만 서빙한다."
            ),
        )

    loop = asyncio.get_running_loop()
    t0 = time.perf_counter()
    answer = await loop.run_in_executor(_executor, _search_blocking, question)
    logger.info("query %.1fs: %s", time.perf_counter() - t0, question[:50])
    return QueryResponse(answer=answer)
