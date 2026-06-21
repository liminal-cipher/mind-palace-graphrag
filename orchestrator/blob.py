"""라이브 잡 산출물의 Blob 영속 — 재시작에도 살아남게.

graphrag 의 var/jobs/<id> 는 로컬 디스크라 서버 재시작 시 휘발한다(config.py 참고).
매칭된 이미지(palace_out/images/*.png)를 Blob 에 올려, 잡 기록(SQLite)이 사라진 뒤에도
job_id + 파일명만으로 그림을 돌려줄 수 있게 한다 — 서빙을 잡 DB 와 분리한다.

계정은 Mindpalace_fork 와 같은 AZURE_APP_STORAGE_CONNECTION_STRING 을 재사용하고(없으면
AZURE_STORAGE_CONNECTION_STRING), 컨테이너만 graphrag-jobs 로 분리한다. 미설정이면 모든
함수가 no-op/None 이라 기존 로컬 전용 동작이 그대로 유지된다(하위호환).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("orchestrator.blob")

# 잡 산출물 전용 컨테이너(Mindpalace_fork 의 library/models 와 분리). 첫 사용 시 자동 생성.
CONTAINER = os.getenv("GRAPHRAG_BLOB_CONTAINER", "graphrag-jobs")

_container_singleton = None
_resolved = False


def _container():
    """잡 산출물 컨테이너 클라이언트(캐시). 미설정/오류 시 None(→ 로컬 전용 폴백)."""
    global _container_singleton, _resolved
    if _resolved:
        return _container_singleton
    _resolved = True
    # Mindpalace_fork 와 같은 계정 재사용(앱 스토리지). 없으면 GLB 와 같은 계정.
    conn = (
        os.getenv("AZURE_APP_STORAGE_CONNECTION_STRING")
        or os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        or ""
    ).strip()
    if not conn:
        return None
    try:
        from azure.storage.blob import BlobServiceClient

        svc = BlobServiceClient.from_connection_string(conn)
        container = svc.get_container_client(CONTAINER)
        try:
            container.create_container()
        except Exception:
            pass  # 이미 있으면 무시.
        _container_singleton = container
        return container
    except Exception as e:  # 잘못된 연결 문자열 등 — 로컬 전용으로 진행.
        logger.warning("Blob 컨테이너 초기화 실패(로컬 전용으로 진행): %s", e)
        return None


def configured() -> bool:
    return _container() is not None


def _image_blob(job_id: str, filename: str) -> str:
    return f"jobs/{job_id}/images/{filename}"


def upload_job_images(job_id: str, images_dir: Path) -> int:
    """images_dir 의 파일들을 jobs/<job_id>/images/<name> 으로 업로드. 올린 개수 반환.
    미설정/오류는 0(best-effort; 텍스트 체인과 무관해 잡을 죽이지 않는다)."""
    container = _container()
    if container is None or not images_dir.is_dir():
        return 0
    from azure.storage.blob import ContentSettings

    n = 0
    for p in sorted(images_dir.iterdir()):
        if not p.is_file():
            continue
        ctype = "image/png" if p.suffix.lower() == ".png" else "application/octet-stream"
        try:
            with p.open("rb") as fh:
                container.upload_blob(
                    _image_blob(job_id, p.name),
                    fh,
                    overwrite=True,
                    content_settings=ContentSettings(content_type=ctype),
                )
            n += 1
        except Exception as e:
            logger.warning("이미지 Blob 업로드 실패 job=%s file=%s: %s", job_id, p.name, e)
    return n


def download_job_image(job_id: str, filename: str) -> bytes | None:
    """jobs/<job_id>/images/<filename> 의 바이트. 없거나 미설정이면 None."""
    container = _container()
    if container is None:
        return None
    try:
        return container.download_blob(_image_blob(job_id, filename)).readall()
    except Exception:
        return None  # 없음(404 처리는 호출부).
