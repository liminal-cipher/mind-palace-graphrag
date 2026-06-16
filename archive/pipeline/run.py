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


# Capture individual Stage B pass results per room. assign_rooms calls
# _run_stage_b_once n_runs times per room and then aggregates; without this
# wrapper the per-pass keep sets are discarded.
_per_room_passes: dict[int, list[dict]] = defaultdict(list)
_orig_stage_b = room_gen._run_stage_b_once


def _instrumented_stage_b(cid, *args, **kw):
    result = _orig_stage_b(cid, *args, **kw)
    _per_room_passes[cid].append({
        'room_name': result['room_name'],
        'coherence': result['coherence'],
        'keep_order': list(result['keep_order']),
        'keep_set': set(result['keep_order']),
        'demote_set': set(result['demote_set']),
        'n_hallucinated': result.get('n_hallucinated', 0),
    })
    return result


room_gen._run_stage_b_once = _instrumented_stage_b


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
# Per-pass agreement + majority effect
# ---------------------------------------------------------------------------


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 1.0


def analyze_passes(
    merged: list[list[int]],
    entities: list[dict],
    final_rooms: list[dict],
    n: int,
    node_budget: int,
) -> dict:
    """For each room: pair-wise jaccard on keep sets, split entities (not
    unanimous across passes), majority verification, and the count of
    entities the majority vote actually changed vs unanimous.
    """
    per_room: list[dict] = []
    total_split = 0
    total_majority_changed = 0
    total_entities = 0
    jacc_means: list[float] = []
    jacc_mins: list[float] = []
    impl_mismatches: list[str] = []

    for room_id, cluster_idx in enumerate(merged):
        passes = _per_room_passes.get(room_id, [])
        input_set = {entities[i]['title'] for i in cluster_idx}
        total_entities += len(input_set)

        keep_sets = [p['keep_set'] for p in passes]

        # pair-wise jaccard
        pair_j: list[float] = []
        for i in range(len(keep_sets)):
            for j in range(i + 1, len(keep_sets)):
                pair_j.append(_jaccard(keep_sets[i], keep_sets[j]))
        mean_j = sum(pair_j) / len(pair_j) if pair_j else 1.0
        min_j = min(pair_j) if pair_j else 1.0
        jacc_means.append(mean_j)
        jacc_mins.append(min_j)

        # per-title vote tally
        votes = {t: 0 for t in input_set}
        for ks in keep_sets:
            for t in ks:
                if t in votes:
                    votes[t] += 1

        # split = not unanimous (some passes keep, some demote)
        split_titles = [t for t, v in votes.items() if 0 < v < n]
        total_split += len(split_titles)

        # majority effect: titles where majority decision differs from
        # the unanimous-keep set (=titles unanimous_keep would NOT include
        # but majority does, plus vice versa). Since 3-vote unanimous keep
        # = {t : v==3} and majority keep = {t : v>=2}, the differ set is
        # exactly {t : v==2} (majority keeps, unanimous-only would demote).
        # Plus, demote unanimous = {t : v==0}; majority demote = {t : v<2};
        # differ on demote side = {t : v==1} (majority demotes, unanimous-demote
        # would not). Both together = {t : v==1 or v==2} = split_titles.
        # So majority_changed_count == split_titles_count when within budget.

        # Implementation verification: actual kept_set from final_rooms[room_id]
        actual_kept = {k['title'] for k in final_rooms[room_id]['kept']}
        threshold = n / 2.0
        expected_majority = {t for t, v in votes.items() if v > threshold}
        if len(expected_majority) <= node_budget:
            if actual_kept != expected_majority:
                impl_mismatches.append(
                    f'room {room_id}: actual_kept {sorted(actual_kept)[:5]}... '
                    f'!= expected_majority {sorted(expected_majority)[:5]}...'
                )
        else:
            if not actual_kept.issubset(expected_majority):
                impl_mismatches.append(
                    f'room {room_id}: actual_kept not subset of expected_majority'
                )
            if len(actual_kept) != node_budget:
                impl_mismatches.append(
                    f'room {room_id}: budget cap expected len={node_budget}, '
                    f'got {len(actual_kept)}'
                )

        majority_changed = len(split_titles)  # within-budget case; see comment above
        if len(expected_majority) > node_budget:
            # over budget: majority "did" the cut as well; count titles in
            # expected_majority that didn't make actual_kept as additional changes.
            cut = expected_majority - actual_kept
            majority_changed += len(cut)
        total_majority_changed += majority_changed

        # name agreement across passes
        names = [p['room_name'] for p in passes]
        name_unanimous = len(set(names)) == 1

        per_room.append({
            'room_id': room_id,
            'cluster_size': len(input_set),
            'n_passes': len(passes),
            'keep_sizes_per_pass': [len(ks) for ks in keep_sets],
            'mean_pair_jaccard': round(mean_j, 4),
            'min_pair_jaccard': round(min_j, 4),
            'split_titles_count': len(split_titles),
            'split_titles': sorted(split_titles)[:20],  # cap for readability
            'majority_changed_vs_unanimous': majority_changed,
            'pass_names': names,
            'name_unanimous': name_unanimous,
        })

    agg = {
        'overall_mean_pair_jaccard': round(sum(jacc_means) / len(jacc_means), 4)
                                     if jacc_means else 1.0,
        'overall_min_pair_jaccard': round(min(jacc_mins), 4) if jacc_mins else 1.0,
        'total_split_titles': total_split,
        'total_entities': total_entities,
        'split_fraction': round(total_split / total_entities, 4) if total_entities else 0.0,
        'majority_changed_count': total_majority_changed,
        'majority_no_op': total_majority_changed == 0,
        'implementation_mismatches': impl_mismatches,
        'spec': 'keep iff votes > n/2 (= >= ceil((n+1)/2)); for n=3 means >= 2/3.',
    }
    return {'per_room': per_room, 'aggregate': agg}


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

    # n-pass agreement + majority effect (per-room then aggregated)
    agreement = analyze_passes(merged, entities, rooms, n, node_budget)

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
        'agreement': agreement,
        'concurrency': {
            'mode': 'serial',
            'rooms': 'sequential for-loop in room_gen.assign_rooms',
            'passes_per_room': 'sequential list comprehension over n_runs',
            'evidence': 'stage_b wall_seconds ≈ call_seconds; no thread/async pool used',
        },
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
            'concurrency': result.get('concurrency', {}),
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
        'stage_b_agreement': result.get('agreement', {}),
    }


