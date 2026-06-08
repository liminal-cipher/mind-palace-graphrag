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
        out[t] = {
            'type': row['type'] if isinstance(row['type'], str) else '',
            'description': row['description'] if isinstance(row['description'], str) else '',
        }
    if dups:
        raise SystemExit(f'duplicate titles in entities.parquet: {dups[:10]}')
    return out


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
                        with_rank: int | None) -> dict:
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


def export(run_id: str, snapshot: Path, with_relationships: bool) -> Path:
    rooms_path = ROOMS / f'{run_id}.json'
    rooms_json = load_rooms(rooms_path)
    meta = rooms_json['meta']

    ents = pd.read_parquet(snapshot / 'entities.parquet')
    ent_lookup = build_ent_lookup(ents)
    title_to_pid = assign_palace_ids(rooms_json, ent_lookup)

    rooms_out: list[dict] = []
    kept_titles_global: set[str] = set()
    for idx, room in enumerate(rooms_json['rooms']):
        kept_list: list[dict] = []
        for rank, item in enumerate(room['kept'], start=1):
            pid = title_to_pid[item['title']]
            kept_list.append(build_entity_record(item, ent_lookup, pid, with_rank=rank))
            kept_titles_global.add(item['title'])
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
    return out_path


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
    out_path = export(args.run_id, snapshot, args.with_relationships)
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
    print(f'OK: room_count={data["palace"]["room_count"]} kept={n_kept} demoted={n_demoted}'
          + (f' relationships={len(data.get("relationships", []))}' if args.with_relationships else ''))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
