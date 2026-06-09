"""exp17 Phase B steps 5-9: build TOC arm + GRAPH arm + ordering + LLM
rubric + keep/demote + blind comparison artifacts.

Both arms produce 6 rooms over the same 119-entity snapshot. Room
membership is deterministic; entity_type is not used for clustering,
assignment, or ordering (per doctrine). LLM is only used for the
keep/demote rubric and per-room keep selection (Stage A + Stage B from
exp10), never for assigning an entity to a room.

TOC arm:
    occurrence(entity, section) = sum over u in entity.text_unit_ids of
        char_overlap(text_unit_u_span, section_span)
    dominant_section = argmax. Tiebreak: lower section idx (학습 흐름).
    This is exp15's occurrence path scaled to text-unit / section
    char-span overlaps (rather than per-unit indicator counts) because
    the corpus has only 5 text_units; indicator counts collapse to
    unit-dominant-section. char overlap restores section diversity.

GRAPH arm:
    room_gen.base_cluster(K=6). Run twice and assert clusters identical.

Ordering:
    Within each room: entities sorted by pos_first_fine ascending
    (fine_matched entities first, then text_unit char_start fallback).
    Room order: TOC = section idx; GRAPH = min(member position).

Rubric:
    derive_rubric(domain="통계학 기초 강의 자료", sample=60) one call.

Keep/demote:
    assign_rooms with NODE_BUDGET=10 per room. demote = room members not
    in keep_titles. No drops, no hidden splits.

Outputs (results/exp17_generalization/):
    toc_rooms.json, graph_rooms.json   (per-arm full spec)
    rubric.json                         (Stage A output, reused across arms)
    keep_demote.json                    (combined Stage B output, both arms)
    blind_compare.json, blind_key.json  (neutral set1/set2 view)
    metrics.json                        (size dist, coverage, reproducibility)
    rooms_ordered.md                    (human-readable)
"""
from __future__ import annotations

import io
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
SNAP = ROOT / 'snapshot'
TOC = ROOT / 'toc_llm.json'
CORPUS = REPO / 'input' / 'ai_gyoan' / 'AI_교안_정제.txt'

sys.path.insert(0, str(REPO / 'results' / 'node_order_probe'))
sys.path.insert(0, str(REPO / 'results' / 'exp10_room_gen'))
import node_metrics  # noqa: E402
from room_gen import (  # noqa: E402
    assign_rooms,
    base_cluster,
    derive_rubric,
    load_snapshot,
    make_azure_client,
)

K = 6
DOMAIN = '통계학 기초 강의 자료 (모집단·표본·확률 분포·가설 검정·상관분석)'
MODEL = 'gpt-4.1-mini'
NODE_BUDGET = 10
N_RUNS = 1
RUBRIC_CACHE = ROOT / 'rubric.json'
SET1_METHOD = 'toc'


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
            'corpus': str(CORPUS.relative_to(REPO)).replace('\\', '/'),
            'n_entities': len(entities),
            'n_rooms': len(rooms),
            'K': K,
            'deterministic': True,
            'llm_calls_for_assignment': 0,
        },
        'rooms': rooms,
    }
    return spec, assignments


def build_graph_rooms(entities: list[dict]) -> tuple[dict, bool]:
    clusters_a = base_cluster(entities, K)
    clusters_b = base_cluster(entities, K)
    def sig(cs):
        return sorted(tuple(sorted(c)) for c in cs)
    identical = sig(clusters_a) == sig(clusters_b)

    sorted_clusters = sorted(clusters_a, key=lambda c: (-len(c), min(c)))
    rooms = []
    for i, idx_list in enumerate(sorted_clusters):
        members = [
            {'id': entities[j]['id'], 'title': entities[j]['title']}
            for j in idx_list
        ]
        rooms.append({
            'room_id': f'graph_{i + 1}',
            'size': len(members),
            'entities': members,
        })

    spec = {
        'meta': {
            'method': 'graph_ward',
            'source': 'exp10 room_gen.base_cluster (L2-norm ward / euclidean)',
            'snapshot': str(SNAP.relative_to(REPO)).replace('\\', '/'),
            'embedding_source': 'exp17 snapshot lancedb entity_description',
            'n_entities': len(entities),
            'n_rooms': len(rooms),
            'K': K,
            'deterministic': True,
            'two_runs_identical': identical,
            'llm_calls_for_assignment': 0,
        },
        'rooms': rooms,
    }
    return spec, identical


