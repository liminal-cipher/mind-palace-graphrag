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
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import showcase_view
from orchestrator.app import app as orchestrator_app
from orchestrator.app import lifespan as orchestrator_lifespan
from serve import app as serve_app
from serve import lifespan as serve_lifespan


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 마운트된 서브앱 lifespan은 자동 실행되지 않으므로 직접 연다. 둘 다 백그라운드
    # 작업을 시작한다: serve=스냅샷 warmup(비차단), orchestrator=잡 워커 스레드.
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(serve_lifespan(serve_app))
        await stack.enter_async_context(orchestrator_lifespan(orchestrator_app))
        yield


app = FastAPI(title="회랑 unified backend (palace + serve + orchestrator)", lifespan=lifespan)

# 가벼운 showcase_api 와 동일한 개방 CORS(프론트가 /palace·/images 를 GET 으로 가져감).
# serve/orchestrator 핸들러 로직은 안 건드린다(미들웨어는 응답 헤더만 추가).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# 라우트 등록 순서 = 매칭 우선순위. 더 구체적인 프리픽스를 serve 의 '/' 캐치올보다 먼저
# 등록해야 한다: /orchestrator -> /palace·/images(router) -> 마지막에 '/'(serve).
app.mount("/orchestrator", orchestrator_app)
app.include_router(showcase_view.router)  # GET /palace/{name}, GET /images/{name}/{file}
app.mount("/", serve_app)
