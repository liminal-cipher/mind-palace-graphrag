"""Room spec evaluator. Domain-agnostic by construction: anchors are loaded
from an external JSON, not embedded in code. Swap the anchors file when
moving to another domain.

Anchor file schema:
    {
        "domain": "한국사",
        "should_show":   ["측우기", "이순신", ...],
        "should_demote": ["조선", "백성", ...],
        "aliases":       {"붕당정치": "붕당 정치"}   // optional
    }

Run:
    python eval_rooms.py --spec results/rooms/<run_id>.json \\
                         --anchors results/exp10_room_gen/anchors_korean_history.json
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load_anchors(path: str) -> dict:
    obj = json.loads(Path(path).read_text(encoding='utf-8'))
    obj.setdefault('aliases', {})
    obj.setdefault('should_show', [])
    obj.setdefault('should_demote', [])
    return obj


def index_spec(spec: dict) -> dict:
    """Build title -> {room_id, room_name, classification} index over a spec."""
    out: dict[str, dict] = {}
    for room in spec['rooms']:
        for m in room['kept']:
            out[m['title']] = {
                'room_id': room['room_id'],
                'room_name': room['name'],
                'classification': 'keep',
            }
        for m in room['demoted']:
            out[m['title']] = {
                'room_id': room['room_id'],
                'room_name': room['name'],
                'classification': 'demote',
            }
    return out


def evaluate(spec: dict, anchors: dict) -> dict:
    idx = index_spec(spec)
    aliases = anchors.get('aliases', {})

    def lookup(name: str):
        actual = aliases.get(name, name)
        return idx.get(actual)

    show_rows = []
    show_hits = 0
    for name in anchors['should_show']:
        rec = lookup(name)
        if rec is None:
            show_rows.append({'name': name, 'status': 'missing'})
        else:
            ok = rec['classification'] == 'keep'
            if ok:
                show_hits += 1
            show_rows.append({
                'name': name,
                'status': 'present',
                'classification': rec['classification'],
                'room_id': rec['room_id'],
                'room_name': rec['room_name'],
                'correct': ok,
            })

    demote_rows = []
    demote_hits = 0
    for name in anchors['should_demote']:
        rec = lookup(name)
        if rec is None:
            demote_rows.append({'name': name, 'status': 'missing'})
        else:
            ok = rec['classification'] == 'demote'
            if ok:
                demote_hits += 1
            demote_rows.append({
                'name': name,
                'status': 'present',
                'classification': rec['classification'],
                'room_id': rec['room_id'],
                'room_name': rec['room_name'],
                'correct': ok,
            })

    coh_counter: Counter[str] = Counter(r['coherence_flag'] for r in spec['rooms'])
    forced_total = sum(
        r.get('_meta', {}).get('n_forced_demote', 0) for r in spec['rooms']
    )

    total_entities = sum(
        len(r['kept']) + len(r['demoted']) for r in spec['rooms']
    )

    return {
        'spec_run_id': spec['meta'].get('run_id'),
        'anchors_domain': anchors.get('domain'),
        'completeness': {
            'total_entities': total_entities,
            'snapshot_entities': spec['meta']['snapshot_meta']['n_entities'],
            'ok': total_entities == spec['meta']['snapshot_meta']['n_entities'],
            'forced_demote': forced_total,
        },
        'should_show': {
            'hits': show_hits,
            'total': len(anchors['should_show']),
            'rows': show_rows,
        },
        'should_demote': {
            'hits': demote_hits,
            'total': len(anchors['should_demote']),
            'rows': demote_rows,
        },
        'coherence_flags': dict(coh_counter),
    }


def print_report(ev: dict) -> None:
    print(f'\n=== eval: {ev["spec_run_id"]} (domain={ev["anchors_domain"]}) ===')
    c = ev['completeness']
    print(f'completeness: {c["total_entities"]}/{c["snapshot_entities"]} '
          f'({"OK" if c["ok"] else "FAIL"})  forced_demote={c["forced_demote"]}')
    print(f'coherence flags: {ev["coherence_flags"]}')
    s = ev['should_show']
    print(f'\nshould_show: {s["hits"]}/{s["total"]}')
    print(f'{"name":<14} {"status":<10} {"class":<8} room')
    for r in s['rows']:
        if r['status'] == 'missing':
            print(f'  {r["name"]:<14} missing')
        else:
            mark = 'OK' if r['correct'] else 'X'
            print(f'  {r["name"]:<14} {mark:<8} {r["classification"]:<8} '
                  f'{r["room_id"]} {r["room_name"]}')
    d = ev['should_demote']
    print(f'\nshould_demote: {d["hits"]}/{d["total"]}')
    for r in d['rows']:
        if r['status'] == 'missing':
            print(f'  {r["name"]:<14} missing')
        else:
            mark = 'OK' if r['correct'] else 'X'
            print(f'  {r["name"]:<14} {mark:<8} {r["classification"]:<8} '
                  f'{r["room_id"]} {r["room_name"]}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--spec', required=True, help='path to room spec JSON')
    parser.add_argument('--anchors', required=True, help='path to anchor checklist JSON')
    parser.add_argument('--out', help='output eval JSON path (default: <spec>.eval.json)')
    args = parser.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding='utf-8'))
    anchors = load_anchors(args.anchors)
    ev = evaluate(spec, anchors)

    out = Path(args.out) if args.out else Path(args.spec).with_suffix('.eval.json')
    out.write_text(json.dumps(ev, ensure_ascii=False, indent=2), encoding='utf-8')

    print_report(ev)
    print(f'\nwrote {out}')


if __name__ == '__main__':
    main()