def attach_positions(
    spec: dict,
    ent_metrics: list[dict],
    ent_df: pd.DataFrame,
    tu_df: pd.DataFrame,
    text: str,
) -> dict:
    """Sort members within each room by pos_first_fine ascending. Reorder
    rooms (graph arm only) by min(member position). TOC arm room order
    is the section order, untouched.
    """
    pos_by_title = {r['entity']: r for r in ent_metrics}
    positions = node_metrics.build_text_unit_positions(tu_df, text)
    title_to_uids = {
        str(r['title']): list(r['text_unit_ids']) if r['text_unit_ids'] is not None else []
        for _, r in ent_df.iterrows()
    }

    def member_pos(title: str) -> tuple[int, int]:
        """Return (pos, source_rank). source_rank=0 if fine_matched, 1 if
        text_unit char_start fallback, 2 if neither (sorted last)."""
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
        if r['entities']:
            r['_room_pos'] = r['entities'][0]['pos']
        else:
            r['_room_pos'] = 10**9

    if spec['meta']['method'] == 'graph_ward':
        spec['rooms'].sort(key=lambda r: (r['_room_pos'], r['room_id']))
        for i, r in enumerate(spec['rooms']):
            r['room_id'] = f'graph_{i + 1}'

    for r in spec['rooms']:
        r.pop('_room_pos', None)
    return spec