def build_report_md(cost: dict, result: dict) -> str:
    m = cost['meta']
    t = cost['totals']
    pending_note = (
        ' (input_per_1m/output_per_1m 미설정이라 cost는 "pending" 표기)'
        if t['cost_usd'] == 'pending' else ''
    )
    lines = [
        f'# 파이프라인 비용 리포트: {m["run_id"]}',
        '',
        f'- model: `{m["model"]}` | n_runs: {m["n_runs"]} | parallel_stage_b: {m["parallel_stage_b"]}',
        f'- generated_at: {m["generated_at"]}',
        f'- 가격 출처: {m["pricing"].get("_source") or "n/a"}{pending_note}',
        '',
        '## 단계별',
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
    lines.append(
        f'stage_b 메모: {result["n"]} pass serial 실행; parallel={sb["parallel"]}이므로 '
        f'wall = call duration 합 ({sb["call_seconds"]} s). '
        f'pass별 wall {sb["per_pass_wall_seconds"]} s.'
    )
    lines.append('')
    lines.append('## 합계')
    lines.append('')
    lines.append(f'- wall: **{t["wall_seconds"]} s**')
    lines.append(f'- LLM calls: **{t["llm_calls"]}** (prompt {t["prompt_tokens"]} + completion {t["completion_tokens"]} tok)')
    lines.append(f'- cost: **${t["cost_usd"]}**')
    lines.append('')
    lines.append('## 파이프라인 설정 (고정)')
    lines.append('')
    spec_meta = result['spec']['meta']
    lines.append(f'- snapshot: `{spec_meta["snapshot"]}`')
    lines.append(f'- K={spec_meta["K"]}, k_base={spec_meta["k_base"]}, '
                 f'max_cluster_size={spec_meta["max_cluster_size"]}, '
                 f'merge={spec_meta["merge_strategy"]}, n_runs={spec_meta["n_runs"]}, '
                 f'node_budget={spec_meta["node_budget"]}')
    lines.append(f'- domain: {spec_meta["domain"]}')
    lines.append('')
    lines.append('## 방 요약')
    lines.append('')
    lines.append('| id | 이름 | 유지 | 강등 | 정합성 |')
    lines.append('|---|---|---:|---:|---|')
    for r in result['spec']['rooms']:
        lines.append(f'| {r["room_id"]} | {r["name"]} | {len(r["kept"])} | '
                     f'{len(r["demoted"])} | {r["coherence_flag"]} |')
    total = sum(len(r['kept']) + len(r['demoted']) for r in result['spec']['rooms'])
    snap_n = spec_meta['snapshot_meta']['n_entities']
    lines.append('')
    lines.append(f'총 엔티티 {total}/{snap_n} (전수보존 {"OK" if total == snap_n else "FAIL"})')

    # 동시성
    conc = m.get('concurrency') or {}
    lines.append('')
    lines.append('## 동시성')
    lines.append('')
    lines.append(f'- mode: **{conc.get("mode")}**')
    lines.append(f'- rooms: {conc.get("rooms")}')
    lines.append(f'- passes_per_room: {conc.get("passes_per_room")}')
    lines.append(f'- evidence: {conc.get("evidence")}')

    # Stage B n-pass 일치도 + 다수결 효과
    agr = cost.get('stage_b_agreement', {})
    agg = agr.get('aggregate', {})
    per_room = agr.get('per_room', [])
    lines.append('')
    lines.append('## Stage B n-pass 일치도')
    lines.append('')
    lines.append(f'- spec: {agg.get("spec")}')
    lines.append(f'- 전체 평균 pair-jaccard: **{agg.get("overall_mean_pair_jaccard")}**')
    lines.append(f'- 전체 최소 pair-jaccard: **{agg.get("overall_min_pair_jaccard")}**')
    lines.append(f'- split 엔티티 (pass 간 불일치): '
                 f'**{agg.get("total_split_titles")}/{agg.get("total_entities")}** '
                 f'({agg.get("split_fraction")})')
    lines.append('')
    lines.append('## 다수결 효과')
    lines.append('')
    lines.append(f'- 다수결(2/3)이 만장일치 대비 바꾼 엔티티: '
                 f'**{agg.get("majority_changed_count")}**')
    if agg.get('majority_no_op'):
        lines.append('- **mode-lock**: 모든 엔티티에 3 pass 만장일치, 다수결은 no-op.')
    else:
        lines.append('- 다수결이 실제로 분류에 관여 (일부 엔티티가 pass 간 불일치).')
    mismatches = agg.get('implementation_mismatches') or []
    if mismatches:
        lines.append('- **구현 불일치:**')
        for m_ in mismatches:
            lines.append(f'  - {m_}')
    else:
        lines.append('- 구현 확인: 실제 keep set이 다수결 spec(>= 2/3)과 일치 (node_budget 한도 내).')
    lines.append('')
    lines.append('### 방별')
    lines.append('')
    lines.append('| room | size | pass별 keep 크기 | mean jacc | min jacc | split | maj 변경 | 이름 일치 |')
    lines.append('|---|---:|---|---:|---:|---:|---:|---|')
    for pr in per_room:
        lines.append(
            f'| {pr["room_id"]} | {pr["cluster_size"]} | {pr["keep_sizes_per_pass"]} | '
            f'{pr["mean_pair_jaccard"]} | {pr["min_pair_jaccard"]} | '
            f'{pr["split_titles_count"]} | {pr["majority_changed_vs_unanimous"]} | '
            f'{"예" if pr["name_unanimous"] else "아니오"} |'
        )
    return '\n'.join(lines) + '\n'


def render_from_disk(out_dir: Path) -> int:
    """Re-render report.md from existing cost_report.json + rooms.json (no LLM)."""
    cost_path = out_dir / 'cost_report.json'
    rooms_path = out_dir / 'rooms.json'
    if not cost_path.exists() or not rooms_path.exists():
        print(f'render-only: 산출물 누락 ({cost_path}, {rooms_path}) — 먼저 파이프라인 실행 필요')
        return 1
    cost = json.loads(cost_path.read_text(encoding='utf-8'))
    spec = json.loads(rooms_path.read_text(encoding='utf-8'))
    result = {'spec': spec, 'n': cost['meta']['n_runs']}
    (out_dir / 'report.md').write_text(build_report_md(cost, result), encoding='utf-8')
    print(f'render-only: report.md 재생성 완료 (LLM 0회, cost_report.json + rooms.json 기반)')
    return 0


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
    # New required fields: concurrency + stage_b_agreement
    if not cost['meta'].get('concurrency', {}).get('mode'):
        errors.append('cost_report.meta.concurrency.mode missing')
    agr = cost.get('stage_b_agreement') or {}
    if not agr:
        errors.append('cost_report.stage_b_agreement missing')
    else:
        agg = agr.get('aggregate') or {}
        for k in ('overall_mean_pair_jaccard', 'overall_min_pair_jaccard',
                  'total_split_titles', 'majority_changed_count', 'majority_no_op'):
            if k not in agg:
                errors.append(f'stage_b_agreement.aggregate.{k} missing')
        per_room = agr.get('per_room') or []
        if result['n'] > 1 and len(per_room) != len(result['spec']['rooms']):
            errors.append(f'stage_b_agreement.per_room length {len(per_room)} '
                          f'!= rooms {len(result["spec"]["rooms"])}')
        if result['n'] > 1:
            for pr in per_room:
                if pr.get('n_passes') != result['n']:
                    errors.append(f'room {pr.get("room_id")}: n_passes {pr.get("n_passes")} != {result["n"]}')
        if agg.get('implementation_mismatches'):
            for m_ in agg['implementation_mismatches']:
                errors.append(f'majority impl mismatch: {m_}')
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
    ap.add_argument('--render-only', action='store_true',
                    help='재실행 없이 cost_report.json + rooms.json에서 report.md만 재생성 (LLM 0회)')
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.render_only:
        return render_from_disk(out_dir)

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
