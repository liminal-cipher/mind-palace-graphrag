"""통합 backend_app이 가벼운 showcase_api의 superset임을 검증한다.

팰리스/이미지/health 라우트는 lifespan(serve warmup·orchestrator 워커) 없이 직접 친다:
TestClient를 컨텍스트 매니저로 쓰지 않으면 lifespan이 안 돌아 graphrag warmup이 트리거되지
않으므로 빠르고 hermetic하다. query/orchestrator는 구조적으로 각 서브앱(serve/orchestrator)에
라우팅됨을 확인한다(채팅 응답 내용·라이브 e2e는 orchestrator/smoke_e2e.py 담당)."""
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.routing import Mount

from backend import app as backend_app

ROOT = Path(__file__).resolve().parent
PALACE_JSON = ROOT / "deliverables" / "korean_history" / "palace_with_images.json"


def _client() -> TestClient:
    # 컨텍스트 매니저 없이 -> lifespan 미실행 -> 스냅샷 warmup이 안 돈다(라우팅만 검증).
    return TestClient(backend_app.app)


def test_palace_korean_history_identical_to_showcase():
    """/palace/korean_history가 가벼운 쇼케이스가 주던 JSON과 byte 동일."""
    r = _client().get("/palace/korean_history")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.content == PALACE_JSON.read_bytes()


def test_palace_unknown_is_404():
    """교안(ai_school) _with_images 팰리스는 아직 없음 -> 명확한 404."""
    r = _client().get("/palace/ai_school")
    assert r.status_code == 404


def test_image_served():
    """팰리스 참조 PNG 라우트가 이미지 1개를 200으로 준다."""
    r = _client().get("/images/korean_history/fig_10_2.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert len(r.content) > 0


def test_health_always_200_without_warmup():
    """/health는 warmup 전에도 200(헬스 프로브가 콜드 시작에 컨테이너를 안 죽이게)."""
    r = _client().get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "warming")


def test_palace_and_images_registered_before_serve_catchall():
    """serve의 '/' 캐치올보다 /palace·/images가 먼저 등록돼야 매칭된다."""
    paths = [getattr(r, "path", "") for r in backend_app.app.routes]
    assert "/palace/{name}" in paths
    assert "/images/{name}/{filename}" in paths
    # '' = serve가 마운트된 '/' (Starlette Mount의 path).
    assert paths.index("/palace/{name}") < paths.index("")
    assert paths.index("/images/{name}/{filename}") < paths.index("")


def test_query_and_orchestrator_route_to_their_subapps():
    """'/' -> serve(/query 보유), '/orchestrator' -> orchestrator(/upload 보유)."""
    mounts = {r.path: r.app for r in backend_app.app.routes if isinstance(r, Mount)}
    assert mounts[""] is backend_app.serve_app
    assert mounts["/orchestrator"] is backend_app.orchestrator_app
    serve_paths = [getattr(x, "path", "") for x in backend_app.serve_app.routes]
    orch_paths = [getattr(x, "path", "") for x in backend_app.orchestrator_app.routes]
    assert "/query" in serve_paths
    assert "/jobs/{job_id}/query" in serve_paths
    assert "/upload" in orch_paths
    assert "/jobs/{job_id}/palace" in orch_paths  # 라이브 잡 팰리스 보기 경로
