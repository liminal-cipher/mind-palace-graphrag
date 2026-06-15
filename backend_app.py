"""App Service co-locate 진입점: serve(RAG 서빙) + orchestrator(업로드 파이프라인)를
한 프로세스에 올린다.

왜 합치나: App Service 한 인스턴스는 포트 하나만 외부로 노출한다. 프론트는 serve(/query)
와 orchestrator(/upload, /jobs/{id}/status)를 둘 다 호출해야 하므로, 둘을 한 ASGI 앱으로
마운트해 같은 포트로 노출한다. serve는 루트(/)에, orchestrator는 /orchestrator 아래에
마운트한다(둘 다 /health·/jobs/{id}/... 경로를 가져 루트를 공유하면 충돌이 나기 때문):

    GET  /health                     -> serve health (항상 200, 헬스 프로브용)
    GET  /ready                      -> serve 준비 게이트(미준비면 503)
    POST /query                      -> serve global search
    POST /jobs/{id}/query            -> serve 잡별 질의
    POST /orchestrator/upload        -> orchestrator 업로드
    GET  /orchestrator/jobs/{id}/... -> orchestrator 상태/팰리스

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


app = FastAPI(title="회랑 heavy backend (serve + orchestrator)", lifespan=lifespan)

# 더 구체적인 프리픽스를 먼저 마운트한다. /orchestrator가 먼저 매칭되고, 나머지는 serve로.
app.mount("/orchestrator", orchestrator_app)
app.mount("/", serve_app)
