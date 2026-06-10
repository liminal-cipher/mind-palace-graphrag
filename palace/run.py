"""palace runner: config + phase -> TOC LLM (phase=toc) or full rooms +
palace.json (phase=rooms). Two-phase by design so the LLM TOC stays
inspectable before paying for Stage A/B + palace export.

Usage:
    python -m palace.run --config palace/configs/repro_run3_K6_toc.json --phase toc
    python -m palace.run --config palace/configs/repro_run3_K6_toc.json --phase rooms

Config schema (paths are repo-relative):
    run_id              str    base name for outputs
    corpus              str    .txt file
    corpus_rel          str    (optional) value written into toc_llm.json
                               meta.corpus; defaults to corpus
    snapshot            str    snapshot dir (entities/text_units/documents/
                               relationships parquet + lancedb)
    snapshot_rel        str    value written into rooms.json meta.snapshot
    rooms_dir           str    where rooms.json + palace.json get written
    toc_out             str    where toc_llm.json gets written
    K                   int    target room count (TOC sections)
    node_budget         int    keep cap per room
    n_runs              int    Stage B passes per room (1 = single pass)
    model               str    Azure deployment name
    domain              str    Korean free-text domain label
    rubric_cache_path   str    Stage A cache
    stage_b_cache_dir   str    Stage B per-prompt cache dir
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

from palace import node_metrics  # noqa: E402
from palace.build_rooms import (  # noqa: E402
    absorb_empty_rooms,
    apply_keep_demote,
    attach_positions,
    build_toc_rooms,
    convert_toc_to_common_schema,
)
from palace.room_gen import (  # noqa: E402
    derive_rubric,
    load_snapshot,
    make_azure_client,
)
from palace.toc_gen import generate_toc  # noqa: E402
from palace import export_palace  # noqa: E402


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())


def _abs(repo: Path, rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else (repo / p)


def _stop_if_missing(cfg: dict, repo: Path) -> None:
    missing = []
    corpus = _abs(repo, cfg['corpus'])
    if not corpus.exists():
        missing.append(cfg['corpus'])
    snapshot = _abs(repo, cfg['snapshot'])
    for name in ('entities.parquet', 'text_units.parquet', 'documents.parquet'):
        if not (snapshot / name).exists():
            missing.append(f'{cfg["snapshot"]}/{name}')
    if not (snapshot / 'lancedb').exists():
        missing.append(f'{cfg["snapshot"]}/lancedb')
    if missing:
        print('STOP: required inputs missing:')
        for m in missing:
            print(f'  - {m}')
        sys.exit(2)


def phase_toc(cfg: dict, repo: Path) -> None:
    toc_out = _abs(repo, cfg['toc_out'])
    toc_out.parent.mkdir(parents=True, exist_ok=True)
    corpus = _abs(repo, cfg['corpus'])
    corpus_rel = cfg.get('corpus_rel') or cfg['corpus']
    generate_toc(
        corpus,
        out_path=toc_out,
        model=cfg['model'],
        corpus_rel=corpus_rel,
    )


def phase_rooms(cfg: dict, repo: Path) -> None:
    toc_out = _abs(repo, cfg['toc_out'])
    if not toc_out.exists():
        print(f'STOP: {cfg["toc_out"]} not found; run --phase toc first')
        sys.exit(2)
    toc_payload = json.loads(toc_out.read_text(encoding='utf-8'))
    sections = toc_payload['sections']

    corpus = _abs(repo, cfg['corpus'])
    snapshot = _abs(repo, cfg['snapshot'])
    rooms_dir = _abs(repo, cfg['rooms_dir'])
    rubric_cache = _abs(repo, cfg['rubric_cache_path'])
    stage_b_cache = _abs(repo, cfg['stage_b_cache_dir'])

    text = corpus.read_text(encoding='utf-8')
    ent_df = pd.read_parquet(snapshot / 'entities.parquet')
    tu_df = pd.read_parquet(snapshot / 'text_units.parquet')
    entities, _ = load_snapshot(snapshot)
    n_ent = len(entities)
    print(f'entities loaded: {n_ent}')

    ent_metrics = node_metrics.compute_entity_metrics(ent_df, tu_df, text)

    corpus_rel = cfg.get('corpus_rel') or cfg['corpus']
    print('building TOC arm (occurrence weighted by char overlap)...')
    toc_spec, _ = build_toc_rooms(
        entities, ent_df, tu_df, text, sections,
        K=cfg['K'], corpus_rel=corpus_rel,
    )
    print(f'  raw room sizes: {[r["size"] for r in toc_spec["rooms"]]}')

    print('sorting members by pos_first_fine...')
    toc_spec = attach_positions(toc_spec, ent_metrics, ent_df, tu_df, text)

    print('deriving rubric (LLM Stage A, cached if present)...')
    client = make_azure_client()
    sample_titles = sorted(e['title'] for e in entities)[:60]
    sample = [e for e in entities if e['title'] in set(sample_titles)]
    rubric_cache.parent.mkdir(parents=True, exist_ok=True)
    rubric = derive_rubric(
        cfg['domain'], sample, client, cfg['model'], cache_path=rubric_cache,
    )
    print(f'  rubric items: {len(rubric.get("rubric", []))}')

    print('applying keep/demote per room (LLM Stage B)...')
    toc_spec = apply_keep_demote(
        toc_spec, entities, rubric, client,
        domain=cfg['domain'], model=cfg['model'],
        node_budget=cfg['node_budget'], n_runs=cfg['n_runs'],
        rubric_source_rel=cfg['rubric_cache_path'],
        stage_b_cache_dir=stage_b_cache,
    )

    print('converting to room_gen common schema...')
    rooms_json = convert_toc_to_common_schema(
        toc_spec,
        run_id=cfg['run_id'],
        domain=cfg['domain'],
        snapshot_rel=cfg['snapshot_rel'],
        model=cfg['model'],
        node_budget=cfg['node_budget'],
        n_entities=n_ent,
        n_runs=cfg['n_runs'],
        k=cfg['K'],
    )
    pre = [(r['room_id'], len(r['kept']), len(r['demoted'])) for r in rooms_json['rooms']]
    print(f'  rooms (id, kept, demoted): {pre}')

    print('absorbing empty rooms into successors (fallback: predecessor)...')
    rooms_json = absorb_empty_rooms(rooms_json)
    post = [(r['room_id'], len(r['kept']), len(r['demoted'])) for r in rooms_json['rooms']]
    print(f'  rooms after absorb: {post}')

    rooms_dir.mkdir(parents=True, exist_ok=True)
    rooms_out = rooms_dir / f'{cfg["run_id"]}.json'
    rooms_out.write_text(
        json.dumps(rooms_json, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    print(f'wrote: {rooms_out}')

    print('exporting palace.json...')
    palace_path, stats = export_palace.export(
        cfg['run_id'], snapshot, rooms_dir, with_relationships=False,
    )
    print(f'wrote: {palace_path}')

    palace = json.loads(Path(palace_path).read_text(encoding='utf-8'))
    rooms = palace['rooms']
    n_rooms = palace['palace']['room_count']
    empty_rooms = sum(1 for r in rooms if r['kept_count'] == 0)
    n_kept = sum(r['kept_count'] for r in rooms)
    n_demoted = sum(len(r['demoted']) for r in rooms)
    n_entities_in = palace['palace']['source']['entity_count']
    total = n_kept + n_demoted
    fine = stats['fine']
    fb = stats['fallback']
    total_pos = fine + fb
    fine_ratio = fine / total_pos if total_pos else 0.0
    fb_ratio = fb / total_pos if total_pos else 0.0
    print(
        f'palace check: room_count={n_rooms} (<=10: {"yes" if n_rooms <= 10 else "NO"}) '
        f'empty_rooms={empty_rooms} kept={n_kept} demoted={n_demoted} '
        f'preserved={total}/{n_entities_in} ({"yes" if total == n_entities_in else "NO"}) '
        f'fine={fine} ({fine_ratio:.2%}) fallback={fb} ({fb_ratio:.2%})'
    )


def main() -> None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--phase', choices=['toc', 'rooms'], required=True)
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = REPO / cfg_path
    cfg = json.loads(cfg_path.read_text(encoding='utf-8'))

    _load_dotenv(REPO / '.env')
    _stop_if_missing(cfg, REPO)

    if args.phase == 'toc':
        phase_toc(cfg, REPO)
    else:
        phase_rooms(cfg, REPO)


if __name__ == '__main__':
    main()
