"""exp16 head-to-head room compare: TOC (exp15 B) vs graph (exp10 ward).

Same corpus (repro_run3, 357 entities), same number of rooms (6), same JSON
shape on both arms. Both arms are deterministic, no LLM calls.

TOC rooms: reuse exp15 partition B chapter assignments (dominant_chapter_B).
Graph rooms: rerun exp10 base_cluster with K=6 on the same 357 embeddings.

Outputs (under results/exp16_room_compare/):
    toc_rooms.json
    graph_rooms.json
    metrics.json
    blind_compare.json
    blind_key.json
"""
from __future__ import annotations

import csv
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'results' / 'exp10_room_gen'))

from room_gen import base_cluster, load_snapshot  # noqa: E402

SNAPSHOT = REPO / 'results' / 'snapshots' / 'repro_run3'
EXP15_CSV = REPO / 'results' / 'exp15_toc_chapters' / 'entity_chapter_assignments.csv'
EXP15_DEF = REPO / 'results' / 'exp15_toc_chapters' / 'chapter_definition.json'
ANCHORS = REPO / 'results' / 'exp10_room_gen' / 'anchors_korean_history.json'
OUT_DIR = REPO / 'results' / 'exp16_room_compare'

K = 6
SET1_METHOD = 'toc'  # blind set1 fixed = TOC, set2 = graph (key file only)


def load_anchors():
    obj = json.loads(ANCHORS.read_text(encoding='utf-8'))
    aliases = obj.get('aliases', {})
    show = [aliases.get(t, t) for t in obj['should_show']]
    demote = [aliases.get(t, t) for t in obj['should_demote']]
    return show, demote, aliases


