"""RAG 서빙 코어: 질문 -> GraphRAG global search -> 답.

warm_query.load_engine를 그대로 쓴다. 처음부터 다시 짜지 않고, 거기서 이미 검증된
스냅샷 warm load(parquet + global 엔진 빌드)와 합성 모델 in-memory 배선을 재사용한다.

여러 스냅샷을 동시에 서빙한다. 레지스트리는 run_id(콘텐츠/제품 정체성)를 키로,
스냅샷 디렉터리(빌드/provenance 정체성)를 값으로 둔다. 둘은 의도적으로 분리돼 있어
(korean_history = 제품, repro_run3 = 빌드) 라우팅 키엔 run_id를 쓴다. 미래 오케스트레이션
rag 스테이지는 register(job.run_id, job.snapshot_path)로 이 레지스트리를 그대로 재사용한다.

설계 메모:
  - load_engine은 import 부수효과가 없다. FastAPI lifespan은 이미 이벤트 루프 안이라
    asyncio.run(warm load 내부)이 "running event loop"로 깨진다. 그래서 GraphRAG
    작업(warm load + 매 검색)을 max_workers=1 전용 스레드에 전부 몰아넣는다. 그 스레드엔
    실행 중인 루프가 없어 asyncio.run이 동작하고, 모든 스냅샷의 엔진을 같은 스레드에서
    빌드/검색하므로 LanceDB 스레드 이슈도 없다(global은 LanceDB 미사용이라 이중 안전).
  - 단일 워커라 /query는 직렬 처리된다. global search 자체가 무거운 단발성 호출이라
    서빙 코어엔 충분하다.

검색 모드: 기본 method="auto"면 BGE-M3 라우터가 질문을 local/global로 보낸다(RAG_ROUTING
=0이면 끄고 항상 global; 라우터 로드 실패 시에도 global 폴백). method="local"/"global"로
강제 가능. 어느 스냅샷에 묻는지는 요청의 snapshot 파라미터(run_id 또는 alias)로 정한다.
라우터는 질문 내용으로 검색 family만 고르고, 데이터셋(스냅샷) 선택엔 관여하지 않는다.
합성 모델: RAG config 기준. global search 합성만 gpt-5.4-mini로 배선한다.
파이프라인 공용 default_completion_model(추출/TOC/Stage B = gpt-4.1-mini)은 안 건드린다.
"""

import ast
import asyncio
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
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

# global search(서빙) 합성 모델. RAG config 기준으로만 배선되고, 파이프라인 공용
# default_completion_model은 불변. 인덱스 산출물(parquet/LanceDB)도 안 바뀐다.
RAG_SYNTHESIS_MODEL = "gpt-5.4-mini"

# BGE-M3 local/global 라우팅. 켜면 method="auto" 질문을 라우터가 local/global로 보낸다.
# 끄면(또는 모델 로드 실패 시) 항상 global(기존 동작). env로 토글.
ROUTING_ENABLED = os.environ.get("RAG_ROUTING", "1") != "0"

# 라우터 로드 시 함께 여는 임베딩 스토어(local search 가 entity_description LanceDB 필요).
# 라우팅 OFF면 global 만 서빙하므로 스토어를 안 연다(기존 경량 경로 유지).
_ROUTING_STORES = frozenset({"entity_desc", "text_unit", "full_content"})

# BGE 라우터 싱글톤. 전용 _executor 스레드에서만 로드/사용(단일 워커라 락 불필요).
# 로드 실패는 _ROUTER_FAILED로 박제해 매 질문 재시도하지 않고 global로 폴백한다.
_ROUTER: Any = None
_ROUTER_FAILED = False


def _get_router() -> Any:
    """BGE 라우터를 lazy 로드해 돌려준다(실패/비활성 시 None -> global 폴백).
    _executor 단일 스레드에서만 호출되므로 별도 락 없이 안전하다."""
    global _ROUTER, _ROUTER_FAILED
    if _ROUTER is not None or _ROUTER_FAILED or not ROUTING_ENABLED:
        return _ROUTER
    try:
        from backend.routing.routing_bge import BGERouter

        t0 = time.perf_counter()
        _ROUTER = BGERouter()
        logger.info("BGE 라우터 로드 완료 %.1fs (model=%s)", time.perf_counter() - t0, _ROUTER.model_path)
    except Exception as e:  # noqa: BLE001  로드 실패는 박제하고 global 폴백.
        _ROUTER_FAILED = True
        logger.warning("BGE 라우터 로드 실패(라우팅 비활성, global 폴백): %s", e)
    return _ROUTER


