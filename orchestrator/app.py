"""회랑 오케스트레이션 FastAPI 앱 (STUB 슬라이스).

업로드 -> 비동기 STUB 파이프라인 -> 부분 준비 조회. serve.py 와 독립이며 /query
류는 만들지 않는다(다음 task).

/upload 는 raw 본문 + 쿼리 파라미터(filename/domain)로 파일을 받는다. multipart 를
피해 신규 의존성을 0으로 유지한다(python-multipart 미설치 환경).
"""
from __future__ import annotations

import json
import logging
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from orchestrator import config
from orchestrator.jobs import JobStore, State
from orchestrator.worker import Worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("orchestrator.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    store = JobStore(config.DB_PATH)
    store.init_db()
    worker = Worker(store, sleep_seconds=config.STUB_STAGE_SECONDS)
    worker.start()
    worker.recover()  # 루프가 뜬 뒤 비종단 잡 복구(재큐/FAILED).
    app.state.store = store
    app.state.worker = worker
    logger.info("오케스트레이터 준비됨. db=%s", config.DB_PATH)
    yield
    worker.stop()


app = FastAPI(title="회랑 오케스트레이션 (STUB)", lifespan=lifespan)


@app.get("/health")
async def health():
    worker: Worker = app.state.worker
    alive = worker.thread is not None and worker.thread.is_alive()
    return {"status": "ok" if alive else "error", "worker_alive": alive}


@app.post("/upload", status_code=201)
async def upload(
    request: Request,
    filename: str = "upload.txt",
    domain: str = "unknown",
    showcase: str | None = None,
):
    """파일(raw 본문)을 받아 잡을 만들고 즉시 job_id 를 반환한다. 무거운 일은
    워커가 백그라운드로 돈다.

    트리거 분리:
      - showcase=<key> (명시): 그 키로 프리베이크 스냅샷을 고른다(scaffold 데모).
        키가 알려진 쇼케이스가 아니면 422. domain 라벨과 무관하게 동작한다.
      - showcase 없음 (일반 업로드): 무조건 라이브 인덱싱. domain 은 라벨일 뿐
        스냅샷 선택에 관여하지 않는다(감지/선언된 domain 으로 프리베이크가 새지 않음).
    """
    if showcase is not None and showcase not in config.SHOWCASE_SNAPSHOTS:
        supported = ", ".join(config.SHOWCASE_SNAPSHOTS) or "-"
        raise HTTPException(
            status_code=422,
            detail=f"미지원 showcase '{showcase}'. 지원: {supported}.",
        )

    # 공개 업로드 크기 상한. Content-Length 로 본문을 메모리에 읽기 전에 먼저 거절하고
    # (거대 파일이 RAM 을 치기 전에 차단), 헤더가 없거나 거짓이면 실제 길이로 폴백 검증.
    limit = config.MAX_UPLOAD_BYTES
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > limit:
                raise HTTPException(
                    status_code=413,
                    detail=f"파일이 너무 큼: 상한 {config.MAX_UPLOAD_MB}MB",
                )
        except ValueError:
            pass  # 헤더가 정수가 아니면 무시하고 아래 실제 길이 검증에 맡긴다.

    data = await request.body()
    if not data:
        raise HTTPException(status_code=422, detail="빈 본문. 파일 바이트가 필요하다.")
    if len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"파일이 너무 큼: {len(data) // (1024 * 1024)}MB (상한 {config.MAX_UPLOAD_MB}MB)",
        )

    job_id = uuid.uuid4().hex
    run_id = job_id  # run_id == job_id.

    jd = config.job_dir(job_id)
    input_dir = jd / "input"
    snapshot_dir = jd / "snapshot"
    input_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # 경로 탈출 방지: 파일명만 취한다.
    safe_name = Path(filename).name or "upload.txt"
    input_path = input_dir / safe_name
    input_path.write_bytes(data)

    store: JobStore = app.state.store
    store.create(
        job_id=job_id,
        domain=domain,
        run_id=run_id,
        input_path=str(input_path),
        snapshot_path=str(snapshot_dir),
        showcase_key=showcase,
    )
    app.state.worker.enqueue(job_id)
    logger.info(
        "업로드 수신: job_id=%s file=%s domain=%s showcase=%s",
        job_id, safe_name, domain, showcase or "-",
    )
    return {"job_id": job_id, "state": State.QUEUED}


@app.get("/jobs/{job_id}/status")
async def job_status(job_id: str):
    store: JobStore = app.state.store
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job_id '{job_id}' 없음")
    return job.to_status()


