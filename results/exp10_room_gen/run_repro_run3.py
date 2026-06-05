"""exp10 repro_run3 validation: K=10,5 x merge=embedding,llm = 4 runs.

repro_run3 has 357 entities, natural max cluster ~51. With max_cluster_size=55
no split should fire (happy path). LLM calls per combo:
  K=10: 10 stage-B + (1 stage-A shared, cached) + (1 LLM-merge if strategy=llm)
  K=5 : 5  stage-B + (cached A)               + (1 if llm)
Total: 30 stage-B + 1 stage-A + 2 LLM-merge = 33 calls.

Outputs go to results/rooms/<run_id>.{json,md}. Rubric cached to
cache/exp10_room_gen/rubric_repro_run3.json so it's derived exactly once.

Run:
    .venv/Scripts/python.exe results/exp10_room_gen/run_repro_run3.py
Or with --dry to skip LLM and just print the cluster-pipeline shapes:
    .venv/Scripts/python.exe results/exp10_room_gen/run_repro_run3.py --dry
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent))

from room_gen import (  # noqa: E402
    base_cluster,
    generate_rooms,
    load_snapshot,
    make_azure_client,
    split_oversized,
)

SNAPSHOT = 'results/snapshots/repro_run3'
OUT_DIR = 'results/rooms'
RUBRIC_CACHE = 'cache/exp10_room_gen/rubric_repro_run3.json'
MODEL = 'gpt-4.1-mini'
DOMAIN = '한국사'
K_BASE = 12
MAX_CLUSTER_SIZE = 55
N_RUNS = 1
NODE_BUDGET = 20

COMBOS = [
    {'K': 10, 'merge_strategy': 'embedding'},
    {'K': 10, 'merge_strategy': 'llm'},
    {'K': 5,  'merge_strategy': 'embedding'},
    {'K': 5,  'merge_strategy': 'llm'},
]


def dry_report():
    entities, meta = load_snapshot(SNAPSHOT)
    print(f'snapshot: {meta}')
    base = base_cluster(entities, K_BASE)
    print(f'base k_base={K_BASE} sizes: {sorted([len(c) for c in base], reverse=True)}')
    after = split_oversized(base, entities, MAX_CLUSTER_SIZE)
    print(f'after split max={MAX_CLUSTER_SIZE} sizes: {sorted([len(c) for c in after], reverse=True)}')
    if len(after) == len(base):
        print('  -> happy path: split fired 0 times (expected for repro_run3)')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry', action='store_true', help='show pipeline shapes, no LLM')
    parser.add_argument('--only', help='comma-separated combo names (e.g. K10_embedding,K10_llm)')
    args = parser.parse_args()

    if args.dry:
        dry_report()
        return

    only = set(args.only.split(',')) if args.only else None

    client = make_azure_client()
    print(f'starting at {time.strftime("%Y-%m-%d %H:%M:%S")}')

    summary = []
    for combo in COMBOS:
        run_id = f'repro_run3_K{combo["K"]}_{combo["merge_strategy"]}'
        if only and run_id not in only:
            continue
        print(f'\n=== {run_id} ===')
        t0 = time.time()
        spec = generate_rooms(
            snapshot_path=SNAPSHOT,
            K=combo['K'],
            k_base=K_BASE,
            max_cluster_size=MAX_CLUSTER_SIZE,
            merge_strategy=combo['merge_strategy'],
            n_runs=N_RUNS,
            node_budget=NODE_BUDGET,
            domain=DOMAIN,
            model=MODEL,
            output_dir=OUT_DIR,
            run_id=run_id,
            llm_client=client,
            rubric_cache_path=RUBRIC_CACHE,
        )
        dt = time.time() - t0
        total = sum(len(r['kept']) + len(r['demoted']) for r in spec['rooms'])
        n_forced = sum(r.get('_meta', {}).get('n_forced_demote', 0) for r in spec['rooms'])
        sizes = spec['meta']['pipeline']['final_sizes']
        names = ' | '.join(r['name'] for r in spec['rooms'])
        print(f'  final sizes: {sizes}')
        print(f'  rooms: {names}')
        print(f'  완전성: {total}/357  forced_demote: {n_forced}  ({dt:.1f}s)')
        summary.append({
            'run_id': run_id, 'sizes': sizes, 'total': total,
            'forced': n_forced, 'dt': round(dt, 1),
        })

    print('\n=== summary ===')
    for s in summary:
        print(f'  {s["run_id"]:<32} sizes={s["sizes"]} total={s["total"]} forced={s["forced"]} {s["dt"]}s')


if __name__ == '__main__':
    main()