def _route_mode(question: str, method: Optional[str], st: "_SnapshotState") -> tuple[str, list]:
    """질문을 local/global/basic 으로 해소하고 (mode, entity_hits)를 반환한다. method가
    'local'/'global'/'basic'이면 그대로 강제(엔티티 힌트 없음), 그 외('auto'/None)면 라우터
    결정 + 매치된 엔티티(entity_hits)도 함께. 라우터 없음/예외면 global 폴백(검색 안 깨짐)."""
    if method in ("local", "global", "basic"):
        return method, []
    router = _get_router()
    if router is None:
        return "global", []
    try:
        r = router.route(question, st.entity_titles)
        return r.mode, list(r.entity_hits or [])
    except Exception as e:  # noqa: BLE001  라우팅 실패는 global 폴백.
        logger.warning("라우팅 실패(global 폴백): %s", e)
        return "global", []


def _extract_titles(bundle: Any) -> list[str]:
    """번들의 entities DataFrame에서 엔티티 title 목록을 뽑는다(엔티티-히트 가드용)."""
    try:
        df = bundle.dfs.get("entities")
        if df is None or "title" not in df.columns:
            return []
        return [str(x).strip() for x in df["title"].dropna().astype(str).tolist() if str(x).strip()]
    except Exception:  # noqa: BLE001  title 추출 실패는 빈 목록(가드만 비활성, 라우팅은 동작).
        return []


# global search가 무데이터 시 코드 레벨(프롬프트 미경유)에서 반환하는 graphrag 영어 거절.
# graphrag.prompts.query.global_search_reduce_system_prompt.NO_DATA_ANSWER 와 동일 문자열.
# local/basic은 프롬프트의 한국어 거절 문구를 쓰므로 보통 여기 안 걸리지만, 모드 무관하게
# 방어적으로 처리한다. graphrag가 이 문자열을 바꾸면 매칭이 빗나가 영어가 그대로 나갈 뿐
# (무해 degrade). 한국어 문구는 쿼리 프롬프트(local/global/basic)의 거절 문구와 동일하게 맞췄다.
_GRAPHRAG_NO_DATA = "I am sorry but I am unable to answer this question given the provided data."
KOREAN_NO_DATA = "현재 주신 자료에는 없는 내용이에요. 다시 한 번 확인해주세요."


def _localize_no_data(answer: str) -> str:
    """graphrag global search의 코드 레벨 영어 무데이터 거절을 한국어 고정 문구로 바꾼다."""
    return KOREAN_NO_DATA if answer.strip() == _GRAPHRAG_NO_DATA else answer

ROOT = Path(__file__).resolve().parent.parent  # backend/ -> repo root

# POST /snapshots/register는 내부 전용(127.0.0.1 바인드 전제, 외부 노출 금지). 임의
# 파일시스템 경로 로드를 막기 위해, 등록 path는 이 루트들 아래만 허용한다:
#   snapshots - showcase/검증 스냅샷
#   var/jobs          - 오케스트레이터 잡 산출물
_ALLOWED_REGISTER_ROOTS = (
    ROOT / "snapshots",
    ROOT / "var" / "jobs",
)

# --- 스냅샷 레지스트리 ---------------------------------------------------------
# 키 = run_id(제품/콘텐츠 정체성), 값 = 스냅샷 디렉터리(빌드/provenance, repo 상대).
# 런타임에 추가 가능한 가변 dict(미래 오케스트레이터가 빌드 후 register).
SNAPSHOTS: dict[str, str] = {
    "korean_history": "snapshots/repro_run3",
    # statistics: 재인덱싱 전까지 snapshots/statistics 없음 -> warmup 에러 격리(korean 무관).
    "statistics": "snapshots/statistics",
}

# alias -> 정규 run_id. 빌드/provenance 이름(repro_run3)이나 구버전 키를 받아준다.
# repro_run3는 디렉터리명이자 예전 serve.py 기본 키였다 -> 같은 국사 엔진으로 보낸다.
ALIASES: dict[str, str] = {
    "repro_run3": "korean_history",
}


