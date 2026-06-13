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
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from orchestrator import config
from orchestrator.jobs import Job, JobStore, State

logger = logging.getLogger("orchestrator.stages")


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
    # SCAFFOLD: 진짜 GraphRAG 인덱싱(graphrag.api.build_index) 대신, 알려진 showcase
    # 도메인을 기존(reports 포함) 스냅샷 dir로 매핑해 snapshot_path를 거기로 가리킨다.
    # rag가 등록할 "진짜 스냅샷"이 생긴다. 다음 슬라이스에서 진짜 인덱싱으로 교체.
    snapshot_dir = config.SHOWCASE_SNAPSHOTS.get(job.domain)
    if snapshot_dir is None:
        supported = ", ".join(config.SHOWCASE_SNAPSHOTS) or "-"
        raise ValueError(
            f"미지원 도메인 '{job.domain}'. SCAFFOLD index 단계는 알려진 showcase "
            f"입력만 처리한다(진짜 인덱싱은 다음 슬라이스). 지원 도메인: {supported}."
        )
    # 결정 기록은 잡 폴더(var, 쓰기 가능)에만. 가리키는 스냅샷 dir(results/snapshots)은
    # 읽기 전용으로만 쓰므로 절대 건드리지 않는다.
    _touch(
        Path(job.snapshot_path).parent / "_index_scaffold.json",
        json.dumps(
            {
                "scaffold": True,
                "domain": job.domain,
                "snapshot_dir": snapshot_dir,
                "note": "points at prebuilt snapshot; real indexing is next slice",
            },
            ensure_ascii=False,
        ),
    )
    # snapshot_path를 기존 스냅샷 dir로 갱신(repo 상대; serve가 허용 루트 검증 후 로드).
    store.update(job.job_id, snapshot_path=snapshot_dir)


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


def _register_with_serve(key: str, snapshot_path: str) -> dict:
    """serve의 내부 register 엔드포인트에 빌드된 스냅샷을 등록한다(두 프로세스 seam).
    stdlib urllib만 쓴다(신규 의존성 0). serve가 path를 허용 루트 검증 후 자기
    _executor 스레드에서 warm하므로 LanceDB 친화성은 serve 쪽에서 보장된다."""
    url = config.SERVE_URL.rstrip("/") + "/snapshots/register"
    payload = json.dumps({"key": key, "path": snapshot_path}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"serve register HTTP {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"serve register 연결 실패 ({url}): {e.reason}")


async def rag(
    job: Job,
    store: JobStore,
    sleep_seconds: float,
) -> None:
    await asyncio.sleep(sleep_seconds)
    # index가 갱신한 snapshot_path를 DB에서 다시 읽는다(워커가 넘긴 job 객체는 stale).
    fresh = store.get(job.job_id)
    snapshot_path = fresh.snapshot_path if fresh else job.snapshot_path
    # 라이브 등록 키 = job_id. serve가 그 스냅샷을 warm하면 /jobs/{job_id}/query로 답한다.
    info = _register_with_serve(job.job_id, snapshot_path)
    store.update(job.job_id, state=State.RAG_READY, rag_ready=True)
    # 등록 결과(합성 모델/warm 시간)는 로그로만. 잡 상태는 rag_ready로 표현된다.
    logger.info(
        "rag 등록 완료: job=%s -> serve key=%s dir=%s synth=%s",
        job.job_id, job.job_id, snapshot_path, info.get("synthesis_model"),
    )


# 워커가 순서대로 도는 STUB 파이프라인. 각 항목은 (job, store, sleep) 로 호출된다.
PIPELINE = (preprocess, index, build_palace, rag)
