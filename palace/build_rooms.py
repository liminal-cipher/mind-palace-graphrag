"""TOC-arm room builder.

Adapted from results/exp17_generalization/build.py, dropping the GRAPH
arm (build_graph_rooms) and the exp17 reporting (build_blind,
compute_metrics, render_markdown). All hardcoded module constants
(K, DOMAIN, MODEL, NODE_BUDGET, N_RUNS, RUBRIC_CACHE, CORPUS) are now
function arguments so the same code drives any corpus + run config.

Pipeline:
    build_toc_rooms        char-overlap weighted occurrence assignment
    attach_positions       sort members within each room by pos_first_fine
    apply_keep_demote      LLM Stage B per room (rubric in, keep/demote out)
    convert_toc_to_common_schema   adapt to the room_gen common spec
    absorb_empty_rooms     merge kept-empty rooms into a non-empty neighbor
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from palace import node_metrics
from palace.room_gen import assign_rooms


def char_overlap(span_a: tuple[int, int], span_b: tuple[int, int]) -> int:
    a0, a1 = span_a
    b0, b1 = span_b
    lo = max(a0, b0)
    hi = min(a1, b1)
    return max(0, hi - lo)


def build_toc_rooms(
    entities: list[dict],
    ent_df: pd.DataFrame,
    tu_df: pd.DataFrame,
    text: str,
    sections: list[dict],
    *,
    K: int,
    corpus_rel: str,
) -> tuple[dict, dict]:
    """Char-overlap weighted occurrence, deterministic argmax."""
    positions = node_metrics.build_text_unit_positions(tu_df, text)
    sec_spans = [(s['start_offset'], s['end_offset']) for s in sections]

    title_to_uids: dict[str, list] = {}
    for _, r in ent_df.iterrows():
        uids = list(r['text_unit_ids']) if r['text_unit_ids'] is not None else []
        title_to_uids[str(r['title'])] = uids

    assignments: dict[str, dict] = {}
    for e in entities:
        uids = title_to_uids.get(e['title'], [])
        weights = [0] * len(sec_spans)
        for uid in uids:
            cs, ce, _, _ = positions.get(uid, (-1, -1, -1, 0))
            if cs < 0:
                continue
            for si, sec_span in enumerate(sec_spans):
                weights[si] += char_overlap((cs, ce), sec_span)
        total = sum(weights)
        if total == 0:
            dom = 0
            ratio = 0.0
        else:
            best_w = max(weights)
            dom = next(i for i, w in enumerate(weights) if w == best_w)
            ratio = best_w / total
        assignments[e['title']] = {
            'dominant_section': dom,
            'weights': weights,
            'dominance_ratio': round(ratio, 4),
            'total_overlap': total,
        }

    by_section: dict[int, list[dict]] = defaultdict(list)
    for e in entities:
        a = assignments[e['title']]
        by_section[a['dominant_section']].append({
            'id': e['id'],
            'title': e['title'],
            'dominance_ratio': a['dominance_ratio'],
        })

    rooms = []
    for si, sec in enumerate(sections):
        members = by_section.get(si, [])
        rooms.append({
            'room_id': f'toc_{si + 1}',
            'section_idx': si,
            'section_name': sec['name'],
            'section_span': [sec['start_offset'], sec['end_offset']],
            'size': len(members),
            'entities': members,
        })

    spec = {
        'meta': {
            'method': 'toc',
            'source': 'char-overlap weighted occurrence (text_unit span ↔ section span)',
            'corpus': corpus_rel,
            'n_entities': len(entities),
            'n_rooms': len(rooms),
            'K': K,
            'deterministic': True,
            'llm_calls_for_assignment': 0,
        },
        'rooms': rooms,
    }
    return spec, assignments


def attach_positions(
    spec: dict,
    ent_metrics: list[dict],
    ent_df: pd.DataFrame,
    tu_df: pd.DataFrame,
    text: str,
) -> dict:
    """Sort members within each room by pos_first_fine ascending. TOC arm
    room order is the section order, untouched.
    """
    pos_by_title = {r['entity']: r for r in ent_metrics}
    positions = node_metrics.build_text_unit_positions(tu_df, text)
    title_to_uids = {
        str(r['title']): list(r['text_unit_ids']) if r['text_unit_ids'] is not None else []
        for _, r in ent_df.iterrows()
    }

    def member_pos(title: str) -> tuple[int, int]:
        m = pos_by_title.get(title)
        if m is not None and m.get('fine_matched'):
            return m['pos_first_fine'], 0
        uids = title_to_uids.get(title, [])
        starts = [positions.get(uid, (-1, -1, -1, 0))[0] for uid in uids]
        starts = [s for s in starts if s >= 0]
        if starts:
            return min(starts), 1
        return 10**9, 2

    for r in spec['rooms']:
        members_pos = [
            (member_pos(e['title']), e) for e in r['entities']
        ]
        members_pos.sort(key=lambda x: (x[0][0], x[0][1], x[1]['title']))
        r['entities'] = [
            {**e, 'pos': p[0], 'pos_source': p[1]}
            for (p, e) in members_pos
        ]

    return spec


def apply_keep_demote(
    spec: dict,
    entities: list[dict],
    rubric: dict,
    client,
    *,
    domain: str,
    model: str,
    node_budget: int,
    n_runs: int,
    rubric_source_rel: str,
    stage_b_cache_dir: str | Path | None = None,
) -> dict:
    """Run Stage B per room. Inject demote and keep_titles into spec."""
    final_clusters = []
    for r in spec['rooms']:
        idxs = [
            i for i, e in enumerate(entities)
            if e['title'] in {m['title'] for m in r['entities']}
        ]
        final_clusters.append(idxs)

    rooms_out = assign_rooms(
        final_clusters, entities, domain, rubric, n_runs, node_budget,
        client, model,
        stage_b_cache_dir=stage_b_cache_dir,
    )

    enriched = []
    for r_in, r_out in zip(spec['rooms'], rooms_out):
        kept_titles = [k['title'] for k in r_out['kept']]
        demoted_titles = {d['title'] for d in r_out['demoted']}
        new_entities = []
        for e in r_in['entities']:
            ke = dict(e)
            if e['title'] in demoted_titles:
                ke['status'] = 'demoted'
            else:
                ke['status'] = 'kept'
            new_entities.append(ke)
        enriched.append({
            **r_in,
            'entities': new_entities,
            'kept_titles': kept_titles,
            'demoted_count': len(demoted_titles),
            'kept_count': len(kept_titles),
            '_llm': {
                'room_name': r_out['name'],
                'coherence_flag': r_out['coherence_flag'],
                'coherence_reason': r_out.get('_meta', {}).get('coherence_reason', ''),
                'n_hallucinated': r_out.get('_meta', {}).get('n_hallucinated', 0),
            },
        })
    spec['rooms'] = enriched
    spec['meta']['node_budget'] = node_budget
    spec['meta']['rubric_source'] = rubric_source_rel
    return spec


def convert_toc_to_common_schema(
    toc_spec: dict,
    *,
    run_id: str,
    domain: str,
    snapshot_rel: str,
    model: str,
    node_budget: int,
    n_entities: int,
    n_runs: int,
    k: int,
) -> dict:
    """Translate the TOC arm spec into the room_gen common schema that
    export_palace.py consumes.
    """
    rooms_out: list[dict] = []
    for i, r in enumerate(toc_spec['rooms']):
        llm = r.get('_llm', {}) or {}
        kept_titles = [
            e['title'] for e in r.get('entities', [])
            if e.get('status') == 'kept'
        ]
        demoted_titles = [
            e['title'] for e in r.get('entities', [])
            if e.get('status') == 'demoted'
        ]
        room_meta = {
            'coherence_reason': llm.get('coherence_reason', ''),
            'n_forced_demote': 0,
            'n_hallucinated': llm.get('n_hallucinated', 0),
            'section_idx': r.get('section_idx'),
            'section_name': r.get('section_name'),
            'section_span': r.get('section_span'),
        }
        rooms_out.append({
            'room_id': i,
            'name': llm.get('room_name', '') or '(unnamed)',
            'kept': [{'title': t} for t in kept_titles],
            'demoted': [{'title': t} for t in demoted_titles],
            'coherence_flag': llm.get('coherence_flag', 'unknown'),
            'source_clusters': [],
            '_meta': room_meta,
        })

    return {
        'meta': {
            'run_id': run_id,
            'snapshot': snapshot_rel,
            'K': k,
            'k_base': k,
            'max_cluster_size': None,
            'merge_strategy': 'toc',
            'n_runs': n_runs,
            'node_budget': node_budget,
            'domain': domain,
            'model': model,
            'ts': datetime.now(timezone.utc).isoformat(),
            'snapshot_meta': {
                'snapshot_path': snapshot_rel,
                'n_entities': n_entities,
            },
            'pipeline': None,
            'toc_source': toc_spec.get('meta', {}).get('source'),
        },
        'rooms': rooms_out,
        'unassigned': [],
    }


def absorb_empty_rooms(rooms_json: dict) -> dict:
    """Merge kept-empty rooms into a non-empty neighbor (next section first,
    fall back to previous). Deterministic and order-preserving.
    """
    rooms = list(rooms_json.get('rooms', []))
    if not rooms:
        return rooms_json
    empty_indices = [i for i, r in enumerate(rooms) if not r.get('kept')]
    non_empty = [i for i, r in enumerate(rooms) if r.get('kept')]
    if not empty_indices or not non_empty:
        return rooms_json

    for i in empty_indices:
        successors = [j for j in non_empty if j > i]
        if successors:
            target = min(successors)
        else:
            target = max(j for j in non_empty if j < i)
        src = rooms[i]
        dst = rooms[target]
        dst.setdefault('demoted', []).extend(src.get('demoted', []))
        meta = dst.setdefault('_meta', {})
        absorbed = meta.setdefault('absorbed_from', [])
        absorbed.append({
            'section_idx': src.get('_meta', {}).get('section_idx'),
            'section_name': src.get('_meta', {}).get('section_name'),
            'demoted_count': len(src.get('demoted', [])),
        })

    rooms_kept = [rooms[i] for i in non_empty]
    for new_id, r in enumerate(rooms_kept):
        r['room_id'] = new_id
    rooms_json['rooms'] = rooms_kept
    return rooms_json
