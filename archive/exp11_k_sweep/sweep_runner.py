"""K sweep 결정적 부분만. LLM 0회.

room_gen.py의 load_snapshot, base_cluster, split_oversized, merge_to_k(strategy='embedding')만 호출.
generate_rooms / derive_rubric / assign_rooms / make_azure_client 등 LLM 경로는 진입 금지.

Parameters mirror results/exp10_room_gen/run_repro_run3.py:
  SNAPSHOT='results/snapshots/repro_run3', K_BASE=12, MAX_CLUSTER_SIZE=55, merge='embedding'.

출력: results/exp11_k_sweep/sweep_K{K}.json (K=2..10).
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path('results/exp10_room_gen')))

from room_gen import (  # noqa: E402
    base_cluster,
    load_snapshot,
    merge_to_k,
    split_oversized,
)

SNAPSHOT = 'results/snapshots/repro_run3'
K_BASE = 12
MAX_CLUSTER_SIZE = 55
OUT_DIR = Path('results/exp11_k_sweep')


def run_one(entities, K):
    base = base_cluster(entities, K_BASE)
    after = split_oversized(base, entities, MAX_CLUSTER_SIZE)
    merged = merge_to_k(after, entities, K, strategy='embedding')
    return base, after, merged


def serialize(entities, merged, K):
    rooms = []
    for room_id, idxs in enumerate(merged):
        members = [
            {
                'id': entities[i]['id'],
                'title': entities[i]['title'],
                'type': entities[i]['type'],
                'degree': entities[i]['degree'],
            }
            for i in idxs
        ]
        members.sort(key=lambda m: (-m['degree'], m['title']))
        rooms.append({'room_id': room_id, 'size': len(members), 'members': members})
    return {
        'meta': {
            'snapshot': SNAPSHOT,
            'K': K,
            'k_base': K_BASE,
            'max_cluster_size': MAX_CLUSTER_SIZE,
            'merge_strategy': 'embedding',
            'n_entities': sum(r['size'] for r in rooms),
        },
        'rooms': rooms,
    }


def main():
    entities, meta = load_snapshot(SNAPSHOT)
    print(f'snapshot: n_entities={meta["n_entities"]} dim={meta["embedding_dim"]}')

    rows = []
    for K in range(2, 11):
        base, after, merged = run_one(entities, K)
        spec = serialize(entities, merged, K)
        out = OUT_DIR / f'sweep_K{K}.json'
        out.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')
        sizes = sorted([r['size'] for r in spec['rooms']], reverse=True)
        ratio = sizes[0] / sizes[-1] if sizes[-1] else float('inf')
        rows.append((K, len(spec['rooms']), sizes, ratio))
        print(f'  K={K}: rooms={len(spec["rooms"])} sizes={sizes} max/min={ratio:.2f}')
        # invariant: base/after stable across K (k_base=12 fixed, split deterministic)
    print()

    # 결정성 체크: K=5 한 번 더
    _, _, merged_a = run_one(entities, 5)
    _, _, merged_b = run_one(entities, 5)
    norm = lambda m: sorted(tuple(sorted(g)) for g in m)
    same = norm(merged_a) == norm(merged_b)
    print(f'determinism K=5 (2 runs): {"IDENTICAL" if same else "DIFFER"}')


if __name__ == '__main__':
    main()