def _resolve_key(requested: Optional[str]) -> Optional[str]:
    """요청 snapshot 값을 정규 run_id로 해소(alias 우선). 미지정이면 None을 돌려준다.
    자동 기본 도메인은 두지 않는다(특정 도메인으로 조용히 떨어지지 않게): 호출부가
    명시 키를 요구한다."""
    if not requested:
        return None
    return ALIASES.get(requested, requested)


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


class _SnapshotState:
    """한 스냅샷(run_id)의 warmup 결과/상태. readiness/error는 키별로 격리된다."""

    def __init__(self, run_id: str, snapshot_dir: str) -> None:
        self.run_id = run_id
        self.snapshot_dir = snapshot_dir
        self.ready: bool = False
        self.error: Optional[str] = None
        self.warmup_seconds: Optional[float] = None
        self.engine: Any = None  # warm_query.LoadedEngine
        self.synthesis_model: Optional[str] = None
        self.entity_titles: list[str] = []  # 라우터 엔티티-히트 가드용(warm 시 채움)


class _State:
    """전체 서빙 상태: run_id -> _SnapshotState."""

    def __init__(self) -> None:
        self.snapshots: dict[str, _SnapshotState] = {}


STATE = _State()


def _warm_one(st: _SnapshotState) -> None:
    """전용 _executor 스레드에서 한 스냅샷을 global 엔진으로 warm load한다. startup
    warmup과 런타임 register가 공유한다. 결과는 st에 in-place로 기록(예외도 격리)."""
    from backend import query as wq

    t0 = time.perf_counter()
    try:
        # global만 서빙 -> 임베딩 스토어/LanceDB 미접근. 합성 모델만 RAG config로 배선.
        # 라우팅 ON이면 local 엔진이 쓸 임베딩 스토어(entity_description LanceDB 등)까지
        # 연다. OFF면 None -> global 에 필요한 것만(기존 경량 경로).
        bundle = wq.load_engine(
            st.snapshot_dir,
            method="global",
            synthesis_model=RAG_SYNTHESIS_MODEL,
            open_stores=_ROUTING_STORES if ROUTING_ENABLED else None,
        )
        st.engine = bundle
        if ROUTING_ENABLED:
            st.entity_titles = _extract_titles(bundle)
        # 빌드된 엔진이 실제로 바인딩한 모델을 확인해 찍는다(검증용).
        eng = bundle.engine("global")
        bound = getattr(eng, "model", None)
        bound_cfg = getattr(bound, "_model_config", None)
        if bound_cfg is not None:
            st.synthesis_model = bound_cfg.azure_deployment_name or bound_cfg.model
        else:
            st.synthesis_model = bundle.synthesis_model
        st.warmup_seconds = time.perf_counter() - t0
        st.ready = True
        st.error = None
        logger.info(
            "warmup done: key=%s dir=%s synthesis_model=%s %.1fs",
            st.run_id, st.snapshot_dir, st.synthesis_model, st.warmup_seconds,
        )
    except Exception as e:  # noqa: BLE001  키별 격리: 하나 실패해도 나머지 진행.
        st.engine = None
        st.ready = False
        st.error = f"{type(e).__name__}: {e}"
        logger.exception("warmup 실패: key=%s dir=%s -> %s", st.run_id, st.snapshot_dir, st.error)


def _register_pending_snapshots() -> None:
    """showcase 스냅샷마다 pending _SnapshotState를 동기로 만들어 둔다. 백그라운드
    warmup이 그 키에 닿기 전이라도 /health·/query·/ready가 처음부터 'warming'(503)으로
    답하게 한다. 이게 없으면 백그라운드 로드 구간에 알려진 키가 503 대신 404로 샌다."""
    for run_id, snapshot_dir in SNAPSHOTS.items():
        STATE.snapshots.setdefault(run_id, _SnapshotState(run_id, snapshot_dir))