@app.get("/jobs/{job_id}/palace")
async def job_palace(job_id: str):
    """palace_ready 면 placeholder palace.json 을 반환. 아직이면 409, 잡 없으면 404."""
    store: JobStore = app.state.store
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job_id '{job_id}' 없음")
    if not job.palace_ready or not job.palace_path:
        raise HTTPException(
            status_code=409,
            detail=f"palace 아직 준비 안 됨 (state={job.state}, palace_ready={job.palace_ready})",
        )
    path = Path(job.palace_path)
    if not path.exists():
        raise HTTPException(status_code=500, detail="palace_ready 인데 산출물 파일이 없다")
    # 라이브 PDF 잡이면 이미지 매칭이 palace_out/palace_with_images.json 을 남긴다(노드에
    # images[] 부착). 있으면 그걸 우선 반환해 프론트가 노드 이미지를 받게 하고, 없으면
    # (.txt 업로드/매칭 스킵/실패) 기존 텍스트 palace 로 폴백한다. /jobs/{id}/images 로
    # 서빙되는 PNG 와 짝(node.images[].path = 'images/<file>').
    with_images = path.parent / "palace_with_images.json"
    serve_path = with_images if with_images.exists() else path
    return JSONResponse(content=json.loads(serve_path.read_text(encoding="utf-8")))


@app.get("/jobs/{job_id}/toc")
async def job_toc(job_id: str):
    """toc_ready 면 인덱싱과 분리돼 먼저 생성된 LLM 목차(toc_llm.json)를 반환한다.
    프론트가 방 생성(palace) 전에 둘러보기 페이지에서 목차를 보여줄 수 있게 하는 조기
    엔드포인트. 아직이면 409, 잡 없으면 404."""
    store: JobStore = app.state.store
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job_id '{job_id}' 없음")
    if not job.toc_ready:
        raise HTTPException(
            status_code=409,
            detail=f"toc 아직 준비 안 됨 (state={job.state}, toc_ready={job.toc_ready})",
        )
    toc_path = config.job_dir(job_id) / "palace_out" / f"{job.run_id}.toc_llm.json"
    if not toc_path.exists():
        raise HTTPException(status_code=500, detail="toc_ready 인데 산출물 파일이 없다")
    return JSONResponse(content=json.loads(toc_path.read_text(encoding="utf-8")))


@app.get("/jobs/{job_id}/images/{filename}")
async def job_image(job_id: str, filename: str):
    """라이브 잡이 매칭한 PNG 를 서빙한다: palace_out/images/<filename>. 프론트는 노드의
    images[].path('images/fig_X.png')를 이 경로로 풀어 <img> 렌더. 쇼케이스의
    /images/{name}/{file} 와 평행한 라이브 잡 전용 경로. 경로 traversal 은 resolve 후
    images_dir 하위인지 검증해 차단한다(절대/.. 차단)."""
    store: JobStore = app.state.store
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job_id '{job_id}' 없음")
    images_dir = (config.job_dir(job_id) / "palace_out" / "images").resolve()
    target = (images_dir / filename).resolve()
    if images_dir not in target.parents:
        raise HTTPException(status_code=400, detail="잘못된 이미지 경로")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"이미지 '{filename}' 없음")
    return FileResponse(target)


@app.delete("/jobs/{job_id}")
async def job_delete(job_id: str):
    """업로드 잡의 산출물(`var/jobs/<id>` 전체)과 DB 기록을 지운다. 업로드 데이터 삭제
    (개인정보) + 공개 데모 디스크 정리용. 워커가 폴더를 쓰는 진행 중 잡은 못 지우고,
    종료된 잡(DONE/FAILED)만 허용한다. 잡 없으면 404, 진행 중이면 409.
    참고: serve 에 등록된 라이브 스냅샷의 RAM 적재는 별개(스냅샷 eviction 은 추후)."""
    store: JobStore = app.state.store
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job_id '{job_id}' 없음")
    if job.state not in State.TERMINAL:
        raise HTTPException(
            status_code=409,
            detail=f"진행 중 잡은 삭제 불가 (state={job.state}); DONE/FAILED 만 삭제 가능",
        )
    jd = config.job_dir(job_id)
    removed_dir = jd.exists()
    if removed_dir:
        shutil.rmtree(jd, ignore_errors=True)
    store.delete(job_id)
    logger.info("deleted job %s (removed_dir=%s)", job_id, removed_dir)
    return {"deleted": job_id, "removed_dir": removed_dir}