def build_toc_rooms(entities):
    """Read exp15 entity_chapter_assignments.csv, keyed by entity title.
    Each of the 357 entities has a dominant_chapter_B; rooms are the 6 chapters.
    """
    title_to_chapter = {}
    with EXP15_CSV.open(encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            title_to_chapter[row['entity']] = row['dominant_chapter_B']

    cdef = json.loads(EXP15_DEF.read_text(encoding='utf-8'))
    b_chapters = cdef['partition_B']['chapters']
    chapter_ids = [c['id'] for c in b_chapters]
    order = {cid: i for i, cid in enumerate(chapter_ids)}

    by_chapter = defaultdict(list)
    missing = []
    for e in entities:
        ch = title_to_chapter.get(e['title'])
        if ch is None:
            missing.append(e['title'])
            continue
        by_chapter[ch].append({'id': e['id'], 'title': e['title']})

    rooms = []
    for cid in chapter_ids:
        members = sorted(by_chapter[cid], key=lambda x: x['title'])
        rooms.append({
            'room_id': f'toc_{order[cid] + 1}',
            'chapter_id': cid,
            'chapter_title': next(
                c['section_titles'][0] for c in b_chapters if c['id'] == cid
            ),
            'size': len(members),
            'entities': members,
        })

    spec = {
        'meta': {
            'method': 'toc',
            'source': 'exp15 partition B (dominant_chapter_B)',
            'snapshot': str(SNAPSHOT.relative_to(REPO)).replace('\\', '/'),
            'n_entities': len(entities),
            'n_rooms': len(rooms),
            'deterministic': True,
            'llm_calls': 0,
            'missing_entities': missing,
        },
        'rooms': rooms,
    }
    return spec


def build_graph_rooms(entities):
    """exp10 base_cluster with K=6. Deterministic. Run twice to verify."""
    clusters_a = base_cluster(entities, K)
    clusters_b = base_cluster(entities, K)

    def clusters_signature(cs):
        sigs = sorted(tuple(sorted(c)) for c in cs)
        return sigs

    identical = clusters_signature(clusters_a) == clusters_signature(clusters_b)

    rooms = []
    sorted_clusters = sorted(clusters_a, key=lambda c: (-len(c), min(c)))
    for i, idx_list in enumerate(sorted_clusters):
        members = sorted(
            ({'id': entities[i]['id'], 'title': entities[i]['title']}
             for i in idx_list),
            key=lambda x: x['title'],
        )
        rooms.append({
            'room_id': f'graph_{i + 1}',
            'size': len(members),
            'entities': members,
        })

    spec = {
        'meta': {
            'method': 'graph_ward',
            'source': 'exp10 room_gen.base_cluster (L2-norm ward / euclidean)',
            'snapshot': str(SNAPSHOT.relative_to(REPO)).replace('\\', '/'),
            'embedding_source': 'repro_run3 lancedb entity_description (reused, same as exp10)',
            'n_entities': len(entities),
            'n_rooms': len(rooms),
            'K': K,
            'deterministic': True,
            'two_runs_identical': identical,
            'llm_calls': 0,
        },
        'rooms': rooms,
    }
    return spec, identical


def compute_metrics(toc_spec, graph_spec, anchors_show, anchors_demote, graph_identical):
    title_to_toc = {}
    for r in toc_spec['rooms']:
        for e in r['entities']:
            title_to_toc[e['title']] = r['room_id']
    title_to_graph = {}
    for r in graph_spec['rooms']:
        for e in r['entities']:
            title_to_graph[e['title']] = r['room_id']

    def coverage(title_to_room, labels):
        present = [t for t in labels if t in title_to_room]
        missing = [t for t in labels if t not in title_to_room]
        rooms_used = Counter(title_to_room[t] for t in present)
        return {
            'n_total': len(labels),
            'n_present': len(present),
            'n_missing': len(missing),
            'missing_titles': missing,
            'rooms_used_count': len(rooms_used),
            'distribution': dict(sorted(rooms_used.items())),
            'per_anchor': {t: title_to_room.get(t) for t in labels},
        }

    groups = {
        '건국': ['이성계', '정도전'],
        '전쟁': ['이순신', '권율', '곽재우', '김시민', '임진왜란', '거북선'],
        '15세기_과학': ['측우기', '자격루', '앙부일구', '혼천의', '인지의'],
    }

    def cohabit(title_to_room, group):
        rooms = {}
        for t in group:
            r = title_to_room.get(t)
            rooms[t] = r
        present_rooms = [r for r in rooms.values() if r is not None]
        unique = sorted(set(present_rooms))
        return {
            'members': group,
            'rooms_per_member': rooms,
            'all_same_room': len(unique) == 1 and len(present_rooms) == len(group),
            'unique_rooms': unique,
            'n_unique_rooms': len(unique),
        }

    metrics = {
        'n_entities': sum(r['size'] for r in toc_spec['rooms']),
        'n_rooms_toc': len(toc_spec['rooms']),
        'n_rooms_graph': len(graph_spec['rooms']),
        'anchor_coverage': {
            'should_show': {
                'toc': coverage(title_to_toc, anchors_show),
                'graph': coverage(title_to_graph, anchors_show),
            },
            'should_demote': {
                'toc': coverage(title_to_toc, anchors_demote),
                'graph': coverage(title_to_graph, anchors_demote),
            },
        },
        'anchor_cohabitation': {
            name: {
                'toc': cohabit(title_to_toc, group),
                'graph': cohabit(title_to_graph, group),
            }
            for name, group in groups.items()
        },
        'reproducibility': {
            'toc': {
                'deterministic': True,
                'note': 'exp15 partition B assignments reused, identical by construction.',
            },
            'graph': {
                'deterministic': True,
                'two_runs_identical': graph_identical,
                'note': 'ward linkage on L2-normalized embeddings, fcluster maxclust. No randomness.',
            },
        },
    }
    return metrics


def build_blind(toc_spec, graph_spec):
    set1 = toc_spec if SET1_METHOD == 'toc' else graph_spec
    set2 = graph_spec if SET1_METHOD == 'toc' else toc_spec

    def to_blind(spec, label):
        rooms_sorted = sorted(spec['rooms'], key=lambda r: r['room_id'])
        out = []
        key_map = {}
        for i, r in enumerate(rooms_sorted, start=1):
            neutral = f'{label}_room{i}'
            out.append({
                'room_id': neutral,
                'size': r['size'],
                'entities': [e['title'] for e in r['entities']],
            })
            key_map[neutral] = {
                'method': spec['meta']['method'],
                'real_room_id': r['room_id'],
            }
            if 'chapter_id' in r:
                key_map[neutral]['chapter_id'] = r['chapter_id']
                key_map[neutral]['chapter_title'] = r['chapter_title']
        return out, key_map

    set1_rooms, set1_key = to_blind(set1, 'set1')
    set2_rooms, set2_key = to_blind(set2, 'set2')

    blind = {
        'note': '각 set은 같은 357 엔티티를 6개 방으로 나눈 한 가지 방식. 어느 쪽이 어떤 방식인지·라벨은 여기 없음. 평가 후 blind_key.json으로 공개.',
        'n_entities': sum(r['size'] for r in set1_rooms),
        'sets': {
            'set1': set1_rooms,
            'set2': set2_rooms,
        },
    }
    key = {
        'set1': {'method': set1['meta']['method'], 'rooms': set1_key},
        'set2': {'method': set2['meta']['method'], 'rooms': set2_key},
    }
    return blind, key


def main():
    entities, snap_meta = load_snapshot(SNAPSHOT)
    print(f'loaded snapshot: {snap_meta}')

    toc_spec = build_toc_rooms(entities)
    print(f'toc rooms: {[(r["room_id"], r["size"]) for r in toc_spec["rooms"]]}')
    if toc_spec['meta']['missing_entities']:
        print(f'WARN: toc missing entities = {toc_spec["meta"]["missing_entities"]}')

    graph_spec, identical = build_graph_rooms(entities)
    print(f'graph rooms: {[(r["room_id"], r["size"]) for r in graph_spec["rooms"]]}')
    print(f'graph two-run identical: {identical}')

    anchors_show, anchors_demote, _ = load_anchors()
    metrics = compute_metrics(
        toc_spec, graph_spec, anchors_show, anchors_demote, identical,
    )

    blind, key = build_blind(toc_spec, graph_spec)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / 'toc_rooms.json').write_text(
        json.dumps(toc_spec, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    (OUT_DIR / 'graph_rooms.json').write_text(
        json.dumps(graph_spec, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    (OUT_DIR / 'metrics.json').write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    (OUT_DIR / 'blind_compare.json').write_text(
        json.dumps(blind, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    (OUT_DIR / 'blind_key.json').write_text(
        json.dumps(key, ensure_ascii=False, indent=2), encoding='utf-8',
    )

    print('\n=== anchor cohabitation summary ===')
    for name, both in metrics['anchor_cohabitation'].items():
        print(f'  {name}: toc same_room={both["toc"]["all_same_room"]} '
              f'unique_rooms={both["toc"]["unique_rooms"]} | '
              f'graph same_room={both["graph"]["all_same_room"]} '
              f'unique_rooms={both["graph"]["unique_rooms"]}')

    print('\n=== should_show coverage ===')
    for arm in ('toc', 'graph'):
        c = metrics['anchor_coverage']['should_show'][arm]
        print(f'  {arm}: {c["n_present"]}/{c["n_total"]} present, '
              f'{c["rooms_used_count"]} rooms touched, dist={c["distribution"]}')

    print('\ndone. files in results/exp16_room_compare/')


if __name__ == '__main__':
    main()
