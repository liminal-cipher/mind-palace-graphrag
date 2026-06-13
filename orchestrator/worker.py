"""백그라운드 워커: 전용 스레드 + 자체 asyncio 루프.

serve.py 의 max_workers=1 전용 스레드 패턴과 동형이다. 나중에 진짜 build_index 가
들어오면 그쪽의 LanceDB 스레드 친화성 + asyncio.run 제약을 바로 이 자리(루프 없는
요청 스레드와 분리된 전용 루프)에 끼운다.

잡은 단일 asyncio.Queue 로 직렬 처리한다(한 번에 한 잡). 다른 스레드(요청 핸들러,
복구)는 call_soon_threadsafe 로 인큐한다. 스테이지 전이마다 SQLite 에 즉시 커밋된다
(JobStore 가 커밋하므로 여기선 호출만).
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

from orchestrator.jobs import JobStore, State
from orchestrator.stages import PIPELINE

logger = logging.getLogger("orchestrator.worker")

# 인큐 종료를 알리는 센티넬.
_STOP = None


class Worker:
    def __init__(self, store: JobStore, sleep_seconds: float) -> None:
        self.store = store
        self.sleep_seconds = sleep_seconds
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.queue: Optional[asyncio.Queue] = None
        self.thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

    # --- 수명 주기 ---------------------------------------------------------
    def start(self) -> None:
        self.thread = threading.Thread(
            target=self._run, name="orch-worker", daemon=True
        )
        self.thread.start()
        if not self._ready.wait(timeout=10):
            raise RuntimeError("worker 루프가 제때 뜨지 않았다")
        logger.info("worker 스레드 시작됨 (sleep=%.1fs/stage)", self.sleep_seconds)

    def _run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.queue = asyncio.Queue()
        self.loop.create_task(self._consume())
        self._ready.set()
        self.loop.run_forever()

    def stop(self) -> None:
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(self.queue.put_nowait, _STOP)
        self.loop.call_soon_threadsafe(self.loop.stop)

    # --- 인큐 / 복구 -------------------------------------------------------
    def enqueue(self, job_id: str) -> None:
        """다른 스레드에서 안전하게 잡을 큐에 넣는다."""
        assert self.loop is not None and self.queue is not None
        self.loop.call_soon_threadsafe(self.queue.put_nowait, job_id)

    def recover(self) -> None:
        """시작 시 비종단 잡 복구. QUEUED 는 재큐(아직 시작 전), 진행 중이던
        잡은 STUB 스테이지가 재개 불가하므로 FAILED 로 마킹한다."""
        recovered = self.store.list_non_terminal()
        for job in recovered:
            if job.state == State.QUEUED:
                logger.info("복구: %s 재큐 (QUEUED)", job.job_id)
                self.enqueue(job.job_id)
            else:
                logger.info("복구: %s FAILED (state=%s 에서 중단)", job.job_id, job.state)
                self.store.fail(
                    job.job_id,
                    f"interrupted by server restart at state={job.state} "
                    "(STUB stages are not resumable)",
                )
        if recovered:
            logger.info("복구 처리한 비종단 잡: %d개", len(recovered))

    # --- 처리 --------------------------------------------------------------
    async def _consume(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                if job_id is _STOP:
                    break
                await self._process(job_id)
            except Exception as e:  # noqa: BLE001  한 잡 실패가 워커를 죽이지 않게.
                logger.exception("잡 %s 처리 실패", job_id)
                self.store.fail(job_id, f"{type(e).__name__}: {e}")
            finally:
                self.queue.task_done()

    async def _process(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None:
            logger.warning("잡 %s 가 사라짐, 건너뜀", job_id)
            return
        logger.info("잡 %s 시작 (domain=%s)", job_id, job.domain)
        for stage in PIPELINE:
            await stage(job, self.store, self.sleep_seconds)
        self.store.update(job_id, state=State.DONE)
        logger.info("잡 %s DONE", job_id)
