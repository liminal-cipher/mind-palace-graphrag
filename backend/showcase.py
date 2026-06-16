"""쇼케이스 팰리스 보기 + 이미지 라우트 (통합 backend_app 용).

backend_app 이 이걸 얹어, 단일 App Service 가 채팅(/query)·orchestrator 에 더해 (옛 가벼운
showcase_api 앱이 하던) 팰리스 보기까지 superset 으로 서빙한다. 동결 _with_images 팰리스
JSON 과 그 PNG 들을 그대로 재사용한다(중복 사본 없음). serve 가 '/' 를 쓰므로 backend_app 은
이 라우트들을 '/' 마운트 '앞'에 등록해 /palace·/images 로 충돌 없이 얹는다.

데이터 위치: 레포 루트 deliverables/<name>/. 도메인마다 자기완결 폴더(palace_with_images.json
+ images/<file>.png)다. 노드의 images[].path 는 deliverable 상대('images/fig_5_3.png')이고,
도메인을 URL 로 스코프해 GET /images/<name>/<file> 로 서빙한다.

라이브 잡 팰리스는 여기 없다: orchestrator 가 이미 GET /jobs/{id}/palace 로 서빙하고,
통합 앱에선 /orchestrator/jobs/{id}/palace 로 노출된다(프리베이크 쇼케이스 + 라이브 잡
둘 다 viewable).
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
DELIVERABLES = Path(__file__).resolve().parent.parent / "deliverables"  # backend/ -> repo root

# 쇼케이스 이름 -> 자기완결 deliverable 폴더(deliverables/<name>/). 팰리스 JSON 과
# 그 PNG(images/)가 한 폴더에 있다. 새 도메인은 deliverables/<name>/ 한 줄만 추가.
SHOWCASE_PALACES: dict[str, Path] = {
    "korean_history": DELIVERABLES / "korean_history" / "palace_with_images.json",
    "statistics": DELIVERABLES / "statistics" / "palace_with_images.json",
}

router = APIRouter()


@router.get("/palace/{name}")
def showcase_palace(name: str):
    """동결 쇼케이스 _with_images 팰리스 JSON 을 그대로 반환. 옛 showcase_api 앱의
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


@router.get("/images/{name}/{filename}")
def showcase_image(name: str, filename: str):
    """팰리스가 참조하는 PNG. 노드의 images[].path 는 deliverable 상대('images/fig_5_3.png')
    이므로 도메인을 URL 로 스코프: GET /images/korean_history/fig_5_3.png ->
    deliverables/korean_history/images/fig_5_3.png."""
    if name not in SHOWCASE_PALACES:
        raise HTTPException(status_code=404, detail=f"미등록 쇼케이스 '{name}'.")
    img_root = (DELIVERABLES / name / "images").resolve()
    path = (img_root / filename).resolve()
    if img_root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail=f"이미지 없음: {filename}")
    return FileResponse(path)
