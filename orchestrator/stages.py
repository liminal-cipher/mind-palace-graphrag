"""STUB 파이프라인 스테이지: preprocess -> index -> build_palace -> rag.

지금은 전부 더미다: 상태 갱신 -> asyncio.sleep -> 잡 폴더에 placeholder 산출물
touch -> (해당하면) readiness 플래그 set. 실패는 예외로 던지고 워커가 FAILED 로 잡는다.

시그니처는 미래 확장 자리를 미리 열어 둔다(지금은 무시):
  - preprocess: substeps 로 전처리 2단계 분리.
  - index: domain/entity_types 를 받아 도메인별 추출.
  - build_palace: frozen_toc 로 frozen/라이브 분기(palace/run.py 와 동형).
실제 graphrag.api.build_index / palace 빌드 구동은 다음 task.

각 스테이지는 (job, store, sleep_seconds, **future) 시그니처를 공유하므로 워커가
동일하게 호출한다. readiness 플래그는 순서 독립이라 스테이지 완료 시점에만 켠다.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from orchestrator.jobs import Job, JobStore, State


def _touch(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


async def preprocess(
    job: Job,
    store: JobStore,
    sleep_seconds: float,
    *,
    substeps: Optional[list[str]] = None,  # 미래: 전처리 2단계 분리
) -> None:
    store.update(job.job_id, state=State.PREPROCESSING)
    await asyncio.sleep(sleep_seconds)
    _touch(Path(job.input_path).parent / "_preprocess.done", "stub preprocess\n")


async def index(
    job: Job,
    store: JobStore,
    sleep_seconds: float,
    *,
    domain: Optional[str] = None,        # 미래: 도메인별 추출
    entity_types: Optional[list[str]] = None,
) -> None:
    store.update(job.job_id, state=State.INDEXING)
    await asyncio.sleep(sleep_seconds)
    # 진짜 인덱싱은 snapshot/ 에 parquet + lancedb 를 쓴다. STUB 은 마커만.
    _touch(
        Path(job.snapshot_path) / "_stub_snapshot.json",
        json.dumps({"stub": True, "run_id": job.run_id}, ensure_ascii=False),
    )


async def build_palace(
    job: Job,
    store: JobStore,
    sleep_seconds: float,
    *,
    frozen_toc: Optional[str] = None,    # 미래: frozen/라이브 TOC 분기
) -> None:
    await asyncio.sleep(sleep_seconds)
    palace_path = Path(job.snapshot_path).parent / "palace" / f"{job.run_id}.palace.json"
    placeholder = {
        "palace": {
            "stub": True,
            "job_id": job.job_id,
            "run_id": job.run_id,
            "domain": job.domain,
            "note": "placeholder produced by STUB build_palace stage",
            "room_count": 0,
        },
        "rooms": [],
    }
    _touch(palace_path, json.dumps(placeholder, ensure_ascii=False, indent=2))
    # palace.json 이 났으므로 3D 핸드오프 가능 -> palace_ready.
    store.update(
        job.job_id,
        state=State.PALACE_READY,
        palace_ready=True,
        palace_path=str(palace_path),
    )


async def rag(
    job: Job,
    store: JobStore,
    sleep_seconds: float,
) -> None:
    await asyncio.sleep(sleep_seconds)
    # 진짜는 community reports + 서빙 엔진 warm. STUB 은 마커만.
    _touch(Path(job.snapshot_path) / "_rag_ready.marker", "stub rag warm\n")
    store.update(job.job_id, state=State.RAG_READY, rag_ready=True)


# 워커가 순서대로 도는 STUB 파이프라인. 각 항목은 (job, store, sleep) 로 호출된다.
PIPELINE = (preprocess, index, build_palace, rag)
