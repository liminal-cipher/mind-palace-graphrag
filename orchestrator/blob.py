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


# ── 인덱싱 스냅샷(parquet + lancedb 디렉터리) 영속 (Phase 3 저장 프리미티브) ──────
# 라이브 잡의 스냅샷(var/jobs/<id>/index_root/output)은 로컬 디스크라 재시작에 휘발한다.
# 디렉터리 전체(중첩 lancedb 포함)를 jobs/<id>/snapshot/<상대경로> 로 보존한다. 아직 빌드
# 파이프라인엔 물리지 않았다(dormant): 업로드 호출 + 재시작 시 다운로드→serve 재등록(lazy)
# 연동은 후속 작업(실서버 검증 필요). 여기선 검증된 디렉터리 라운드트립 저장만 제공한다.

def _snapshot_prefix(job_id: str) -> str:
    return f"jobs/{job_id}/snapshot"


def upload_snapshot(job_id: str, snapshot_dir: Path) -> int:
    """snapshot_dir 전체(하위 디렉터리·lancedb 포함)를 재귀로 Blob 에 업로드한다.
    jobs/<job_id>/snapshot/<상대경로(posix)> 로 올린다. 올린 파일 수 반환. 미설정/오류는 0."""
    container = _container()
    if container is None or not snapshot_dir.is_dir():
        return 0
    n = 0
    for p in sorted(snapshot_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(snapshot_dir).as_posix()  # Blob 키는 posix 경로로 통일.
        try:
            with p.open("rb") as fh:
                container.upload_blob(f"{_snapshot_prefix(job_id)}/{rel}", fh, overwrite=True)
            n += 1
        except Exception as e:
            logger.warning("스냅샷 Blob 업로드 실패 job=%s file=%s: %s", job_id, rel, e)
    return n


def download_snapshot(job_id: str, dest_dir: Path) -> int:
    """jobs/<job_id>/snapshot/* 를 dest_dir 아래로 내려받아 디렉터리 구조를 복원한다
    (lancedb 등 하위 디렉터리 포함). 내려받은 파일 수 반환(0 이면 없음/미설정)."""
    container = _container()
    if container is None:
        return 0
    prefix = _snapshot_prefix(job_id) + "/"
    try:
        blobs = list(container.list_blobs(name_starts_with=prefix))
    except Exception:
        return 0
    n = 0
    for b in blobs:
        rel = b.name[len(prefix):]
        if not rel:
            continue
        target = dest_dir / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(container.download_blob(b.name).readall())
            n += 1
        except Exception as e:
            logger.warning("스냅샷 Blob 다운로드 실패 job=%s blob=%s: %s", job_id, b.name, e)
    return n


def snapshot_exists(job_id: str) -> bool:
    """Blob 에 이 잡의 스냅샷이 보존돼 있는지(파일 1개 이상)."""
    container = _container()
    if container is None:
        return False
    try:
        for _ in container.list_blobs(name_starts_with=_snapshot_prefix(job_id) + "/"):
            return True
    except Exception:
        return False
    return False


def delete_job(job_id: str) -> int:
    """이 잡의 모든 Blob(images + snapshot)을 지운다. 지운 개수 반환(0=없음/미설정).
    DELETE /jobs/{id} 시 호출해 Blob 의 무한 누적을 막는다(big-service 의 정리 정책)."""
    container = _container()
    if container is None:
        return 0
    try:
        names = [b.name for b in container.list_blobs(name_starts_with=f"jobs/{job_id}/")]
    except Exception:
        return 0
    n = 0
    for name in names:
        try:
            container.delete_blob(name)
            n += 1
        except Exception:
            pass  # 이미 없음 등.
    return n
