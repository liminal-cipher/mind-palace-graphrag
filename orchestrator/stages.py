"""파이프라인 스테이지: preprocess -> index -> build_palace -> rag.

상태:
  - preprocess: STUB (sleep + done 마커).
  - index: 분기. job.showcase_key 가 있으면 SCAFFOLD(기존 스냅샷 매핑), 없으면
    라이브 인덱싱(_index_live, 후속 커밋). domain 라벨은 스냅샷 선택에 안 쓴다.
    PALACE_CONFIGS 는 SHOWCASE_SNAPSHOTS 와 분리돼 있어 scaffold 가정이 안 샌다.
  - build_palace: 진짜. palace/run.py 를 subprocess 로 구동해 per-job config 로 방을
    빌드한다. korean_history 는 frozen_toc -> rooms 만, 그 외는 full(toc+클램프+rooms).
    모든 출력/캐시는 var/jobs/<id>/ 로 격리(잡마다 새 캐시 = cold). snapshots 는
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

from orchestrator import blob, config, domain_detect, entity_types, index_root
from orchestrator.jobs import Job, JobStore, State

logger = logging.getLogger("orchestrator.stages")


def _touch(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _is_pdf(path: Path) -> bool:
    """입력이 PDF 인지 매직바이트(%PDF)로 판별. 파일명 확장자는 임의일 수 있으므로
    내용으로 본다. PDF 만 전처리(텍스트 추출)를 타고, .txt(이미 추출된 텍스트)는
    그대로 통과한다."""
    try:
        with open(path, "rb") as f:
            return f.read(5).startswith(b"%PDF-")
    except OSError:
        return False


def _run_preprocess(pdf_path: Path, out_dir: Path) -> tuple[int, str]:
    """preprocessing/pipeline_v2.py 를 subprocess 로 돈다(_run_index 와 동형 seam).
    무거운 torch import + step5 스레드풀을 워커 프로세스에서 격리한다. env(.env 로드분)를
    상속해 OPEN_AI_*/CONTENT_UNDERSTANDING_* 가 steps 에서 풀린다. preprocessing 은
    패키지가 아니므로 -m 대신 스크립트 경로로 실행한다(-X utf8: 한글 출력 안전)."""
    config.load_env()
    script = config.REPO / "preprocessing" / "pipeline_v2.py"
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(script),
         "--pdf", str(pdf_path), "--out-dir", str(out_dir)],
        cwd=str(config.REPO),
        capture_output=True, text=True, encoding="utf-8",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


async def preprocess(
    job: Job,
    store: JobStore,
    sleep_seconds: float,
    *,
    substeps: Optional[list[str]] = None,  # 미래: 전처리 2단계 분리
) -> None:
    """업로드를 인덱싱 가능한 .txt 로 만든다. 쇼케이스(프리베이크) 잡과 이미 텍스트인
    업로드는 추출이 필요 없어 통과하고, 생 PDF 만 pipeline_v2 로 실제 전처리한다.
    추출 성공 시 store 의 input_path 를 추출 본문(content.txt)으로 갱신해, index 가
    fresh 로 그 텍스트를 받게 한다(snapshot_path 와 같은 store seam)."""
    store.update(job.job_id, state=State.PREPROCESSING)

    # 쇼케이스: index 가 프리베이크 스냅샷으로 scaffold 하므로 입력 전처리 불필요(스텁 유지).
    if job.showcase_key:
        await asyncio.sleep(sleep_seconds)
        _touch(Path(job.input_path).parent / "_preprocess.done", "showcase: skip preprocess\n")
        return

    src = Path(job.input_path)
    if not _is_pdf(src):
        # 이미 텍스트(.txt) 업로드: 추출 불필요, 그대로 통과(현행 라이브 .txt 경로 무변경).
        _touch(src.parent / "_preprocess.done", "passthrough (non-pdf input)\n")
        return

    # PDF: 작업 격리 디렉터리에서 pipeline_v2 로 본문/이미지/캡션 추출(인덱스 시점 1회).
    out_dir = config.job_dir(job.job_id) / "preprocess"
    loop = asyncio.get_running_loop()
    rc, out = await loop.run_in_executor(None, _run_preprocess, src, out_dir)
    if rc != 0:
        raise RuntimeError(
            f"전처리(pipeline_v2) 실패 (rc={rc}) job={job.job_id}:\n{out[-1500:]}"
        )

    content = out_dir / "txt" / "content.txt"
    if not content.is_file() or content.stat().st_size == 0:
        raise RuntimeError(
            f"전처리 완료했으나 본문 추출 없음 job={job.job_id}: {content} "
            "(빈/깨진 PDF 또는 추출 실패 추정)."
        )
    # index 가 읽을 입력을 추출 본문으로 교체(store seam; 워커가 넘긴 job 은 stale).
    store.update(job.job_id, input_path=str(content))
    logger.info(
        "preprocess 완료 job=%s pdf=%s -> %s (%d자)",
        job.job_id, src.name, content, content.stat().st_size,
    )


def _detect_domain_label(text: str, declared: str) -> str:
    """corpus 본문으로 도메인 라벨 1개를 해소한다. 감지 실패 시 선언 라벨(빈값/unknown
    제외)로 폴백. toc 단계에서 1회 수행해 store 에 저장하고 index 는 그 값을 재사용한다."""
    label = domain_detect.detect_domain(text)
    return label or ("" if declared in ("", "unknown") else declared)


async def toc(
    job: Job,
    store: JobStore,
    sleep_seconds: float,
) -> None:
    """인덱싱과 분리된 조기 목차 단계. phase_toc 는 corpus 만 읽고 snapshot(인덱스)은
    안 쓰므로 index 앞에서 돌릴 수 있다 -> 프론트가 방 생성 전에 목차를 본다(toc_ready).
    도메인 감지도 여기서 1회 수행해 store 에 저장한다(index/build_palace 가 그 값을
    재사용 -> 중복 LLM 콜 제거). best-effort: 목차 생성이 실패해도 잡을 죽이지 않고
    build_palace 가 toc+rooms 로 폴백한다(단, 도메인은 이미 저장됨)."""
    await asyncio.sleep(sleep_seconds)
    fresh = store.get(job.job_id) or job
    # 쇼케이스(프리베이크 팰리스)는 toc 생성 불필요.
    if fresh.showcase_key:
        return
    loop = asyncio.get_running_loop()
    # 도메인 감지(단일 소스). corpus 는 preprocess 가 갱신한 추출 본문(content.txt).
    corpus = Path(fresh.input_path)
    if corpus.is_file():
        text = corpus.read_text(encoding="utf-8", errors="replace")
        effective = await loop.run_in_executor(
            None, _detect_domain_label, text, fresh.domain
        )
        if effective:
            store.update(job.job_id, domain=effective)
            fresh = store.get(job.job_id) or fresh
    cfg_path, cfg, _ = _build_job_palace_config(fresh, fresh.snapshot_path)
    # frozen_toc(커밋 목차) 도메인은 생성 안 함 -> build_palace 가 동결 목차로 rooms.
    if cfg.get("frozen_toc"):
        return
    rc, out = await loop.run_in_executor(None, _run_palace, cfg_path, "toc")
    if rc != 0:
        logger.warning(
            "조기 toc 실패(best-effort, build_palace 가 재생성) job=%s rc=%d:\n%s",
            job.job_id, rc, out[-800:],
        )
        return
    store.update(job.job_id, state=State.TOC_READY, toc_ready=True)
    logger.info("toc 완료(조기) job=%s domain=%s", job.job_id, fresh.domain)


async def index(
    job: Job,
    store: JobStore,
    sleep_seconds: float,
) -> None:
    """showcase 트리거가 명시된 잡은 프리베이크 스냅샷으로 매핑(scaffold), 그 외
    일반 업로드는 진짜 라이브 인덱싱한다. 분기 기준은 job.showcase_key 하나뿐이고
    job.domain(라벨)은 스냅샷 선택에 절대 쓰지 않는다(프리베이크 누수 차단)."""
    store.update(job.job_id, state=State.INDEXING)
    if job.showcase_key:
        await _index_scaffold(job, store, sleep_seconds)
    else:
        await _index_live(job, store)


async def _index_scaffold(job: Job, store: JobStore, sleep_seconds: float) -> None:
    """SCAFFOLD: 진짜 인덱싱 대신 명시된 showcase 키를 기존(reports 포함) 스냅샷 dir로
    매핑해 snapshot_path 를 거기로 가리킨다. 쇼케이스 데모 폴백 경로."""
    await asyncio.sleep(sleep_seconds)
    snapshot_dir = config.SHOWCASE_SNAPSHOTS.get(job.showcase_key)
    if snapshot_dir is None:
        supported = ", ".join(config.SHOWCASE_SNAPSHOTS) or "-"
        raise ValueError(
            f"미지원 showcase '{job.showcase_key}'. 지원: {supported}."
        )
    # 결정 기록은 잡 폴더(var, 쓰기 가능)에만. 가리키는 스냅샷 dir(snapshots)은
    # 읽기 전용으로만 쓰므로 절대 건드리지 않는다.
    _touch(
        Path(job.snapshot_path).parent / "_index_scaffold.json",
        json.dumps(
            {
                "scaffold": True,
                "showcase_key": job.showcase_key,
                "domain": job.domain,
                "snapshot_dir": snapshot_dir,
                "note": "explicit showcase trigger -> prebuilt snapshot",
            },
            ensure_ascii=False,
        ),
    )
    # snapshot_path를 기존 스냅샷 dir로 갱신(repo 상대; serve가 허용 루트 검증 후 로드).
    store.update(job.job_id, snapshot_path=snapshot_dir)


def _run_index(root: Path) -> tuple[int, str]:
    """graphrag index 를 subprocess 로 돈다(_run_palace 와 동형 seam). LanceDB +
    Azure + 내부 asyncio 를 워커 이벤트 루프에서 격리한다. env(.env 로드분)를 상속해
    GRAPHRAG_API_KEY/BASE 가 settings 의 ${...} 로 풀린다."""
    config.load_env()
    proc = subprocess.run(
        [sys.executable, "-m", "graphrag", "index", "--root", str(root)],
        cwd=str(config.REPO),
        capture_output=True, text=True, encoding="utf-8",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _entity_count(snapshot_dir: Path) -> int:
    """인덱싱 산출 엔티티 수(다운스트림 K 붕괴 조기 감지용). 못 읽으면 -1."""
    try:
        import pandas as pd

        return len(pd.read_parquet(snapshot_dir / "entities.parquet"))
    except Exception:  # noqa: BLE001
        return -1


async def _index_live(job: Job, store: JobStore) -> None:
    """진짜 GraphRAG 인덱싱: 도메인 감지 -> entity_types 해소(discover/폴백) ->
    격리 root 에서 graphrag index subprocess -> 산출(parquet 7종 + lancedb)을 잡
    스냅샷으로 등록. snapshot_path seam 으로 build_palace 가 fresh 로 받아 흐른다."""
    # preprocess 가 input_path 를 추출 본문(content.txt)으로 갱신했을 수 있다. 워커가
    # 넘긴 job 은 stale 하므로 store 에서 fresh 로 다시 읽는다(build_palace 와 동일 seam).
    job = store.get(job.job_id) or job
    corpus = Path(job.input_path)
    if not corpus.is_file():
        raise RuntimeError(f"업로드 입력 없음: {corpus}")
    loop = asyncio.get_running_loop()

    # 1) 도메인은 toc 단계가 이미 감지·저장했다(단일 소스) -> 그 값을 재사용해 중복
    #    LLM 콜을 피한다. toc 가 스킵/실패해 미해소(빈값/unknown)면 여기서 폴백 감지.
    effective = job.domain if job.domain not in ("", "unknown") else ""
    if not effective:
        text = corpus.read_text(encoding="utf-8", errors="replace")
        effective = await loop.run_in_executor(None, domain_detect.detect_domain, text) or ""
        if effective:
            store.update(job.job_id, domain=effective)

    # 2) 격리 root materialize(초기 generic, resolve 가 확정 치환).
    root = index_root.build_index_root(
        job, corpus, entity_types.GENERIC_ENTITY_TYPES,
    )
    # 3) entity_types 해소(curated -> discover ON -> generic 폴백). prompt-tune
    #    subprocess 를 돌리므로 executor 로. root 의 settings/프롬프트가 여기서 확정된다.
    res = await loop.run_in_executor(
        None, entity_types.resolve_entity_types, root, effective,
    )
    logger.info(
        "index_live job=%s domain=%s entity_types=%s (%d종)",
        job.job_id, effective or "-", res.source, len(res.entity_types),
    )

    # 4) graphrag index subprocess.
    rc, out = await loop.run_in_executor(None, _run_index, root)
    if rc != 0:
        raise RuntimeError(
            f"graphrag index 실패 (rc={rc}) job={job.job_id}:\n{out[-1500:]}"
        )

    # 5) 산출 검증 + 스냅샷 등록. 출력 dir 가 곧 스냅샷(var/jobs 아래 = serve 허용 루트).
    snapshot = index_root.index_output_dir(job)
    required = ("entities.parquet", "text_units.parquet", "documents.parquet")
    missing = [n for n in required if not (snapshot / n).exists()]
    if missing or not (snapshot / "lancedb").exists():
        raise RuntimeError(
            f"인덱싱 완료했으나 스냅샷 산출 누락 job={job.job_id}: "
            f"{missing or 'lancedb'} ({snapshot})"
        )
    n_ent = _entity_count(snapshot)
    if n_ent == 0:
        raise RuntimeError(
            f"인덱싱 산출 엔티티 0 job={job.job_id}: 빈/깨진 입력 추정({snapshot})."
        )
    logger.info("index_live 완료 job=%s entities=%s snapshot=%s", job.job_id, n_ent, snapshot)
    store.update(job.job_id, snapshot_path=str(snapshot))


def _rel(p: Path) -> str:
    """palace/run.py 의 _abs(REPO, p) 가 해소할 경로 문자열. REPO 하위면 repo-상대로
    (기존 동작), 아니면 절대경로로 돌려준다. 잡 산출물은 config.VAR_DIR 아래인데 배포에선
    ORCH_VAR_DIR=/home/var 로 REPO(/tmp/<hash>) 밖이라 relative_to 가 터진다. _abs 는
    절대경로를 그대로 통과시키므로(p.is_absolute() -> p) 절대경로 폴백이 안전하다."""
    rp = p.resolve()
    try:
        return rp.relative_to(config.REPO).as_posix()
    except ValueError:
        return rp.as_posix()


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


def _default_palace_base(job: Job) -> dict:
    """라이브 잡(쇼케이스 베이스 config 없음)용 중립 palace 베이스. corpus 는 업로드
    파일, domain 은 감지 라벨. frozen_toc 없음 -> build_palace 가 full(toc+rooms) 라이브
    경로를 탄다. 커밋된 캐시가 없어 seed 는 miss(콜드 빌드 = real LLM), 신규 도메인의
    기대 동작과 일치한다."""
    corpus_rel = _rel(Path(job.input_path))
    return {
        "run_id": job.run_id,
        "corpus": corpus_rel,
        "corpus_rel": corpus_rel,
        "min_rooms": 1,
        "max_rooms": 10,
        "node_budget": 20,
        "n_runs": 1,
        "model": "gpt-4.1-mini",
        "domain": job.domain,
        # 커밋된 캐시가 없는 중립 경로(seed 는 디렉터리 부재로 miss = 콜드).
        "rubric_cache_path": "cache/palace/live/rubric.json",
        "stage_b_cache_dir": "cache/palace/live/stage_b",
    }


def _build_job_palace_config(job: Job, snapshot_path: str) -> tuple[Path, dict, Optional[str]]:
    """Materialize a per-job palace config from the domain base, overriding all
    outputs/caches into var/jobs/<id>/ and pointing at the job's fresh snapshot.
    corpus/domain/node_budget/n_runs/model/room bounds and frozen_toc
    (korean_history only) are kept from the base, so the domain branch (frozen
    rooms-only vs full toc+rooms) falls out of base.frozen_toc and never relies
    on a stage kwarg. Per-job cache paths keep the base's basenames so the seed
    (option A) lands where palace looks. Showcase domains use their committed
    base config; live jobs (domain not a showcase key) get a neutral base whose
    corpus is the uploaded file. Returns (config_path, cfg, seeded_src)."""
    base_rel = config.PALACE_CONFIGS.get(job.domain)
    if base_rel is None:
        # 라이브 잡: 중립 베이스 합성(업로드 corpus + 감지 domain).
        base = _default_palace_base(job)
    else:
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


def _run_match_images(
    palace: Path, snapshot: Path, figures_json: Path, pagesplit: Path, out_dir: Path,
) -> tuple[int, str]:
    """palace/match_images 를 subprocess 로 돌려 figures.json 기반 이미지↔노드 매칭 후
    palace_with_images.json + unplaced_figures.json + images/ 를 out_dir 에 만든다.
    lancedb + numpy + Azure 임베딩을 워커 이벤트 루프에서 격리(_run_palace 와 동형 seam).
    env(.env)를 상속해 캡션 임베딩의 GRAPHRAG_API_KEY/BASE 가 풀린다."""
    config.load_env()
    proc = subprocess.run(
        [sys.executable, "-m", "palace.match_images",
         "--palace", str(palace), "--snapshot", str(snapshot),
         "--figures-json", str(figures_json), "--pagesplit", str(pagesplit),
         "--out-dir", str(out_dir)],
        cwd=str(config.REPO),
        capture_output=True, text=True, encoding="utf-8",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


async def build_palace(
    job: Job,
    store: JobStore,
    sleep_seconds: float,
) -> None:
    # 방 생성(toc 재사용 시 rooms-only + 이미지 매칭) 진행 표시용 state. 프론트 로딩
    # 바가 인덱싱과 방 생성을 구분해 보여줄 수 있게 한다(완료 시 PALACE_READY 로 전이).
    store.update(job.job_id, state=State.BUILDING_PALACE)
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
    # toc 단계가 이미 목차를 만들었으면(toc_out 존재) rooms 만 돈다(중복 생성 제거).
    # toc 가 스킵/실패해 toc_out 이 없으면 기존대로 toc+rooms 로 폴백한다.
    toc_out_path = config.job_dir(job.job_id) / "palace_out" / f"{job.run_id}.toc_llm.json"
    if not cfg.get("frozen_toc") and toc_out_path.exists():
        phases = ["rooms"]
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

    # 라이브 PDF 잡: 전처리 이미지(figures.json)를 palace 노드에 매칭해 self-contained
    # 산출물(palace_with_images.json + unplaced_figures.json + images/)을 palace_out 에
    # 만든다. STEP4 분리 자식(_cv_)도 figures.json 레코드라 자기 캡션 달고 흐른다.
    # 쇼케이스(프리베이크)는 preprocess 를 건너뛰어 figures.json 이 없으니 자동 스킵,
    # .txt 라이브 업로드도 이미지가 없어 스킵. 매칭 실패는 텍스트 palace/RAG 와 무관해
    # 잡을 죽이지 않고 경고만 남긴다(best-effort; 텍스트 체인은 그대로 진행).
    pre = config.job_dir(job.job_id) / "preprocess"
    figures_json = pre / "meta" / "figures.json"
    pagesplit = pre / "txt" / "content_paged.txt"
    if not job.showcase_key and figures_json.exists() and pagesplit.exists():
        out_dir = config.job_dir(job.job_id) / "palace_out"
        rc, out = await loop.run_in_executor(
            None, _run_match_images,
            palace_path, Path(fresh.snapshot_path), figures_json, pagesplit, out_dir,
        )
        if rc != 0:
            logger.warning(
                "이미지 매칭 실패(텍스트 palace 유지, best-effort) job=%s rc=%d:\n%s",
                job.job_id, rc, out[-800:],
            )
        else:
            logger.info("이미지 매칭 완료 job=%s: %s", job.job_id, out.strip()[-300:])
            # 매칭 이미지(palace_out/images)를 Blob 에 영속한다 — 재시작/잡 삭제로
            # 로컬·DB 기록이 사라져도 job_id+파일명으로 서빙되게(서빙은 DB 와 분리).
            # 미설정이면 no-op. best-effort(텍스트 체인과 무관해 잡을 죽이지 않는다).
            try:
                n = blob.upload_job_images(job.job_id, out_dir / "images")
                if n:
                    logger.info("이미지 Blob 업로드 job=%s: %d개", job.job_id, n)
            except Exception as e:
                logger.warning("이미지 Blob 업로드 단계 예외 job=%s: %s", job.job_id, e)

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
PIPELINE = (preprocess, toc, index, build_palace, rag)
