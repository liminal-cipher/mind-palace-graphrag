"""End-to-end TOC arm on the repro_run3 textbook snapshot.

Wiring only: TOC arm functions live in results/exp17_generalization/
(toc_gen.generate_toc, build.*). This script picks them up, runs them
against the textbook corpus, converts the output to the room_gen
common schema, absorbs empty rooms, writes results/rooms/<run_id>.json
and then calls export_palace.export() to emit the .palace.json.

Two-phase entry by design:
    --phase toc   -> generate toc_llm.json only and STOP for review.
    --phase rooms -> read existing toc_llm.json and continue all the way
                     to .palace.json.

That keeps the LLM TOC inspectable before paying for occurrence + rubric
+ keep/demote + palace. Output paths and run_id are fixed so two runs of
the same phase are byte-identical (modulo generated_at).
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'results' / 'exp17_generalization'))
sys.path.insert(0, str(REPO / 'results' / 'exp10_room_gen'))
sys.path.insert(0, str(REPO / 'results' / 'node_order_probe'))

import pandas as pd  # noqa: E402

from toc_gen import generate_toc  # noqa: E402
from build import (  # noqa: E402
    absorb_empty_rooms,
    apply_keep_demote,
    attach_positions,
    build_toc_rooms,
    convert_toc_to_common_schema,
)
import node_metrics  # noqa: E402
from room_gen import derive_rubric, load_snapshot, make_azure_client  # noqa: E402
import export_palace  # noqa: E402


RUN_ID = 'repro_run3_K6_toc'
CORPUS = REPO / 'input' / '국사교과서_조선_본문_정제.txt'
SNAPSHOT = REPO / 'results' / 'snapshots' / 'repro_run3'
SNAPSHOT_REL = 'results/snapshots/repro_run3'
ROOMS_DIR = REPO / 'results' / 'rooms'
TOC_OUT = ROOMS_DIR / f'{RUN_ID}.toc_llm.json'
ROOMS_OUT = ROOMS_DIR / f'{RUN_ID}.json'
RUBRIC_CACHE = REPO / 'cache' / 'exp10_room_gen' / 'rubric_repro_run3_toc.json'
STAGE_B_CACHE = REPO / 'cache' / 'exp10_room_gen' / 'stage_b_repro_run3_toc'

K = 6
NODE_BUDGET = 20
MODEL = 'gpt-4.1-mini'
DOMAIN = '조선 전기 한국사 (건국·통치제도·문화·사림·왜란·붕당·실학)'


def stop_if_missing() -> None:
    missing = []
    if not CORPUS.exists():
        missing.append(str(CORPUS.relative_to(REPO)))
    for name in ('entities.parquet', 'text_units.parquet', 'documents.parquet'):
        if not (SNAPSHOT / name).exists():
            missing.append(f'{SNAPSHOT_REL}/{name}')
    if not (SNAPSHOT / 'lancedb').exists():
        missing.append(f'{SNAPSHOT_REL}/lancedb')
    if missing:
        print('STOP: required inputs missing:')
        for m in missing:
            print(f'  - {m}')
        sys.exit(2)


def phase_toc() -> None:
    ROOMS_DIR.mkdir(parents=True, exist_ok=True)
    generate_toc(CORPUS, out_path=TOC_OUT, model=MODEL)


def phase_rooms() -> None:
    if not TOC_OUT.exists():
        print(f'STOP: {TOC_OUT.relative_to(REPO)} not found; run --phase toc first')
        sys.exit(2)
    toc_payload = json.loads(TOC_OUT.read_text(encoding='utf-8'))
    sections = toc_payload['sections']

    text = CORPUS.read_text(encoding='utf-8')
    ent_df = pd.read_parquet(SNAPSHOT / 'entities.parquet')
    tu_df = pd.read_parquet(SNAPSHOT / 'text_units.parquet')
    entities, snap_meta = load_snapshot(SNAPSHOT)
    n_ent = len(entities)
    print(f'entities loaded: {n_ent}')

    ent_metrics = node_metrics.compute_entity_metrics(ent_df, tu_df, text)

    print('building TOC arm (occurrence weighted by char overlap)...')
    toc_spec, _ = build_toc_rooms(entities, ent_df, tu_df, text, sections)
    print(f'  raw room sizes: {[r["size"] for r in toc_spec["rooms"]]}')

    print('sorting members by pos_first_fine...')
    toc_spec = attach_positions(toc_spec, ent_metrics, ent_df, tu_df, text)

    print('deriving rubric (LLM Stage A, cached if present)...')
    client = make_azure_client()
    sample_titles = sorted(e['title'] for e in entities)[:60]
    sample = [e for e in entities if e['title'] in set(sample_titles)]
    RUBRIC_CACHE.parent.mkdir(parents=True, exist_ok=True)
    rubric = derive_rubric(DOMAIN, sample, client, MODEL, cache_path=RUBRIC_CACHE)
    print(f'  rubric items: {len(rubric.get("rubric", []))}')

    print('applying keep/demote per room (LLM Stage B)...')
    toc_spec = apply_keep_demote(
        toc_spec, entities, rubric, client,
        domain=DOMAIN, model=MODEL, node_budget=NODE_BUDGET, n_runs=1,
        rubric_source_rel=str(RUBRIC_CACHE.relative_to(REPO)).replace('\\', '/'),
        stage_b_cache_dir=STAGE_B_CACHE,
    )

    print('converting to room_gen common schema...')
    rooms_json = convert_toc_to_common_schema(
        toc_spec,
        run_id=RUN_ID,
        domain=DOMAIN,
        snapshot_rel=SNAPSHOT_REL,
        model=MODEL,
        node_budget=NODE_BUDGET,
        n_entities=n_ent,
        k=K,
    )
    pre = [(r['room_id'], len(r['kept']), len(r['demoted'])) for r in rooms_json['rooms']]
    print(f'  rooms (id, kept, demoted): {pre}')

    print('absorbing empty rooms into successors (fallback: predecessor)...')
    rooms_json = absorb_empty_rooms(rooms_json)
    post = [(r['room_id'], len(r['kept']), len(r['demoted'])) for r in rooms_json['rooms']]
    print(f'  rooms after absorb: {post}')

    ROOMS_OUT.write_text(
        json.dumps(rooms_json, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    print(f'wrote: {ROOMS_OUT.relative_to(REPO)}')

    print('exporting palace.json...')
    palace_path, stats = export_palace.export(RUN_ID, SNAPSHOT, with_relationships=False)
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
    kept_dist = [(r['id'], r['name'], r['kept_count']) for r in rooms]
    print(
        'keep dist: '
        + ' | '.join(f'{rid}({nm}) {kc}' for rid, nm, kc in kept_dist)
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', choices=['toc', 'rooms'], required=True)
    args = ap.parse_args()
    stop_if_missing()
    if args.phase == 'toc':
        phase_toc()
    else:
        phase_rooms()


if __name__ == '__main__':
    main()
