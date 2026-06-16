"""generic 사전 제거 후 재클러스터 sweep. K=10 고정, LLM 0회.

각 제거수준 N ∈ {0,10,20,30}: degree desc 상위 N개 엔티티를 빼고 나머지로
base_cluster(k_base=12) → split_oversized(max=55) → merge_to_k(embedding, K=10).

저장: results/exp13_generic_filter/filter_N{N}.json.
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
K = 10
K_BASE = 12
MAX_CLUSTER_SIZE = 55
LEVELS = [0, 10, 20, 30]
OUT = Path('results/exp13_generic_filter')


def cluster_pipeline(entities):
    base = base_cluster(entities, K_BASE)
    after = split_oversized(base, entities, MAX_CLUSTER_SIZE)
    merged = merge_to_k(after, entities, K, strategy='embedding')
    return merged


def serialize(entities_filtered, merged, N, removed):
    rooms = []
    for room_id, idxs in enumerate(merged):
        members = [
            {
                'id': entities_filtered[i]['id'],
                'title': entities_filtered[i]['title'],
                'type': entities_filtered[i]['type'],
                'degree': entities_filtered[i]['degree'],
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
            'removed_top_N': N,
            'removed_titles': [r['title'] for r in removed],
            'n_entities_used': sum(r['size'] for r in rooms),
        },
        'rooms': rooms,
    }


def main():
    entities, meta = load_snapshot(SNAPSHOT)
    print(f'snapshot: n_entities={meta["n_entities"]}')

    # degree desc 정렬 (안정적 tiebreak: title)
    sorted_entities = sorted(entities, key=lambda e: (-e['degree'], e['title']))

    for N in LEVELS:
        removed = sorted_entities[:N]
        removed_ids = {e['id'] for e in removed}
        entities_filtered = [e for e in entities if e['id'] not in removed_ids]

        merged = cluster_pipeline(entities_filtered)
        spec = serialize(entities_filtered, merged, N, removed)

        out = OUT / f'filter_N{N}.json'
        out.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')

        sizes = sorted([r['size'] for r in spec['rooms']], reverse=True)
        ratio = sizes[0] / sizes[-1]
        print(f'  N={N:>2}: n_used={meta["n_entities"] - N:>3} sizes={sizes} max/min={ratio:.2f}')


if __name__ == '__main__':
    main()