def _warmup_blocking() -> None:
    """전용 스레드에서 실행. 레지스트리의 모든 showcase 스냅샷을 제자리에서 warm load한다.
    pending 상태는 이미 _register_pending_snapshots가 만들어 뒀다(없으면 방어적으로 생성).
    한 스냅샷 실패가 다른 스냅샷을 막지 않도록 키별로 error가 격리된다."""
    for run_id, snapshot_dir in SNAPSHOTS.items():
        st = STATE.snapshots.get(run_id)
        if st is None:  # 방어: register가 생략됐어도 안전하게.
            st = _SnapshotState(run_id, snapshot_dir)
            STATE.snapshots[run_id] = st
        _warm_one(st)
    # 스냅샷 warm 뒤 라우터를 사전 로드(첫 auto 질문이 113s 모델 로드를 떠안지 않게).
    # 실패해도 _get_router가 흡수하고 이후 질문은 global로 폴백한다.
    if ROUTING_ENABLED:
        _get_router()


# 답변에 함께 줄 "관련 개념" 엔티티 상한(degree 상위 N). 커뮤니티가 크면 전부 주면 과해서
# 자른다. env 로 조정 가능.
_SOURCE_MAX_ENTITIES = int(os.environ.get("RAG_SOURCE_MAX_ENTITIES") or 12)

_REPORTS_RE = re.compile(r"Reports?\s*\(([^)]*)\)")
_ENTITIES_RE = re.compile(r"Entities?\s*\(([^)]*)\)")


def _cited_nums(text: str, pat: "re.Pattern") -> set[int]:
    """답변/리포트 본문의 [Data: ...] 인용에서 숫자 id 만 뽑는다('+more' 등은 무시)."""
    out: set[int] = set()
    for m in pat.finditer(text or ""):
        for tok in m.group(1).split(","):
            tok = tok.strip()
            if tok.isdigit():
                out.add(int(tok))
    return out


def _as_id_list(v) -> list[str]:
    """communities.entity_ids 값(numpy array / list / 문자열)을 uuid 문자열 리스트로."""
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    if hasattr(v, "tolist"):
        return [str(x) for x in v.tolist()]
    if isinstance(v, str):
        try:
            return [str(x) for x in ast.literal_eval(v)]
        except Exception:  # noqa: BLE001
            return re.findall(r"[0-9a-fA-F-]{8,}", v)
    return []


def _extract_sources(answer: str, bundle, max_entities: int = _SOURCE_MAX_ENTITIES) -> Optional[dict]:
    """답변의 [Data: Reports (...)] 인용을 그 커뮤니티의 구성 엔티티로 펼쳐(=(B)) degree 상위
    N 개를 '관련 개념'으로 돌려준다. local 인용의 Entities()도 직접 흡수. best-effort:
    실패하면 None(답변은 그대로 나간다)."""
    try:
        import pandas as pd

        dfs = getattr(bundle, "dfs", None) or {}
        cr, comm, ent = dfs.get("community_reports"), dfs.get("communities"), dfs.get("entities")
        if ent is None:
            return None
        report_nums = _cited_nums(answer, _REPORTS_RE)
        entity_nums = _cited_nums(answer, _ENTITIES_RE)

        reports_out: list[dict] = []
        community_ids: set[str] = set()
        if cr is not None and report_nums:
            want = {str(n) for n in report_nums}
            rows = cr[cr["community"].astype(str).isin(want)
                      | cr["human_readable_id"].astype(str).isin(want)]
            seen = set()
            for _, r in rows.iterrows():
                c = str(r["community"])
                community_ids.add(c)
                if c not in seen:
                    seen.add(c)
                    reports_out.append({"id": c, "title": r.get("title")})

        uuids: set[str] = set()
        if comm is not None and community_ids:
            crows = comm[comm["community"].astype(str).isin(community_ids)]
            for v in crows["entity_ids"]:
                uuids.update(_as_id_list(v))

        sel = ent[ent["id"].astype(str).isin(uuids)
                  | ent["human_readable_id"].astype(str).isin({str(n) for n in entity_nums})]
        if "degree" in sel.columns:
            sel = sel.sort_values("degree", ascending=False)
        total = int(len(sel))
        entities_out = []
        for _, r in sel.head(max_entities).iterrows():
            desc = str(r.get("description") or "").strip()
            hr = r.get("human_readable_id")
            entities_out.append({
                "id": int(hr) if pd.notna(hr) else None,
                "title": r.get("title"),
                "type": r.get("type"),
                "degree": int(r["degree"]) if "degree" in r and pd.notna(r["degree"]) else None,
                "description": desc[:200],
            })
        if not entities_out and not reports_out:
            return None
        return {"reports": reports_out, "entities": entities_out, "entities_total": total}
    except Exception as e:  # noqa: BLE001
        logger.warning("sources 추출 실패(답변은 그대로 반환): %s", e)
        return None