def apply_keep_demote(
    spec: dict,
    entities: list[dict],
    rubric: dict,
    client,
) -> dict:
    """Run Stage B per room. Inject demote and keep_titles into spec."""
    title_to_e = {e['title']: e for e in entities}
    final_clusters = []
    for r in spec['rooms']:
        idxs = [
            i for i, e in enumerate(entities)
            if e['title'] in {m['title'] for m in r['entities']}
        ]
        final_clusters.append(idxs)

    rooms_out = assign_rooms(
        final_clusters, entities, DOMAIN, rubric, N_RUNS, NODE_BUDGET,
        client, MODEL,
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
    spec['meta']['node_budget'] = NODE_BUDGET
    spec['meta']['rubric_source'] = str(RUBRIC_CACHE.relative_to(REPO)).replace('\\', '/')
    return spec


def build_blind(toc_spec: dict, graph_spec: dict) -> tuple[dict, dict]:
    set1 = toc_spec if SET1_METHOD == 'toc' else graph_spec
    set2 = graph_spec if SET1_METHOD == 'toc' else toc_spec

    def to_blind(spec, label):
        rooms_sorted = sorted(spec['rooms'], key=lambda r: r['room_id'])
        out, key = [], {}
        for i, r in enumerate(rooms_sorted, start=1):
            neutral = f'{label}_room{i}'
            kept = [e['title'] for e in r['entities'] if e.get('status') == 'kept']
            demoted = [e['title'] for e in r['entities'] if e.get('status') == 'demoted']
            out.append({
                'room_id': neutral,
                'size': len(r['entities']),
                'kept_count': len(kept),
                'demoted_count': len(demoted),
                'entities_kept': kept,
                'entities_demoted': demoted,
            })
            key[neutral] = {
                'method': spec['meta']['method'],
                'real_room_id': r['room_id'],
                'llm_room_name': r.get('_llm', {}).get('room_name', ''),
            }
            if 'section_idx' in r:
                key[neutral]['section_idx'] = r['section_idx']
                key[neutral]['section_name'] = r['section_name']
        return out, key

    set1_rooms, set1_key = to_blind(set1, 'set1')
    set2_rooms, set2_key = to_blind(set2, 'set2')
    blind = {
        'note': '각 set은 같은 119 엔티티를 6개 방으로 나눈 한 방식. 어느 set이 어떤 방식인지·라벨은 여기 없음. 평가 후 blind_key.json으로 공개.',
        'n_entities': sum(r['size'] for r in set1_rooms),
        'sets': {'set1': set1_rooms, 'set2': set2_rooms},
    }
    key = {
        'set1': {'method': set1['meta']['method'], 'rooms': set1_key},
        'set2': {'method': set2['meta']['method'], 'rooms': set2_key},
    }
    return blind, key


def compute_metrics(
    toc_spec: dict,
    graph_spec: dict,
    graph_identical: bool,
    n_entities: int,
) -> dict:
    def size_dist(spec):
        sizes = [r['size'] for r in spec['rooms']]
        return {
            'sizes': sizes,
            'min': min(sizes) if sizes else 0,
            'max': max(sizes) if sizes else 0,
            'mean': round(sum(sizes) / len(sizes), 2) if sizes else 0.0,
            'empty_rooms': sum(1 for s in sizes if s == 0),
        }

    def coverage(spec):
        seen = []
        for r in spec['rooms']:
            for e in r['entities']:
                seen.append(e.get('id') or e['title'])
        return {
            'covered': len(seen),
            'unique_covered': len(set(seen)),
            'all_entities_assigned': len(seen) == n_entities and len(set(seen)) == n_entities,
        }

    def keep_demote_dist(spec):
        kept = [r.get('kept_count', 0) for r in spec['rooms']]
        demoted = [r.get('demoted_count', 0) for r in spec['rooms']]
        return {
            'kept_per_room': kept,
            'demoted_per_room': demoted,
            'kept_total': sum(kept),
            'demoted_total': sum(demoted),
        }

    return {
        'n_entities': n_entities,
        'K': K,
        'size_distribution': {
            'toc': size_dist(toc_spec),
            'graph': size_dist(graph_spec),
        },
        'coverage': {
            'toc': coverage(toc_spec),
            'graph': coverage(graph_spec),
        },
        'keep_demote_distribution': {
            'toc': keep_demote_dist(toc_spec),
            'graph': keep_demote_dist(graph_spec),
        },
        'reproducibility': {
            'toc': {
                'deterministic': True,
                'note': 'char-overlap weighted occurrence + section-idx tiebreak.',
            },
            'graph': {
                'deterministic': True,
                'two_runs_identical': graph_identical,
                'note': 'ward linkage on L2-normalized embeddings, fcluster maxclust.',
            },
            'keep_demote': {
                'temp': 0,
                'n_runs': N_RUNS,
                'note': 'Azure gpt-4.1-mini temp=0; single-run keep order taken as-is. '
                        'Determinism caveat: API may show micro-variation across calls.',
            },
        },
    }


def render_markdown(toc_spec: dict, graph_spec: dict) -> str:
    lines = ['# exp17 rooms ordered (TOC arm + GRAPH arm)', '']
    for spec, title in [(toc_spec, 'TOC arm'), (graph_spec, 'GRAPH arm')]:
        lines.append(f'## {title} ({spec["meta"]["method"]})')
        lines.append('')
        for r in spec['rooms']:
            head = r['room_id']
            llm_name = r.get('_llm', {}).get('room_name', '')
            if 'section_name' in r:
                head += f' · {r["section_name"]}'
            if llm_name:
                head += f' · (LLM: {llm_name})'
            head += f' · size={r["size"]} kept={r.get("kept_count", "n/a")} demoted={r.get("demoted_count", "n/a")}'
            lines.append(f'### {head}')
            lines.append('')
            if not r['entities']:
                lines.append('(empty)')
                lines.append('')
                continue
            lines.append('| # | title | status | pos | pos_source |')
            lines.append('|---|---|---|---|---|')
            for i, e in enumerate(r['entities'], start=1):
                src = {0: 'fine', 1: 'unit', 2: 'none'}.get(e.get('pos_source', 2), '?')
                pos = e.get('pos', -1)
                pos_disp = pos if pos < 10**8 else '-'
                lines.append(
                    f'| {i} | {e["title"]} | {e.get("status", "?")} | {pos_disp} | {src} |'
                )
            lines.append('')
    return '\n'.join(lines)


def main() -> None:
    text = CORPUS.read_text(encoding='utf-8')
    ent_df = pd.read_parquet(SNAP / 'entities.parquet')
    tu_df = pd.read_parquet(SNAP / 'text_units.parquet')

    entities, snap_meta = load_snapshot(SNAP)
    n_ent = len(entities)
    print(f'entities loaded: {n_ent}')

    toc_payload = json.loads(TOC.read_text(encoding='utf-8'))
    sections = toc_payload['sections']
    print(f'sections: {len(sections)}')

    # entity metrics for pos_first_fine
    ent_metrics = node_metrics.compute_entity_metrics(ent_df, tu_df, text)

    print('building TOC arm...')
    toc_spec, _ = build_toc_rooms(entities, ent_df, tu_df, text, sections)
    print(f'  toc room sizes: {[r["size"] for r in toc_spec["rooms"]]}')

    print('building GRAPH arm...')
    graph_spec, identical = build_graph_rooms(entities)
    print(f'  graph room sizes: {[r["size"] for r in graph_spec["rooms"]]}')
    print(f'  graph two-run identical: {identical}')

    print('attaching positions and sorting...')
    toc_spec = attach_positions(toc_spec, ent_metrics, ent_df, tu_df, text)
    graph_spec = attach_positions(graph_spec, ent_metrics, ent_df, tu_df, text)

    print('deriving rubric (LLM Stage A)...')
    client = make_azure_client()
    # sample 60 entities for rubric. deterministic via sample_seed in
    # generate_rooms; here we use a deterministic head() slice on titles.
    sample_titles = sorted(e['title'] for e in entities)[:60]
    sample = [e for e in entities if e['title'] in set(sample_titles)]
    rubric = derive_rubric(
        DOMAIN, sample, client, MODEL, cache_path=RUBRIC_CACHE,
    )
    print(f'  rubric items: {len(rubric.get("rubric", []))}')

    print('applying keep/demote to TOC arm...')
    toc_spec = apply_keep_demote(toc_spec, entities, rubric, client)
    print('applying keep/demote to GRAPH arm...')
    graph_spec = apply_keep_demote(graph_spec, entities, rubric, client)

    print('writing artifacts...')
    blind, key = build_blind(toc_spec, graph_spec)
    metrics = compute_metrics(toc_spec, graph_spec, identical, n_ent)

    (ROOT / 'toc_rooms.json').write_text(
        json.dumps(toc_spec, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    (ROOT / 'graph_rooms.json').write_text(
        json.dumps(graph_spec, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    (ROOT / 'blind_compare.json').write_text(
        json.dumps(blind, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    (ROOT / 'blind_key.json').write_text(
        json.dumps(key, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    (ROOT / 'metrics.json').write_text(
        json.dumps({
            **json.loads((ROOT / 'metrics.json').read_text(encoding='utf-8')),
            'rooms_metrics': metrics,
            'rooms_metrics_ts': datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )

    # keep_demote.json: condensed per-room view across both arms
    keep_demote = {
        'toc': [
            {
                'room_id': r['room_id'],
                'section_name': r.get('section_name', ''),
                'llm_room_name': r.get('_llm', {}).get('room_name', ''),
                'coherence': r.get('_llm', {}).get('coherence_flag', ''),
                'kept': [e['title'] for e in r['entities'] if e.get('status') == 'kept'],
                'demoted': [e['title'] for e in r['entities'] if e.get('status') == 'demoted'],
            }
            for r in toc_spec['rooms']
        ],
        'graph': [
            {
                'room_id': r['room_id'],
                'llm_room_name': r.get('_llm', {}).get('room_name', ''),
                'coherence': r.get('_llm', {}).get('coherence_flag', ''),
                'kept': [e['title'] for e in r['entities'] if e.get('status') == 'kept'],
                'demoted': [e['title'] for e in r['entities'] if e.get('status') == 'demoted'],
            }
            for r in graph_spec['rooms']
        ],
    }
    (ROOT / 'keep_demote.json').write_text(
        json.dumps(keep_demote, ensure_ascii=False, indent=2), encoding='utf-8',
    )

    (ROOT / 'rooms_ordered.md').write_text(
        render_markdown(toc_spec, graph_spec), encoding='utf-8',
    )

    print()
    print('=== summary ===')
    print(f'TOC sizes: {[r["size"] for r in toc_spec["rooms"]]}')
    print(f'GRAPH sizes: {[r["size"] for r in graph_spec["rooms"]]}')
    print(f'graph identical (2 runs): {identical}')
    print('files: toc_rooms.json, graph_rooms.json, blind_compare.json, '
          'blind_key.json, metrics.json, keep_demote.json, rooms_ordered.md')


if __name__ == '__main__':
    main()
