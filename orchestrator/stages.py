"""파이프라인 스테이지: preprocess -> index -> build_palace -> rag.

상태:
  - preprocess: STUB (sleep + done 마커).
  - index: SCAFFOLD. 업로드를 인덱싱하는 대신 도메인을 기존 스냅샷으로 매핑하고
    snapshot_path 를 거기로 갱신. 라이브 인덱싱은 다음 슬라이스(여기만 localized swap;
    PALACE_CONFIGS 는 SHOWCASE_SNAPSHOTS 와 분리돼 있어 scaffold 가정이 안 샌다).
  - build_palace: 진짜. palace/run.py 를 subprocess 로 구동해 per-job config 로 방을
    빌드한다. korean_history 는 frozen_toc -> rooms 만, 그 외는 full(toc+클램프+rooms).
    모든 출력/캐시는 var/jobs/<id>/ 로 격리(잡마다 새 캐시 = cold). results/snapshots 는
    읽기 전용.
  - rag: 진짜. 빌드/매핑된 스냅샷을 serve 에 register.

각 스테이지는 (job, store, sleep_seconds, **future) 시그니처를 공유하므로 워커가
동일하게 호출한다(워커는 kwargs 없이 위치 인자로만 호출). readiness 플래그는 순서
독립이라 스테이지 완료 시점에만 켠다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import sys
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


def _rel(p: Path) -> str:
    """repo-relative posix path string (palace/run.py resolves these vs REPO)."""
    return p.resolve().relative_to(config.REPO).as_posix()


def _seed_palace_cache_if_available(base: dict, cache_dir: Path) -> Optional[str]:
    """Option A: seed the per-job (cold) cache from the domain's committed cache
    so showcase domains reproduce their reference rooms deterministically. The
    committed cache dir is the parent of the base config's cache paths. Stage A
    rubric is path-keyed and Stage B is content-hash-keyed, so a wrong-domain
    seed can only miss (recompute), never cross-hit. New/unknown domains have no
    committed cache -> no seed -> cold build (real LLM). Toggle the whole
    behavior with config.SEED_PALACE_CACHE (A<->C in one place). Returns the
    seeded source path (for logging) or None."""
    if not config.SEED_PALACE_CACHE:
        return None
    src = (config.REPO / base["rubric_cache_path"]).parent
    if not src.is_dir():
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, cache_dir, dirs_exist_ok=True)
    return str(src)


def _build_job_palace_config(job: Job, snapshot_path: str) -> tuple[Path, dict, Optional[str]]:
    """Materialize a per-job palace config from the domain base, overriding all
    outputs/caches into var/jobs/<id>/ and pointing at the job's fresh snapshot.
    corpus/domain/node_budget/n_runs/model/room bounds and frozen_toc
    (korean_history only) are kept from the base, so the domain branch (frozen
    rooms-only vs full toc+rooms) falls out of base.frozen_toc and never relies
    on a stage kwarg. Per-job cache paths keep the base's basenames so the seed
    (option A) lands where palace looks. Returns (config_path, cfg, seeded_src)."""
    base_rel = config.PALACE_CONFIGS.get(job.domain)
    if base_rel is None:
        supported = ", ".join(config.PALACE_CONFIGS) or "-"
        raise ValueError(
            f"미지원 도메인 '{job.domain}'. build_palace 베이스 config 없음. "
            f"지원: {supported}."
        )
    base = json.loads((config.REPO / base_rel).read_text(encoding="utf-8"))
    jd = config.job_dir(job.job_id)
    palace_out = jd / "palace_out"
    cache_dir = jd / "cache"
    cfg = dict(base)
    cfg["run_id"] = job.run_id
    cfg["snapshot"] = snapshot_path           # fresh from store (seam to live index)
    cfg["snapshot_rel"] = snapshot_path
    cfg["rooms_dir"] = _rel(palace_out)
    cfg["toc_out"] = _rel(palace_out / f"{job.run_id}.toc_llm.json")
    # keep base basenames so a seeded committed cache lands at these exact paths.
    cfg["rubric_cache_path"] = _rel(cache_dir / Path(base["rubric_cache_path"]).name)
    cfg["stage_b_cache_dir"] = _rel(cache_dir / Path(base["stage_b_cache_dir"]).name)
    # seed BEFORE the build so Stage A/B hit the committed cache (option A).
    seeded = _seed_palace_cache_if_available(base, cache_dir)
    cfg_path = jd / "palace_config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return cfg_path, cfg, seeded


def _run_palace(config_path: Path, phase: str) -> tuple[int, str]:
    """Run palace/run.py as a subprocess. palace loads LanceDB + calls Azure +
    uses asyncio internally; a subprocess isolates all that from the worker's
    event loop (same seam serve.py uses). Returns (returncode, combined output)."""
    proc = subprocess.run(
        [sys.executable, "-m", "palace.run",
         "--config", str(config_path), "--phase", phase],
        cwd=str(config.REPO),
        capture_output=True, text=True, encoding="utf-8",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


async def build_palace(
    job: Job,
    store: JobStore,
    sleep_seconds: float,
) -> None:
    # gotcha 2: index updated snapshot_path in the store; the worker's job is stale.
    fresh = store.get(job.job_id) or job
    cfg_path, cfg, seeded = _build_job_palace_config(fresh, fresh.snapshot_path)
    logger.info(
        "build_palace job=%s domain=%s cache_seed=%s",
        job.job_id, job.domain, seeded or "none (cold)",
    )
    # gotcha 1: stage kwargs are not passed by the worker; derive the build mode
    # from the base config. korean_history has frozen_toc -> rooms only; others
    # run the full live path (toc + clamp -> rooms).
    phases = ["rooms"] if cfg.get("frozen_toc") else ["toc", "rooms"]
    loop = asyncio.get_running_loop()
    for phase in phases:
        rc, out = await loop.run_in_executor(None, _run_palace, cfg_path, phase)
        if rc != 0:
            raise RuntimeError(
                f"palace {phase} 실패 (rc={rc}) job={job.job_id}:\n{out[-1500:]}"
            )
    palace_path = config.job_dir(job.job_id) / "palace_out" / f"{job.run_id}.palace.json"
    if not palace_path.exists():
        raise RuntimeError(f"build_palace 완료했으나 산출물 없음: {palace_path}")
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
