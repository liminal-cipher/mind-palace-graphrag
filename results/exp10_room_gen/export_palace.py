"""rooms json을 3D팀 핸드오프용 .palace.json으로 변환. LLM 0회, 결정적.

방 배정·이름·keep/demote는 results/rooms/<run_id>.json에서 그대로 읽고,
type·description은 results/snapshots/<snap>/entities.parquet에서 title 조인.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd

sys.path.insert(0, str(Path('results/node_order_probe')))
from node_metrics import (  # noqa: E402
    _first_in_text,
    _surface_variants,
    build_text_unit_positions,
)

ROOMS = Path('results/rooms')

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
    # fall back: split on '. '
    for sep in ['다.', '.']:
        if text.endswith(sep):
            return text
    # take up to 200 chars if no sentence boundary
    return text[:200].strip()


def load_rooms(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def build_ent_lookup(ents: pd.DataFrame) -> dict[str, dict]:
    # title -> row dict
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
        entity's text_unit_ids that has a resolved char position in
        the corpus.
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
    """title -> ent_<norm> mapping. duplicate norm -> abort."""
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
                pid = f'ent_{normalize_title(title)}'
                if pid in pid_to_title and pid_to_title[pid] != title:
                    raise SystemExit(
                        f'normalized id collision: pid={pid} from titles '
                        f'{pid_to_title[pid]!r} and {title!r}'
                    )
                title_to_pid[title] = pid
                pid_to_title[pid] = title
    return title_to_pid


def build_entity_record(item: dict, ent_lookup: dict[str, dict], pid: str,
                        with_rank: int | None,
                        order: int | None = None,
                        order_confidence: str | None = None) -> dict:
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
        rec['rank'] = with_rank
    if order is not None:
        rec['order'] = order
        rec['order_confidence'] = order_confidence
    rec['caption'] = caption_of(info['description'])
    rec['description'] = info['description']
    return rec


def collect_relationships(rels: pd.DataFrame, kept_titles: set[str],
                          title_to_pid: dict[str, str]) -> list[dict]:
    out: list[dict] = []
    for _, r in rels.iterrows():
        s, t = r['source'], r['target']
        if s in kept_titles and t in kept_titles:
            out.append({
                'source': title_to_pid[s],
                'target': title_to_pid[t],
                'weight': float(r['weight']) if pd.notna(r['weight']) else None,
                'description': r['description'] if isinstance(r['description'], str) else '',
            })
    return out


def export(run_id: str, snapshot: Path, with_relationships: bool) -> tuple[Path, dict]:
    rooms_path = ROOMS / f'{run_id}.json'
    rooms_json = load_rooms(rooms_path)
    meta = rooms_json['meta']

    ents = pd.read_parquet(snapshot / 'entities.parquet')
    ent_lookup = build_ent_lookup(ents)
    title_to_pid = assign_palace_ids(rooms_json, ent_lookup)

    # Corpus text + text_unit char spans for first-occurrence ordering.
    # Both come from the same snapshot used to build the rooms: documents
    # carries the full corpus text, text_units carries the chunk
    # boundaries we use as the fallback position.
    docs_path = snapshot / 'documents.parquet'
    tu_path = snapshot / 'text_units.parquet'
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
    kept_titles_global: set[str] = set()
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
            kept_titles_global.add(item['title'])
        # Stable sort by order ASC; Python's sort is stable so same-order
        # entries keep the source rank order. Unresolved (order == -1)
        # would land at the front, but the snapshots we ship currently
        # have no zero-chunk entities, so this is only a safety net.
        kept_list.sort(key=lambda r: r['order'])
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
                'source_cluster_count': len(room.get('source_clusters') or []),
            },
            'kept': kept_list,
            'demoted': demoted_list,
        })

    palace = {
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

    if with_relationships:
        rels = pd.read_parquet(snapshot / 'relationships.parquet')
        palace['relationships'] = collect_relationships(rels, kept_titles_global, title_to_pid)

    suffix = '.palace.with_rels.json' if with_relationships else '.palace.json'
    out_path = ROOMS / f'{run_id}{suffix}'
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
    ap.add_argument('--run-id', default='repro_run3_K10_embedding')
    ap.add_argument('--snapshot', default='results/snapshots/repro_run3')
    ap.add_argument('--with-relationships', action='store_true')
    args = ap.parse_args()

    snapshot = Path(args.snapshot)
    out_path, stats = export(args.run_id, snapshot, args.with_relationships)
    print(f'wrote: {out_path}')

    rooms_json = load_rooms(ROOMS / f'{args.run_id}.json')
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

    # Sort check: every room's kept must be ASC by order.
    bad_sort = []
    for r in data['rooms']:
        ords = [k['order'] for k in r['kept']]
        if ords != sorted(ords):
            bad_sort.append(r['id'])
    sort_ok = not bad_sort

    n_resolved = stats['fine'] + stats['fallback'] - stats['unresolved']
    total_kept = stats['fine'] + stats['fallback']
    fine_ratio = stats['fine'] / total_kept if total_kept else 0.0
    fallback_ratio = stats['fallback'] / total_kept if total_kept else 0.0
    print(
        f'OK: room_count={data["palace"]["room_count"]} kept={n_kept} demoted={n_demoted}'
        + (f' relationships={len(data.get("relationships", []))}' if args.with_relationships else '')
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
