"""Canonical pipeline runner. Reuses exp10 (clustering + Stage A + Stage B
with n-runs majority vote already in room_gen) and exp10 export_palace.
No core logic re-implementation.

Locked defaults (overridable via flags): merge=embedding, K=10, n=3,
node_budget=20, snapshot=results/snapshots/repro_run3, model=gpt-4.1-mini.

Outputs (results/pipeline/, won't overwrite results/rooms/):
  rooms.json, palace.json, cost_report.json, report.md
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

EXP10_DIR = Path('results/exp10_room_gen')
sys.path.insert(0, str(EXP10_DIR))


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

import room_gen  # noqa: E402
from room_gen import (  # noqa: E402
    HARD_CAP_K,
    assign_rooms,
    base_cluster,
    check_invariants,
    derive_rubric,
    load_snapshot,
    make_azure_client,
    merge_to_k,
    split_oversized,
)
import export_palace  # noqa: E402


# ---------------------------------------------------------------------------
# Instrumentation: tag the current pipeline stage so call_json usage is
# attributed correctly. Wrap room_gen.call_json without modifying the source.
# ---------------------------------------------------------------------------

_current_stage = ['unknown']
_usage_by_stage: dict[str, dict] = defaultdict(
    lambda: {'prompt_tokens': 0, 'completion_tokens': 0, 'calls': 0, 'call_seconds': 0.0}
)
_orig_call_json = room_gen.call_json


def _instrumented_call_json(*args, **kw):
    stage = _current_stage[0]
    t0 = time.perf_counter()
    result = _orig_call_json(*args, **kw)
    dt = time.perf_counter() - t0
    _, usage = result
    acc = _usage_by_stage[stage]
    acc['prompt_tokens'] += int(usage.get('prompt_tokens', 0))
    acc['completion_tokens'] += int(usage.get('completion_tokens', 0))
    acc['calls'] += 1
    acc['call_seconds'] += dt
    return result


room_gen.call_json = _instrumented_call_json


# ---------------------------------------------------------------------------
# Pricing + cost calc
# ---------------------------------------------------------------------------


def load_pricing(path: Path, model: str) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    info = data.get(model) or {}
    return {
        'input_per_1m': info.get('input_per_1m'),
        'output_per_1m': info.get('output_per_1m'),
        '_note': data.get('_note'),
        '_source': info.get('_source'),
    }


def stage_cost(usage: dict, pricing: dict) -> str | float:
    if pricing.get('input_per_1m') is None or pricing.get('output_per_1m') is None:
        return 'pending'
    pt = usage['prompt_tokens'] / 1_000_000.0 * pricing['input_per_1m']
    ct = usage['completion_tokens'] / 1_000_000.0 * pricing['output_per_1m']
    return round(pt + ct, 6)


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


def run_pipeline(
    snapshot: str,
    K: int,
    n: int,
    node_budget: int,
    k_base: int,
    max_cluster_size: int,
    domain: str,
    model: str,
    out_dir: Path,
    pricing_path: Path,
    rubric_cache: Path,
    sample_size: int = 60,
    sample_seed: int = 42,
) -> dict:
    if K > HARD_CAP_K:
        raise ValueError(f'K={K} exceeds hard cap {HARD_CAP_K}')
    if k_base < K:
        raise ValueError(f'k_base ({k_base}) < K ({K})')

    timings: dict[str, float] = {}
    pricing = load_pricing(pricing_path, model)
    client = make_azure_client()

    # snapshot_load
    _current_stage[0] = 'snapshot_load'
    t0 = time.perf_counter()
    entities, snap_meta = load_snapshot(snapshot)
    timings['snapshot_load'] = time.perf_counter() - t0
    print(f'snapshot_load: {timings["snapshot_load"]:.2f}s  n_entities={snap_meta["n_entities"]}')

    # clustering (deterministic, no LLM)
    _current_stage[0] = 'clustering'
    t0 = time.perf_counter()
    base = base_cluster(entities, k_base)
    after_split = split_oversized(base, entities, max_cluster_size)
    merged = merge_to_k(after_split, entities, K, strategy='embedding')
    timings['clustering'] = time.perf_counter() - t0
    entity_to_split_cid = {ei: cid for cid, c in enumerate(after_split) for ei in c}
    source_ids = [sorted({entity_to_split_cid[ei] for ei in room}) for room in merged]
    print(f'clustering: {timings["clustering"]:.2f}s  '
          f'base={len(base)} after_split={len(after_split)} final={len(merged)}')

    # stage_a (rubric, cached if file exists)
    _current_stage[0] = 'stage_a'
    t0 = time.perf_counter()
    rng = random.Random(sample_seed)
    sample = rng.sample(entities, min(sample_size, len(entities)))
    rubric_cache.parent.mkdir(parents=True, exist_ok=True)
    rubric = derive_rubric(domain, sample, client, model, cache_path=rubric_cache)
    timings['stage_a'] = time.perf_counter() - t0
    sa_calls = _usage_by_stage['stage_a']['calls']
    print(f'stage_a: {timings["stage_a"]:.2f}s  llm_calls={sa_calls} '
          f'({"cached" if sa_calls == 0 else "fresh"})')

    # stage_b x n (assign_rooms internally does n_runs + majority vote)
    _current_stage[0] = 'stage_b'
    t0 = time.perf_counter()
    rooms = assign_rooms(
        merged, entities, domain, rubric, n, node_budget, client, model,
        source_ids=source_ids,
    )
    timings['stage_b'] = time.perf_counter() - t0
    timings['stage_b_per_pass'] = timings['stage_b'] / max(n, 1)
    sb = _usage_by_stage['stage_b']
    print(f'stage_b: wall={timings["stage_b"]:.2f}s  call_sum={sb["call_seconds"]:.2f}s  '
          f'calls={sb["calls"]} (={len(merged)} rooms x {n} runs)')

    # aggregate (majority vote happens inside assign_rooms; reported separately = 0)
    timings['aggregate'] = 0.0  # folded into stage_b call

    # invariants
    check_invariants(rooms, len(entities), K, node_budget)

    # build spec (same schema as room_gen output) and write rooms.json
    _current_stage[0] = 'export'
    t0 = time.perf_counter()
    run_id = f'pipeline_K{K}_n{n}_embedding'
    spec = {
        'meta': {
            'run_id': run_id,
            'snapshot': snapshot,
            'K': K,
            'k_base': k_base,
            'max_cluster_size': max_cluster_size,
            'merge_strategy': 'embedding',
            'n_runs': n,
            'node_budget': node_budget,
            'domain': domain,
            'model': model,
            'ts': datetime.now(timezone.utc).isoformat(),
            'snapshot_meta': snap_meta,
            'pipeline': {
                'k_base_sizes': sorted([len(c) for c in base], reverse=True),
                'after_split_sizes': sorted([len(c) for c in after_split], reverse=True),
                'final_sizes': sorted([len(c) for c in merged], reverse=True),
            },
        },
        'rooms': rooms,
        'unassigned': [],
    }
    rooms_path = out_dir / 'rooms.json'
    rooms_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')

    # palace export — re-route export_palace at rooms.json location.
    # export_palace reads from results/rooms/<run_id>.json so stage rooms.json there
    # temporarily then move palace output. Easier: inline the same logic.
    palace = build_palace(spec, snapshot, snap_meta, model, run_id)
    palace_path = out_dir / 'palace.json'
    palace_path.write_text(json.dumps(palace, ensure_ascii=False, indent=2), encoding='utf-8')
    timings['export'] = time.perf_counter() - t0
    print(f'export: {timings["export"]:.2f}s  '
          f'rooms.json + palace.json (room_count={palace["palace"]["room_count"]})')

    return {
        'spec': spec,
        'palace': palace,
        'timings': timings,
        'usage': dict(_usage_by_stage),
        'pricing': pricing,
        'run_id': run_id,
        'n': n,
        'parallel': False,
    }


def build_palace(spec: dict, snapshot: str, snap_meta: dict, model: str, run_id: str) -> dict:
    """Reuse export_palace internals on the in-memory spec (no temp file)."""
    import pandas as pd
    ents = pd.read_parquet(Path(snapshot) / 'entities.parquet')
    ent_lookup = export_palace.build_ent_lookup(ents)
    title_to_pid = export_palace.assign_palace_ids(spec, ent_lookup)

    rooms_out: list[dict] = []
    for idx, room in enumerate(spec['rooms']):
        kept_list: list[dict] = []
        for rank, item in enumerate(room['kept'], start=1):
            pid = title_to_pid[item['title']]
            kept_list.append(export_palace.build_entity_record(item, ent_lookup, pid, with_rank=rank))
        demoted_list: list[dict] = []
        for item in room.get('demoted', []):
            pid = title_to_pid[item['title']]
            demoted_list.append(export_palace.build_entity_record(item, ent_lookup, pid, with_rank=None))
        rmeta = room.get('_meta') or {}
        rooms_out.append({
            'id': f'room_{room["room_id"]:02d}',
            'index': idx,
            'name': room['name'],
            'summary': rmeta.get('coherence_reason') or None,
            'kept_count': len(kept_list),
            'meta': {
                'coherence_flag': room.get('coherence_flag'),
                'source_cluster_count': len(room.get('source_clusters') or []),
            },
            'kept': kept_list,
            'demoted': demoted_list,
        })

    return {
        'palace': {
            'id': run_id,
            'title': f'기억의 궁전: {run_id}',
            'source': {
                'corpus': spec['meta']['domain'],
                'language': 'ko',
                'entity_count': int(snap_meta['n_entities']),
            },
            'room_count': len(rooms_out),
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'pipeline': {
                'snapshot': snapshot,
                'k': spec['meta']['K'],
                'merge': spec['meta']['merge_strategy'],
                'embedding_model': 'text-embedding-3-small',
                'llm_model': model,
                'node_budget': spec['meta']['node_budget'],
            },
        },
        'rooms': rooms_out,
    }


# ---------------------------------------------------------------------------
# Cost report + human report
# ---------------------------------------------------------------------------


def build_cost_report(result: dict, model: str) -> dict:
    timings, usage, pricing = result['timings'], result['usage'], result['pricing']

    stages = {}
    total_tokens = {'prompt': 0, 'completion': 0, 'calls': 0}
    total_cost: float | str = 0.0
    cost_pending = False

    stage_order = ['snapshot_load', 'clustering', 'stage_a', 'stage_b', 'aggregate', 'export']
    for s in stage_order:
        u = usage.get(s, {'prompt_tokens': 0, 'completion_tokens': 0, 'calls': 0, 'call_seconds': 0.0})
        wall = round(timings.get(s, 0.0), 3)
        entry: dict = {
            'wall_seconds': wall,
            'call_seconds': round(u.get('call_seconds', 0.0), 3),
            'llm_calls': u['calls'],
            'prompt_tokens': u['prompt_tokens'],
            'completion_tokens': u['completion_tokens'],
            'cost_usd': stage_cost(u, pricing) if u['calls'] > 0 else 0.0,
        }
        if s == 'stage_b':
            entry['per_pass_wall_seconds'] = round(timings.get('stage_b_per_pass', 0.0), 3)
            entry['parallel'] = result.get('parallel', False)
        if s in ('snapshot_load', 'clustering', 'aggregate', 'export'):
            entry['cost_usd'] = 0.0  # no LLM by construction
        stages[s] = entry
        total_tokens['prompt'] += u['prompt_tokens']
        total_tokens['completion'] += u['completion_tokens']
        total_tokens['calls'] += u['calls']
        c = entry['cost_usd']
        if c == 'pending':
            cost_pending = True
        elif isinstance(c, (int, float)):
            if not isinstance(total_cost, str):
                total_cost += c

    if cost_pending:
        total_cost = 'pending'
    else:
        total_cost = round(total_cost, 6)

    return {
        'meta': {
            'run_id': result['run_id'],
            'model': model,
            'n_runs': result['n'],
            'parallel_stage_b': result.get('parallel', False),
            'pricing': pricing,
            'generated_at': datetime.now(timezone.utc).isoformat(),
        },
        'stages': stages,
        'totals': {
            'wall_seconds': round(sum(timings.get(s, 0.0) for s in stage_order), 3),
            'llm_calls': total_tokens['calls'],
            'prompt_tokens': total_tokens['prompt'],
            'completion_tokens': total_tokens['completion'],
            'cost_usd': total_cost,
        },
    }


def build_report_md(cost: dict, result: dict) -> str:
    m = cost['meta']
    t = cost['totals']
    lines = [
        f'# Pipeline cost report: {m["run_id"]}',
        '',
        f'- model: `{m["model"]}` | n_runs: {m["n_runs"]} | parallel_stage_b: {m["parallel_stage_b"]}',
        f'- generated_at: {m["generated_at"]}',
        f'- pricing source: {m["pricing"].get("_source") or "n/a"}'
        + ('  (cost shown as "pending" because input_per_1m/output_per_1m unset)'
           if t['cost_usd'] == 'pending' else ''),
        '',
        '## Per-stage',
        '',
        '| stage | wall s | call_sum s | LLM calls | prompt tok | completion tok | cost $ |',
        '|---|---:|---:|---:|---:|---:|---:|',
    ]
    for s, e in cost['stages'].items():
        lines.append(
            f'| {s} | {e["wall_seconds"]} | {e["call_seconds"]} | '
            f'{e["llm_calls"]} | {e["prompt_tokens"]} | {e["completion_tokens"]} | '
            f'{e["cost_usd"]} |'
        )
    sb = cost['stages']['stage_b']
    lines.append('')
    lines.append(f'stage_b note: {result["n"]} passes serial; wall = sum of call durations '
                 f'({sb["call_seconds"]} s) since parallel={sb["parallel"]}. '
                 f'Per-pass wall {sb["per_pass_wall_seconds"]} s.')
    lines.append('')
    lines.append('## Totals')
    lines.append('')
    lines.append(f'- wall: **{t["wall_seconds"]} s**')
    lines.append(f'- LLM calls: **{t["llm_calls"]}** (prompt {t["prompt_tokens"]} + completion {t["completion_tokens"]} tokens)')
    lines.append(f'- cost: **${t["cost_usd"]}**')
    lines.append('')
    lines.append('## Pipeline settings (locked)')
    lines.append('')
    spec_meta = result['spec']['meta']
    lines.append(f'- snapshot: `{spec_meta["snapshot"]}`')
    lines.append(f'- K={spec_meta["K"]}, k_base={spec_meta["k_base"]}, '
                 f'max_cluster_size={spec_meta["max_cluster_size"]}, '
                 f'merge={spec_meta["merge_strategy"]}, n_runs={spec_meta["n_runs"]}, '
                 f'node_budget={spec_meta["node_budget"]}')
    lines.append(f'- domain: {spec_meta["domain"]}')
    lines.append('')
    lines.append('## Rooms summary')
    lines.append('')
    lines.append('| id | name | kept | demoted | coherence |')
    lines.append('|---|---|---:|---:|---|')
    for r in result['spec']['rooms']:
        lines.append(f'| {r["room_id"]} | {r["name"]} | {len(r["kept"])} | '
                     f'{len(r["demoted"])} | {r["coherence_flag"]} |')
    total = sum(len(r['kept']) + len(r['demoted']) for r in result['spec']['rooms'])
    snap_n = spec_meta['snapshot_meta']['n_entities']
    lines.append('')
    lines.append(f'total entities {total}/{snap_n} (전수보존 {"OK" if total == snap_n else "FAIL"})')
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(cost: dict, result: dict) -> list[str]:
    errors: list[str] = []
    required = ['snapshot_load', 'clustering', 'stage_a', 'stage_b', 'aggregate', 'export']
    for s in required:
        if s not in cost['stages']:
            errors.append(f'missing stage {s}')
    # LLM stages must have non-zero tokens (Stage A may be 0 if cached, but warn don't fail)
    sb = cost['stages']['stage_b']
    if sb['llm_calls'] == 0 or sb['prompt_tokens'] == 0:
        errors.append(f'stage_b token count is 0 (calls={sb["llm_calls"]} tokens={sb["prompt_tokens"]})')
    # Clustering and snapshot_load must be $0
    for s in ('snapshot_load', 'clustering', 'aggregate', 'export'):
        if cost['stages'][s]['cost_usd'] not in (0, 0.0):
            errors.append(f'{s} cost_usd should be 0, got {cost["stages"][s]["cost_usd"]}')
    # totals consistency
    t = cost['totals']
    sum_calls = sum(cost['stages'][s]['llm_calls'] for s in required)
    if t['llm_calls'] != sum_calls:
        errors.append(f'totals.llm_calls {t["llm_calls"]} != sum {sum_calls}')
    sum_prompt = sum(cost['stages'][s]['prompt_tokens'] for s in required)
    if t['prompt_tokens'] != sum_prompt:
        errors.append(f'totals.prompt_tokens {t["prompt_tokens"]} != sum {sum_prompt}')
    sum_compl = sum(cost['stages'][s]['completion_tokens'] for s in required)
    if t['completion_tokens'] != sum_compl:
        errors.append(f'totals.completion_tokens {t["completion_tokens"]} != sum {sum_compl}')
    # rooms/palace produced
    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--snapshot', default='results/snapshots/repro_run3')
    ap.add_argument('--K', type=int, default=10)
    ap.add_argument('--n', type=int, default=3)
    ap.add_argument('--node-budget', type=int, default=20)
    ap.add_argument('--k-base', type=int, default=12)
    ap.add_argument('--max-cluster-size', type=int, default=55)
    ap.add_argument('--domain', default='한국사')
    ap.add_argument('--model', default='gpt-4.1-mini')
    ap.add_argument('--out-dir', default='results/pipeline')
    ap.add_argument('--pricing', default='results/pipeline/pricing.json')
    ap.add_argument('--rubric-cache', default='results/pipeline/rubric.json')
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = run_pipeline(
        snapshot=args.snapshot, K=args.K, n=args.n, node_budget=args.node_budget,
        k_base=args.k_base, max_cluster_size=args.max_cluster_size,
        domain=args.domain, model=args.model, out_dir=out_dir,
        pricing_path=Path(args.pricing), rubric_cache=Path(args.rubric_cache),
    )

    cost = build_cost_report(result, args.model)
    (out_dir / 'cost_report.json').write_text(
        json.dumps(cost, ensure_ascii=False, indent=2), encoding='utf-8')
    (out_dir / 'report.md').write_text(build_report_md(cost, result), encoding='utf-8')

    errors = validate(cost, result)
    if errors:
        print('\nVALIDATION FAILED:')
        for e in errors:
            print(' -', e)
        return 1

    print(f'\nOK: wall={cost["totals"]["wall_seconds"]}s  '
          f'calls={cost["totals"]["llm_calls"]}  '
          f'tokens={cost["totals"]["prompt_tokens"]}+{cost["totals"]["completion_tokens"]}  '
          f'cost=${cost["totals"]["cost_usd"]}')
    print(f'wrote: {out_dir}/{{rooms,palace,cost_report}}.json + report.md')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
