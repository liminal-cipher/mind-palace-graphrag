"""쇼케이스 팰리스 보기 + 이미지 라우트 (통합 backend_app 용).

backend_app 이 이걸 얹어, 단일 App Service 가 채팅(/query)·orchestrator 에 더해 가벼운
showcase_api 가 하던 팰리스 보기까지 superset 으로 서빙한다. 라우트/데이터는
showcase_api/main.py 와 동일하다: 동결 _with_images 팰리스 JSON 과 그 PNG 들을 그대로
재사용한다(중복 사본 없음). serve 가 '/' 를 쓰므로 backend_app 은 이 라우트들을 '/' 마운트
'앞'에 등록해 /palace·/images 로 충돌 없이 얹는다.

라이브 잡 팰리스는 여기 없다: orchestrator 가 이미 GET /jobs/{id}/palace 로 서빙하고,
통합 앱에선 /orchestrator/jobs/{id}/palace 로 노출된다(프리베이크 쇼케이스 + 라이브 잡
둘 다 viewable).
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_SHOWCASE_DIR = Path(__file__).resolve().parent / "showcase_api"
DATA_DIR = _SHOWCASE_DIR / "data"
IMAGES_DIR = _SHOWCASE_DIR / "images"

# 쇼케이스 이름 -> 동결 _with_images 팰리스 JSON(showcase_api/data 아래).
# ai_school 미등록: 교안 _with_images 팰리스가 아직 없다(STOP-and-report). 데이터가
# 생기면 여기 한 줄(`"ai_school": DATA_DIR / "ai_school_with_images.palace.json"`)만 추가.
SHOWCASE_PALACES: dict[str, Path] = {
    "korean_history": DATA_DIR / "korean_history_with_images.palace.json",
}

router = APIRouter()


@router.get("/palace/{name}")
def showcase_palace(name: str):
    """동결 쇼케이스 _with_images 팰리스 JSON 을 그대로 반환. showcase_api 의
    /palace/korean_history 와 동일 페이로프(프론트 기존 URL 호환)."""
    path = SHOWCASE_PALACES.get(name)
    if path is None:
        known = ", ".join(SHOWCASE_PALACES) or "-"
        raise HTTPException(
            status_code=404,
            detail=f"미등록 쇼케이스 팰리스 '{name}'. 등록: {known}.",
        )
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"팰리스 파일 없음: {path.name}")
    return FileResponse(path, media_type="application/json")


def images_staticfiles() -> StaticFiles:
    """팰리스가 참조하는 PNG 정적 마운트(showcase_api/images). 노드의 images[].path 를
    그대로 미러: 'input/korean_history/img/fig_5_3.png' -> GET /images/input/korean_history/img/fig_5_3.png."""
    return StaticFiles(directory=IMAGES_DIR)
