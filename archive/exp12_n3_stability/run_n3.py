"""n=3 Stage B 흔들림 측정 (embedding × {K=10, K=5}).

결정적 부분(load → base → split → merge)은 K별 1회.
Stage B(_run_stage_b_once)만 클러스터당 3회 호출. rubric은 RUBRIC_CACHE 재사용.

출력: results/exp12_n3_stability/K{K}_run{n}.json 형식
  {
    'meta': {K, run_idx, snapshot, ...},
    'rooms': [
      {'room_id', 'name', 'kept': [{title,type,degree,id}], 'demoted': [...], 'coherence', 'n_hallucinated'}
    ]
  }
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path('results/exp10_room_gen')))


def _load_dotenv(path: str = '.env') -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

import random  # noqa: E402

from room_gen import (  # noqa: E402
    _run_stage_b_once,
    base_cluster,
    derive_rubric,
    load_snapshot,
    make_azure_client,
    merge_to_k,
    split_oversized,
)

SNAPSHOT = 'results/snapshots/repro_run3'
RUBRIC_CACHE = 'cache/exp10_room_gen/rubric_repro_run3.json'
DOMAIN = '한국사'
MODEL = 'gpt-4.1-mini'
K_BASE = 12
MAX_CLUSTER_SIZE = 55
NODE_BUDGET = 20
N_RUNS = 3
SAMPLE_SIZE = 60
SAMPLE_SEED = 42
OUT = Path('results/exp12_n3_stability')
OUT.mkdir(parents=True, exist_ok=True)


def members_payload_of(entities, cluster_idx):
    return [
        {
            'title': entities[i]['title'],
            'type': entities[i]['type'],
            'degree': entities[i]['degree'],
            'desc': entities[i]['description'][:200],
        }
        for i in cluster_idx
    ]


def serialize_run(entities, merged_clusters, run_results, K, run_idx):
    rooms = []
    for room_id, (cluster_idx, sb) in enumerate(zip(merged_clusters, run_results)):
        title_to_e = {entities[i]['title']: entities[i] for i in cluster_idx}
        kept = [
            {
                'id': title_to_e[t]['id'],
                'title': t,
                'type': title_to_e[t]['type'],
                'degree': title_to_e[t]['degree'],
            }
            for t in sb['keep_order']
        ]
        demoted = [
            {
                'id': title_to_e[t]['id'],
                'title': t,
                'type': title_to_e[t]['type'],
                'degree': title_to_e[t]['degree'],
            }
            for t in sorted(sb['demote_set'], key=lambda x: -title_to_e[x]['degree'])
        ]
        rooms.append({
            'room_id': room_id,
            'name': sb['room_name'],
            'coherence': sb['coherence'],
            'coherence_reason': sb['coherence_reason'],
            'kept': kept,
            'demoted': demoted,
            'n_hallucinated': sb['n_hallucinated'],
        })
    return {
        'meta': {
            'snapshot': SNAPSHOT,
            'K': K,
            'k_base': K_BASE,
            'max_cluster_size': MAX_CLUSTER_SIZE,
            'merge_strategy': 'embedding',
            'node_budget': NODE_BUDGET,
            'domain': DOMAIN,
            'model': MODEL,
            'run_idx': run_idx,
            'n_runs_total': N_RUNS,
            'n_entities': sum(len(r['kept']) + len(r['demoted']) for r in rooms),
        },
        'rooms': rooms,
    }


def main():
    entities, meta = load_snapshot(SNAPSHOT)
    print(f'snapshot: n_entities={meta["n_entities"]}')

    client = make_azure_client()

    # Stage A: rubric (RUBRIC_CACHE 재사용 → 0 LLM call)
    rng = random.Random(SAMPLE_SEED)
    sample = rng.sample(entities, min(SAMPLE_SIZE, len(entities)))
    rubric = derive_rubric(DOMAIN, sample, client, MODEL, cache_path=RUBRIC_CACHE)
    print(f'rubric loaded ({len(rubric.get("rubric", []))} rules)')

    for K in [10, 5]:
        print(f'\n=== K={K} ===')
        base = base_cluster(entities, K_BASE)
        after = split_oversized(base, entities, MAX_CLUSTER_SIZE)
        merged = merge_to_k(after, entities, K, strategy='embedding')
        sizes = sorted([len(c) for c in merged], reverse=True)
        print(f'  clusters: sizes={sizes}')

        for run_idx in range(1, N_RUNS + 1):
            print(f'  run {run_idx}/{N_RUNS} ...', end=' ', flush=True)
            t0 = time.time()
            run_results = []
            for cid, idxs in enumerate(merged):
                payload = members_payload_of(entities, idxs)
                sb = _run_stage_b_once(
                    cid, payload, DOMAIN, rubric, NODE_BUDGET, client, MODEL,
                )
                run_results.append(sb)
            spec = serialize_run(entities, merged, run_results, K, run_idx)
            out = OUT / f'K{K}_run{run_idx}.json'
            out.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')
            total_kept = sum(len(r['kept']) for r in spec['rooms'])
            total_dem = sum(len(r['demoted']) for r in spec['rooms'])
            print(f'kept={total_kept} demoted={total_dem} ({time.time()-t0:.1f}s)')


if __name__ == '__main__':
    main()
