"""rooms json -> .palace.json. LLM 0회, 결정적.

Adapted from results/exp10_room_gen/export_palace.py. The original keyed
the rooms directory off `Path('results/rooms')` (CWD-relative) and did
a sys.path hack to import node_metrics; both are removed here. The
rooms directory is passed in as an argument so palace can write to its
own output tree without colliding with results/rooms.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from palace.node_metrics import (
    _first_in_text,
    _surface_variants,
    build_text_unit_positions,
)


_norm_re = re.compile(r'[\s\W]+', re.UNICODE)


def normalize_title(title: str) -> str:
    s = _norm_re.sub('_', title.strip()).strip('_').lower()
    return s or 'unnamed'


def caption_of(description: str) -> str:
    if not isinstance(description, str) or not description:
        return ''
    text = description.strip()
    for sep in ['다. ', '다.\n', '. ', '.\n']:
        idx = text.find(sep)
        if idx > 0:
            return text[:idx + (2 if sep.startswith('다') else 1)].strip()
    for sep in ['다.', '.']:
        if text.endswith(sep):
            return text
    return text[:200].strip()


def load_rooms(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def build_ent_lookup(ents: pd.DataFrame) -> dict[str, dict]:
    out: dict[str, dict] = {}
    dups: list[str] = []
    for _, row in ents.iterrows():
        t = row['title']
        if t in out:
            dups.append(t)
            continue
        tuids = row['text_unit_ids']
        out[t] = {
            'type': row['type'] if isinstance(row['type'], str) else '',
            'description': row['description'] if isinstance(row['description'], str) else '',
            'text_unit_ids': list(tuids) if tuids is not None else [],
        }
    if dups:
        raise SystemExit(f'duplicate titles in entities.parquet: {dups[:10]}')
    return out


def compute_position(
    title: str,
    text_unit_ids: list,
    corpus_text: str,
    text_unit_positions: dict,
) -> tuple[int, str]:
    """Return (order, order_confidence) for a kept entity.

    "fine": first-occurrence char offset of any surface variant of the
        title found in the corpus.
    "fallback": char_start of the first text_unit listed in the
        entity's text_unit_ids that has a resolved char position.
    """
    variants = _surface_variants(title)
    pos = _first_in_text(corpus_text, variants)
    if pos >= 0:
        return pos, 'fine'
    for uid in text_unit_ids:
        cs, _ce, _hr, _ln = text_unit_positions.get(uid, (-1, -1, -1, 0))
        if cs >= 0:
            return cs, 'fallback'
    return -1, 'fallback'


def assign_palace_ids(rooms_json: dict, ent_lookup: dict[str, dict]) -> dict[str, str]:
    title_to_pid: dict[str, str] = {}
    pid_to_title: dict[str, str] = {}
    seen_titles: set[str] = set()
    for room in rooms_json['rooms']:
        for bucket in ('kept', 'demoted'):
            for item in room.get(bucket, []):
                title = item['title']
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                base_pid = f'ent_{normalize_title(title)}'
                # Distinct titles can normalize to the same id (예: 괄호 앞
                # 공백 하나가 '_'로 접히는 '지수 분포 (...)' vs '지수 분포(...)').
                # 죽이는 대신 숫자 접미로 분리해 각 title을 별 노드로 유지한다.
                # 첫 title이 base_pid를 차지하고 이후 충돌자만 _2, _3을 받으므로
                # 충돌이 없는 코퍼스의 id는 그대로다.
                pid = base_pid
                suffix = 2
                while pid in pid_to_title and pid_to_title[pid] != title:
                    pid = f'{base_pid}_{suffix}'
                    suffix += 1
                title_to_pid[title] = pid
                pid_to_title[pid] = title
    return title_to_pid


def build_entity_record(
    item: dict,
    ent_lookup: dict[str, dict],
    pid: str,
    with_rank: int | None,
    order: int | None = None,
    order_confidence: str | None = None,
) -> dict:
    title = item['title']
    info = ent_lookup.get(title)
    if info is None:
        raise KeyError(title)
    rec: dict = {
        'id': pid,
        'title': title,
        'type': info['type'],
    }
    if with_rank is not None:
        rec['sequence'] = with_rank
    if order is not None:
        rec['source_offset'] = order
        rec['offset_confidence'] = order_confidence
    rec['summary'] = caption_of(info['description'])
    rec['description'] = info['description']
    return rec


def collect_intra_room_relationships(
    rels: pd.DataFrame,
    rooms_out: list[dict],
    title_to_pid: dict[str, str],
) -> tuple[list[dict], dict[str, list[str]]]:
    """Return (edges, related_by_pid) for edges whose both endpoints are kept
    in the SAME room.

    edges: list of {source, target, weight, description}, one per qualifying
        parquet row, in parquet order. source/target are palace ids (pid).
    related_by_pid: pid -> list of other pids in the same room sharing an
        edge with it (undirected). Ordered by each entity's position in
        its room's kept list for stable 3D layout.
    """
    pid_to_room: dict[str, int] = {}
    for ridx, room in enumerate(rooms_out):
        for ent in room['kept']:
            pid_to_room[ent['id']] = ridx

    edges: list[dict] = []
    related_sets: dict[str, set[str]] = {pid: set() for pid in pid_to_room}

    for _, r in rels.iterrows():
        s_pid = title_to_pid.get(r['source'])
        t_pid = title_to_pid.get(r['target'])
        if s_pid is None or t_pid is None:
            continue
        s_room = pid_to_room.get(s_pid)
        t_room = pid_to_room.get(t_pid)
        if s_room is None or t_room is None:
            continue
        if s_room != t_room:
            continue
        edges.append({
            'source': s_pid,
            'target': t_pid,
            'weight': float(r['weight']) if pd.notna(r['weight']) else None,
            'description': r['description'] if isinstance(r['description'], str) else '',
        })
        related_sets[s_pid].add(t_pid)
        related_sets[t_pid].add(s_pid)

    related_by_pid: dict[str, list[str]] = {}
    for room in rooms_out:
        kept_order = {ent['id']: i for i, ent in enumerate(room['kept'])}
        for ent in room['kept']:
            related_by_pid[ent['id']] = sorted(
                related_sets.get(ent['id'], ()),
                key=lambda p: kept_order.get(p, len(kept_order)),
            )

    return edges, related_by_pid


def export(
    run_id: str,
    snapshot: Path,
    rooms_dir: Path,
) -> tuple[Path, dict]:
    rooms_dir = Path(rooms_dir)
    rooms_path = rooms_dir / f'{run_id}.json'
    rooms_json = load_rooms(rooms_path)
    meta = rooms_json['meta']

    ents = pd.read_parquet(Path(snapshot) / 'entities.parquet')
    ent_lookup = build_ent_lookup(ents)
    title_to_pid = assign_palace_ids(rooms_json, ent_lookup)

    docs_path = Path(snapshot) / 'documents.parquet'
    tu_path = Path(snapshot) / 'text_units.parquet'
    if not docs_path.exists() or not tu_path.exists():
        missing = [p.name for p in (docs_path, tu_path) if not p.exists()]
        raise SystemExit(f'STOP: snapshot missing required files for ordering: {missing}')
    docs = pd.read_parquet(docs_path)
    if len(docs) != 1:
        raise SystemExit(
            f'STOP: documents.parquet has {len(docs)} rows; multi-doc corpora '
            f'not handled by this ordering path'
        )
    corpus_text = docs.iloc[0]['text']
    if not isinstance(corpus_text, str) or not corpus_text:
        raise SystemExit('STOP: documents.parquet text column missing or empty')
    tu_df = pd.read_parquet(tu_path)
    text_unit_positions = build_text_unit_positions(tu_df, corpus_text)

    stats = {'fine': 0, 'fallback': 0, 'unresolved': 0}

    rooms_out: list[dict] = []
    for idx, room in enumerate(rooms_json['rooms']):
        kept_list: list[dict] = []
        for rank, item in enumerate(room['kept'], start=1):
            pid = title_to_pid[item['title']]
            info = ent_lookup.get(item['title'])
            tuids = info['text_unit_ids'] if info else []
            order, confidence = compute_position(
                item['title'], tuids, corpus_text, text_unit_positions,
            )
            if order < 0:
                stats['unresolved'] += 1
            stats[confidence] += 1
            kept_list.append(build_entity_record(
                item, ent_lookup, pid, with_rank=rank,
                order=order, order_confidence=confidence,
            ))
        kept_list.sort(key=lambda r: r['source_offset'])
        demoted_list: list[dict] = []
        for item in room.get('demoted', []):
            pid = title_to_pid[item['title']]
            demoted_list.append(build_entity_record(item, ent_lookup, pid, with_rank=None))
        rmeta = room.get('_meta') or {}
        rooms_out.append({
            'id': f'room_{room["room_id"]:02d}',
            'index': idx,
            'name': room['name'],
            'summary': rmeta.get('coherence_reason') or None,
            'kept_count': len(kept_list),
            'meta': {
                'coherence_flag': room.get('coherence_flag'),
            },
            'kept': kept_list,
            'demoted': demoted_list,
        })

    palace = {
        'schema_version': '1.1',
        'schema_changelog': (
            '1.0->1.1: images[] 추가 + rank->sequence, order->source_offset, '
            'order_confidence->offset_confidence, caption->summary, '
            'source_cluster_count 삭제'
        ),
        'palace': {
            'id': run_id,
            'title': f'기억의 궁전: {run_id}',
            'source': {
                'corpus': meta.get('domain') or 'unknown',
                'language': 'ko',
                'entity_count': int(meta.get('snapshot_meta', {}).get('n_entities')
                                    or len(ents)),
            },
            'room_count': len(rooms_out),
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'pipeline': {
                'snapshot': meta.get('snapshot'),
                'k': meta.get('K'),
                'merge': meta.get('merge_strategy'),
                'embedding_model': 'text-embedding-3-small',
                'llm_model': meta.get('model'),
                'node_budget': meta.get('node_budget'),
            },
        },
        'rooms': rooms_out,
    }

    rels = pd.read_parquet(Path(snapshot) / 'relationships.parquet')
    edges, related_by_pid = collect_intra_room_relationships(
        rels, rooms_out, title_to_pid,
    )
    for room in rooms_out:
        for ent in room['kept']:
            ent['related'] = related_by_pid.get(ent['id'], [])
    palace['relationships'] = edges

    out_path = rooms_dir / f'{run_id}.palace.json'
    out_path.write_text(
        json.dumps(palace, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return out_path, stats


def validate(out_path: Path, rooms_json: dict, ent_lookup: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    data = json.loads(out_path.read_text(encoding='utf-8'))
    if 'palace' not in data:
        errors.append('missing top-level palace')
    p = data.get('palace', {})
    for k in ('id', 'room_count'):
        if k not in p:
            errors.append(f'palace.{k} missing')
    rooms = data.get('rooms', [])
    if p.get('room_count') != len(rooms):
        errors.append(f'room_count {p.get("room_count")} != len(rooms) {len(rooms)}')

    src_rooms = rooms_json['rooms']
    if len(rooms) != len(src_rooms):
        errors.append(f'rooms length mismatch: {len(rooms)} vs source {len(src_rooms)}')
    for i, (r_out, r_src) in enumerate(zip(rooms, src_rooms)):
        for k in ('id', 'name', 'kept'):
            if k not in r_out:
                errors.append(f'rooms[{i}].{k} missing')
        if r_out.get('kept_count') != len(r_out.get('kept', [])):
            errors.append(f'rooms[{i}].kept_count != len(kept)')
        if len(r_out.get('kept', [])) != len(r_src['kept']):
            errors.append(f'rooms[{i}] kept length differs from source')
        for e in r_out.get('kept', []) + r_out.get('demoted', []):
            for k in ('id', 'title', 'type', 'description'):
                if k not in e:
                    errors.append(f'rooms[{i}] entity missing {k}: {e.get("title")}')
            if e['title'] not in ent_lookup:
                errors.append(f'rooms[{i}] entity title not in entities.parquet: {e["title"]}')
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-id', required=True)
    ap.add_argument('--snapshot', required=True)
    ap.add_argument('--rooms-dir', required=True)
    args = ap.parse_args()

    snapshot = Path(args.snapshot)
    rooms_dir = Path(args.rooms_dir)
    out_path, stats = export(args.run_id, snapshot, rooms_dir)
    print(f'wrote: {out_path}')

    rooms_json = load_rooms(rooms_dir / f'{args.run_id}.json')
    ents = pd.read_parquet(snapshot / 'entities.parquet')
    ent_lookup = build_ent_lookup(ents)
    errors = validate(out_path, rooms_json, ent_lookup)
    if errors:
        print('VALIDATION FAILED:')
        for e in errors:
            print(' -', e)
        return 1
    data = json.loads(out_path.read_text(encoding='utf-8'))
    n_kept = sum(r['kept_count'] for r in data['rooms'])
    n_demoted = sum(len(r['demoted']) for r in data['rooms'])

    bad_sort = []
    for r in data['rooms']:
        ords = [k['source_offset'] for k in r['kept']]
        if ords != sorted(ords):
            bad_sort.append(r['id'])
    sort_ok = not bad_sort

    total_kept = stats['fine'] + stats['fallback']
    fine_ratio = stats['fine'] / total_kept if total_kept else 0.0
    fallback_ratio = stats['fallback'] / total_kept if total_kept else 0.0
    print(
        f'OK: room_count={data["palace"]["room_count"]} kept={n_kept} demoted={n_demoted}'
        f' relationships={len(data.get("relationships", []))}'
    )
    print(
        f'order: fine={stats["fine"]} ({fine_ratio:.2%}) '
        f'fallback={stats["fallback"]} ({fallback_ratio:.2%}) '
        f'unresolved={stats["unresolved"]} | kept ASC by order: '
        f'{"yes" if sort_ok else "NO " + ",".join(bad_sort)}'
    )
    return 0 if sort_ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
