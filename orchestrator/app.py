"""회랑 오케스트레이션 FastAPI 앱 (STUB 슬라이스).

업로드 -> 비동기 STUB 파이프라인 -> 부분 준비 조회. serve.py 와 독립이며 /query
류는 만들지 않는다(다음 task).

/upload 는 raw 본문 + 쿼리 파라미터(filename/domain)로 파일을 받는다. multipart 를
피해 신규 의존성을 0으로 유지한다(python-multipart 미설치 환경).
"""
from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

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
async def upload(request: Request, filename: str = "upload.txt", domain: str = "unknown"):
    """파일(raw 본문)을 받아 잡을 만들고 즉시 job_id 를 반환한다. 무거운 일은
    워커가 백그라운드로 돈다."""
    data = await request.body()
    if not data:
        raise HTTPException(status_code=422, detail="빈 본문. 파일 바이트가 필요하다.")

    job_id = uuid.uuid4().hex
    run_id = job_id  # STUB 단계에선 run_id == job_id.

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
    )
    app.state.worker.enqueue(job_id)
    logger.info("업로드 수신: job_id=%s file=%s domain=%s", job_id, safe_name, domain)
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
    return JSONResponse(content=json.loads(path.read_text(encoding="utf-8")))