def _search_blocking(run_id: str, question: str, method: Optional[str] = "auto") -> tuple[str, str, Optional[dict]]:
    """전용 스레드에서 해당 스냅샷 search 한 번. 먼저 method를 local/global로 해소(auto면
    라우터)한 뒤 그 엔진으로 검색한다. warm_query와 동일하게 asyncio.run으로 코루틴을
    돌린다(이 스레드엔 루프가 없으므로 OK). (answer, 사용한 mode)를 돌려준다."""
    st = STATE.snapshots[run_id]
    mode, entity_hits = _route_mode(question, method, st)
    eng = st.engine.engine(mode)
    # 라우터가 찾은 엔티티를 local 컨텍스트에 강제 포함(include_entity_names). graphrag의
    # 커뮤니티-필터 엔티티 집합에서 빠진 orphan(예: degree=0)도 이 경로로 grounded 가능.
    cbp = getattr(eng, "context_builder_params", None)
    inject = mode == "local" and bool(entity_hits) and isinstance(cbp, dict)
    if inject:
        prev = cbp.get("include_entity_names")
        cbp["include_entity_names"] = entity_hits
    try:
        result = asyncio.run(eng.search(question))
    finally:
        if inject:
            if prev is None:
                cbp.pop("include_entity_names", None)
            else:
                cbp["include_entity_names"] = prev
    answer = _localize_no_data(result.response if hasattr(result, "response") else str(result))
    # 답변 인용을 근거(관련 개념)로 구조화. st.engine 은 dfs 를 든 LoadedEngine 번들.
    sources = _extract_sources(answer, st.engine)
    return answer, mode, sources


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 모든 스냅샷을 백그라운드로 warmup한다. 무거운 로드를 startup 경로에서
    빼서 앱이 즉시 바인드되고 /health가 곧장 응답하게 한다(콜드 시작이 헬스 프로브를
    막지 않음). 준비된 스냅샷부터 ready로 바뀌고, 아직이면 /query·/ready는 503을 준다.

    먼저 pending 상태를 동기 등록(첫 요청부터 503 'warming' 보장), 그 다음 비차단 warmup을
    전용 스레드에 던진다. warmup 예외는 키별로 _warmup_blocking 안에서 격리된다."""
    loop = asyncio.get_running_loop()
    _install_model_logger()
    _register_pending_snapshots()
    logger.info("warmup 시작(백그라운드): %d개 스냅샷 (%s)", len(SNAPSHOTS), ", ".join(SNAPSHOTS))
    app.state.warmup_future = loop.run_in_executor(_executor, _warmup_blocking)
    yield
    _executor.shutdown(wait=False)


app = FastAPI(title="회랑 RAG 서빙 코어", lifespan=lifespan)


_METHOD_DESC = (
    "검색 모드. 'auto'(기본): BGE 라우터가 local/global 자동 선택. "
    "'local'/'global': 강제. 라우팅 OFF/실패 시 'auto'는 global로 폴백."
)


class QueryRequest(BaseModel):
    question: str = Field(..., description="자연어 질문")
    snapshot: Optional[str] = Field(
        default=None,
        description=(
            "대상 데이터셋 키(run_id) 또는 alias. 미지정 시 기본 스냅샷. "
            f"등록 키: {', '.join(SNAPSHOTS)} (alias: {', '.join(ALIASES) or '-'})."
        ),
    )
    method: Optional[str] = Field(default="auto", description=_METHOD_DESC)


class QueryResponse(BaseModel):
    answer: str
    snapshot: str  # 실제로 답한 키(showcase run_id 또는 live job_id).
    mode: Optional[str] = None  # 실제로 사용한 검색 모드(local/global).
    # sources: 답변이 인용한 근거를 구조화해 함께 준다. global은 Reports(커뮤니티) 인용만
    # 나오므로 그 커뮤니티의 구성 엔티티로 펼쳐(degree 상위 N) "관련 개념"으로 내려준다
    # (정확한 사용 엔티티가 아니라 근사 superset). local 인용의 Entities()도 같이 흡수.
    sources: Optional[dict] = None
    # related_nodes(팰리스 방 연결)는 프론트가 entities[].title 로 나중에 잇는다.


class RegisterRequest(BaseModel):
    key: str = Field(..., description="레지스트리 키. 라이브 잡은 job_id.")
    path: str = Field(..., description="스냅샷 디렉터리(허용 루트 아래여야 함).")


class JobQueryRequest(BaseModel):
    question: str = Field(..., description="자연어 질문")
    method: Optional[str] = Field(default="auto", description=_METHOD_DESC)


def _validate_snapshot_path(path: str) -> Path:
    """register path가 허용 루트(snapshots 또는 var/jobs) 아래인지 검증.
    임의 파일시스템 경로 로드를 막는다. 통과 시 resolve된 절대 경로 반환."""
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    p = p.resolve()
    for root in _ALLOWED_REGISTER_ROOTS:
        if p == root.resolve() or p.is_relative_to(root.resolve()):
            return p
    raise ValueError(
        f"path '{path}' 허용 루트 밖. snapshots 또는 var/jobs 아래만 등록 가능."
    )


async def _run_query(
    key: str, question: str, method: Optional[str] = "auto",
) -> tuple[str, str, Optional[dict]]:
    """키 -> 번들 -> (라우팅된) search. /query와 /jobs/{id}/query가 공유하는 코어.
    검색은 _executor 단일 스레드에서 직렬 실행된다. (answer, mode, sources) 반환."""
    st = STATE.snapshots.get(key)
    if st is None:
        raise HTTPException(
            status_code=404,
            detail=f"'{key}' 미등록 (등록됨: {', '.join(STATE.snapshots) or '-'}).",
        )
    if st.error:
        raise HTTPException(status_code=503, detail=f"'{key}' warmup 실패: {st.error}")
    if not st.ready or st.engine is None:
        raise HTTPException(status_code=503, detail=f"'{key}' warmup 진행 중. 잠시 후 재시도.")

    q = question.strip()
    if not q:
        raise HTTPException(status_code=422, detail="question이 비어 있다.")

    loop = asyncio.get_running_loop()
    t0 = time.perf_counter()
    answer, mode, sources = await loop.run_in_executor(_executor, _search_blocking, key, q, method)
    logger.info("query [%s] mode=%s %.1fs: %s", key, mode, time.perf_counter() - t0, q[:50])
    return answer, mode, sources


def _snapshot_health(st: Optional[_SnapshotState], snapshot_dir: str) -> dict:
    if st is None:
        return {"status": "pending", "ready": False, "snapshot_dir": snapshot_dir}
    if st.error:
        return {
            "status": "error",
            "ready": False,
            "error": st.error,
            "snapshot_dir": snapshot_dir,
        }
    return {
        "status": "ok" if st.ready else "warming",
        "ready": st.ready,
        "snapshot_dir": snapshot_dir,
        "warmup_seconds": round(st.warmup_seconds, 1) if st.warmup_seconds else None,
        "synthesis_model": st.synthesis_model,
    }


@app.get("/health")
async def health():
    """스냅샷별 warmup 상태 맵. 어느 하나라도 떴으면 ok."""
    snaps = {
        run_id: _snapshot_health(STATE.snapshots.get(run_id), snapshot_dir)
        for run_id, snapshot_dir in SNAPSHOTS.items()
    }
    any_ready = any(s.get("ready") for s in snaps.values())
    return {
        "status": "ok" if any_ready else "warming",
        "method": "global",
        "aliases": ALIASES,
        "snapshots": snaps,
    }


@app.get("/ready")
async def ready(snapshot: Optional[str] = None):
    """준비 게이트. /health가 항상 200(헬스 프로브가 콜드 시작에 컨테이너를 안 죽이게)인
    것과 달리, /ready는 준비가 안 됐으면 503을 돌려준다. warm/poll 스크립트와 데모 전
    게이팅에 쓴다.

    snapshot 지정: 그 키 하나의 준비 여부만 본다(미등록이면 404). 미지정: 등록된 모든
    showcase 스냅샷이 준비됐을 때만 200. statistics처럼 한 스냅샷이 error여도 격리되므로,
    특정 스냅샷만 게이팅하려면 snapshot 파라미터로 그 키를 콕 집어라."""
    if snapshot is not None:
        key = _resolve_key(snapshot)
        st = STATE.snapshots.get(key)
        if st is None and key not in SNAPSHOTS:
            return JSONResponse(
                status_code=404,
                content={"ready": False, "snapshot": key, "detail": f"'{key}' 미등록."},
            )
        snapshot_dir = st.snapshot_dir if st is not None else SNAPSHOTS.get(key, "?")
        detail = _snapshot_health(st, snapshot_dir)
        is_ready = bool(detail.get("ready"))
        return JSONResponse(
            status_code=200 if is_ready else 503,
            content={"ready": is_ready, "snapshot": key, "detail": detail},
        )

    snaps = {
        run_id: _snapshot_health(STATE.snapshots.get(run_id), snapshot_dir)
        for run_id, snapshot_dir in SNAPSHOTS.items()
    }
    all_ready = bool(snaps) and all(s.get("ready") for s in snaps.values())
    return JSONResponse(
        status_code=200 if all_ready else 503,
        content={"ready": all_ready, "snapshots": snaps},
    )


@app.post("/snapshots/register")
async def register_snapshot(req: RegisterRequest):
    """런타임 스냅샷 등록(내부 전용). 오케스트레이터 rag 스테이지가 빌드된 잡 스냅샷을
    여기에 register하면 /jobs/{key}/query로 답할 수 있다. 외부 노출 금지(127.0.0.1).

    warm은 반드시 _executor 단일 스레드에서 일어난다(LanceDB 친화성 + asyncio.run
    제약). 같은 키 재등록은 멱등(덮어쓰기 -> 재빌드)."""
    try:
        snap = _validate_snapshot_path(req.path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    st = _SnapshotState(req.key, str(snap))
    STATE.snapshots[req.key] = st  # 멱등: 같은 키 덮어쓰기.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, _warm_one, st)
    if st.error:
        raise HTTPException(status_code=500, detail=f"register warm 실패: {st.error}")
    logger.info("registered: key=%s dir=%s", req.key, st.snapshot_dir)
    return {
        "registered": req.key,
        "snapshot_dir": st.snapshot_dir,
        "ready": st.ready,
        "synthesis_model": st.synthesis_model,
        "warmup_seconds": round(st.warmup_seconds, 1) if st.warmup_seconds else None,
    }


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    """질문 -> (snapshot 라우팅) -> global search -> 답 텍스트. showcase 진입점."""
    key = _resolve_key(req.snapshot)
    # 자동 기본 도메인이 없으므로 무키 요청은 명시적으로 막는다(국사로 조용히 안 떨어짐).
    if key is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "snapshot 키가 필요합니다. 등록 키: "
                f"{', '.join(SNAPSHOTS)} (alias: {', '.join(ALIASES) or '-'})."
            ),
        )
    # showcase(alias 포함) 또는 런타임 등록 키가 아니면 명시적으로 막는다.
    if key not in SNAPSHOTS and key not in STATE.snapshots:
        raise HTTPException(
            status_code=400,
            detail=(
                f"스냅샷 '{req.snapshot}' 미등록. 등록 키: {', '.join(SNAPSHOTS)} "
                f"(alias: {', '.join(ALIASES) or '-'})."
            ),
        )
    answer, mode, sources = await _run_query(key, req.question, req.method)
    return QueryResponse(answer=answer, snapshot=key, mode=mode, sources=sources)


@app.post("/jobs/{job_id}/query", response_model=QueryResponse)
async def job_query(job_id: str, req: JobQueryRequest):
    """잡별 질의. 라이브 등록 키 = job_id이므로 키 라우팅 한 줄이다(코어 공유).
    잡 메타는 오케스트레이터(/jobs/{id}/status) 소관이고 여기선 엔진만 라우팅한다."""
    answer, mode, sources = await _run_query(job_id, req.question, req.method)
    return QueryResponse(answer=answer, snapshot=job_id, mode=mode, sources=sources)
