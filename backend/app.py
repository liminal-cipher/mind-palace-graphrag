"""App Service co-locate 진입점: serve(RAG 서빙) + orchestrator(업로드 파이프라인)를
한 프로세스에 올린다.

왜 합치나: App Service 한 인스턴스는 포트 하나만 외부로 노출한다. 프론트는 serve(/query),
orchestrator(/upload, /jobs/{id}/status), 그리고 팰리스 보기(/palace, /images)를 모두
호출해야 하므로, 전부 한 ASGI 앱으로 얹어 같은 포트로 노출한다. 이로써 통합 backend_app은
가벼운 showcase_api(/palace·/images)의 완전한 superset이 된다. serve는 루트(/)에,
orchestrator는 /orchestrator 아래에 마운트하고, 팰리스/이미지 라우트는 '/' 마운트 '앞'에
등록한다(serve의 '/' 캐치올보다 먼저 매칭되도록):

    GET  /health                     -> serve health (항상 200, 헬스 프로브용)
    GET  /ready                      -> serve 준비 게이트(미준비면 503)
    POST /query                      -> serve global search
    POST /jobs/{id}/query            -> serve 잡별 질의
    GET  /palace/{name}              -> 동결 쇼케이스 _with_images 팰리스(예: korean_history)
    GET  /images/...                 -> 팰리스 참조 PNG 정적 마운트
    POST /orchestrator/upload        -> orchestrator 업로드
    GET  /orchestrator/jobs/{id}/status  -> orchestrator 잡 상태
    GET  /orchestrator/jobs/{id}/palace  -> 라이브 잡이 빌드한 팰리스(프론트가 가져감)

lifespan 주의: Starlette는 mount된 서브앱의 lifespan을 자동 실행하지 않는다. serve의
백그라운드 warmup과 orchestrator의 워커 스레드는 둘 다 lifespan에서 시작되므로, 부모
lifespan에서 두 서브앱 lifespan을 AsyncExitStack으로 직접 연다.

프로세스 모델: gunicorn 워커 1개로 띄운다(startup.sh). serve가 스냅샷을 RAM에 상주시키
므로 워커를 늘리면 워커마다 스냅샷이 복제돼 RAM이 N배가 된다. 인덱싱 subprocess와의 RAM
경쟁 때문에 B2/B3 플랜을 권장한다(런북 참조). serve의 register는 내부 전용이라 orchestrator
rag 스테이지가 같은 프로세스 안에서 http://127.0.0.1:<port> 로 호출한다(config.SERVE_URL).
"""
import logging
import os
import time
from contextlib import AsyncExitStack, asynccontextmanager

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("backend.auth")

# 인증 없이 통과시킬 경로(헬스/레디니스 프로브). 통합 앱 기준 풀패스. App Service 의
# 헬스 프로브가 항상 200/503 을 받아야 컨테이너를 죽이지 않으므로 게이트에서 제외한다.
_AUTH_EXEMPT_PATHS = {"/health", "/ready", "/orchestrator/health"}


async def _auth_dispatch(request, call_next):
    """공개 엔드포인트 앞단 인증 게이트.

    정책(점진 도입):
      - API_KEY 환경변수가 *설정된 경우에만* 인증을 강제한다. 미설정이면 비활성
        (로컬/데모 무중단). 운영 배포 시 App Settings 에 API_KEY 를 반드시 넣는다.
      - 헬스/레디니스 프로브와 CORS preflight(OPTIONS)는 항상 통과.
      - 같은 컨테이너 내부(loopback) 호출은 신뢰한다(오케스트레이터→serve register 등
        내부 seam). App Service 외부 트래픽은 프록시 IP 로 들어와 loopback 이 아니므로
        키가 필요하다.
    """
    if request.method == "OPTIONS" or request.url.path in _AUTH_EXEMPT_PATHS:
        return await call_next(request)
    api_key = os.environ.get("API_KEY")
    if not api_key:
        return await call_next(request)  # 미설정 → 인증 비활성(데모/로컬).
    client = request.client.host if request.client else None
    if client in ("127.0.0.1", "::1") or request.headers.get("x-api-key") == api_key:
        return await call_next(request)
    return JSONResponse(status_code=401, content={"detail": "유효한 API 키가 필요합니다(X-API-Key 헤더)."})


# ── 레이트리미팅(인메모리 고정 윈도우, per-IP) ──────────────────────────────────
# 단일 gunicorn 워커 전제(startup.sh)라 프로세스 메모리 상태로 충분하다. 무인증·개방
# CORS 와 겹친 유료 LLM/무거운 질의 남용(비용·DoS)을 완화한다. WAF/API 게이트웨이의
# 대체가 아니라 1차 가드다(RATE_LIMIT_PER_MIN=0 이면 비활성).
_RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN") or 120)
_RATE_WINDOW_S = 60.0
_rate_state: dict[str, list] = {}  # ip -> [window_start(monotonic), count]


def _client_ip(request) -> str:
    """클라이언트 IP 추정. App Service 는 프록시 뒤라 X-Forwarded-For 선두를 우선한다
    (스푸핑 가능 = 완벽한 통제는 아니나 1차 가드로 충분). 없으면 실제 peer."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _ratelimit_dispatch(request, call_next):
    """per-IP 고정 윈도우 레이트리미터. 헬스/프리플라이트·loopback 내부 통신은 면제."""
    if request.method == "OPTIONS" or request.url.path in _AUTH_EXEMPT_PATHS:
        return await call_next(request)
    if _RATE_LIMIT_PER_MIN <= 0:
        return await call_next(request)
    ip = _client_ip(request)
    if ip in ("127.0.0.1", "::1"):  # 내부 seam(오케스트레이터→serve)은 제한 안 함.
        return await call_next(request)
    now = time.monotonic()
    state = _rate_state.get(ip)
    if state is None or now - state[0] >= _RATE_WINDOW_S:
        _rate_state[ip] = [now, 1]
        if len(_rate_state) > 10000:  # 만료 항목 정리(메모리 누수 방지).
            for k in [k for k, v in _rate_state.items() if now - v[0] >= _RATE_WINDOW_S]:
                _rate_state.pop(k, None)
        return await call_next(request)
    state[1] += 1
    if state[1] > _RATE_LIMIT_PER_MIN:
        retry = max(1, int(_RATE_WINDOW_S - (now - state[0])))
        return JSONResponse(
            status_code=429,
            content={"detail": f"요청이 너무 많습니다. {retry}초 후 다시 시도하세요."},
            headers={"Retry-After": str(retry)},
        )
    return await call_next(request)

from backend import showcase
from backend.mnemonic import routes as mnemonic_routes
from backend.quiz import quiz_page
from backend.quiz import quiz_json
from backend.serve import app as serve_app
from backend.serve import lifespan as serve_lifespan
from orchestrator.app import app as orchestrator_app
from orchestrator.app import lifespan as orchestrator_lifespan


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 마운트된 서브앱 lifespan은 자동 실행되지 않으므로 직접 연다. 둘 다 백그라운드
    # 작업을 시작한다: serve=스냅샷 warmup(비차단), orchestrator=잡 워커 스레드.
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(serve_lifespan(serve_app))
        await stack.enter_async_context(orchestrator_lifespan(orchestrator_app))
        yield


app = FastAPI(title="회랑 unified backend (palace + serve + orchestrator)", lifespan=lifespan)

if not os.environ.get("API_KEY"):
    logger.warning(
        "API_KEY 미설정 → 인증 게이트 비활성(모든 엔드포인트 공개). "
        "운영 배포 시 App Settings 에 API_KEY 를 설정하세요."
    )

# 미들웨어 등록 순서 = 실행 순서의 역(Starlette 는 나중에 등록한 것이 더 바깥). 런타임
# 바깥→안: CORS → 레이트리밋 → 인증 → 라우트. 인증을 가장 안쪽에 둬 레이트리밋이 인증보다
# 먼저 돌게(무인증 폭주도 차단), CORS 를 가장 바깥에 둬 401/429 응답에도 CORS 헤더가 붙게.
app.add_middleware(BaseHTTPMiddleware, dispatch=_auth_dispatch)
app.add_middleware(BaseHTTPMiddleware, dispatch=_ratelimit_dispatch)

# 가벼운 showcase_api 와 동일한 개방 CORS(프론트가 /palace·/images 를 GET 으로 가져감).
# serve/orchestrator 핸들러 로직은 안 건드린다(미들웨어는 응답 헤더만 추가).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],  # GET=showcase/query, POST=upload/query, DELETE=잡 삭제
    allow_headers=["*"],
)

# 라우트 등록 순서 = 매칭 우선순위. 더 구체적인 프리픽스를 serve 의 '/' 캐치올보다 먼저
# 등록해야 한다: /orchestrator -> /palace·/images(router) -> 마지막에 '/'(serve).
app.mount("/orchestrator", orchestrator_app)
app.include_router(showcase.router)  # GET /palace/{name}, GET /images/{name}/{file}
app.include_router(quiz_page.router)  # GET/POST /quiz + POST /quiz/grade (테스트 페이지, 서버 채점)
app.include_router(quiz_json.router)  # POST /quiz/json (인룸 퀴즈 JSON, quiz_page 재사용 - 추가만)
app.include_router(mnemonic_routes.router)  # POST /mnemonic (핫스팟→학습노드 연상 장면 생성)


@app.get("/api/speech-token")
def speech_token():
    """브라우저에 키 대신 10분짜리 토큰만 발급 (Azure Speech)."""
    region = os.environ.get("AZURE_SPEECH_REGION")
    key = os.environ.get("AZURE_SPEECH_KEY")
    if not region or not key:
        raise HTTPException(status_code=500, detail="speech not configured")
    resp = requests.post(
        f"https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken",
        headers={"Ocp-Apim-Subscription-Key": key},
        timeout=10,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="speech token issue failed")
    return {"token": resp.text, "region": region}


app.mount("/", serve_app)
