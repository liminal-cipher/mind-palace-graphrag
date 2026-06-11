"""Compare a palace run against the golden snapshot.

Usage:
    python palace/tests/compare_golden.py --run-id korean_history \
        [--runs-dir palace/tests/runs/korean_history] \
        [--golden-dir palace/tests/golden]

Returns exit code 0 on full match, 1 on mismatch. Mismatches printed as
(file, room_id, field, golden, palace) rows.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding='utf-8'))


def _row(rows: list[dict], file: str, room: str, field: str, golden, palace) -> None:
    rows.append({'file': file, 'room': room, 'field': field,
                 'golden': golden, 'palace': palace})


def compare_toc_llm(golden: dict, palace: dict, rows: list[dict]) -> None:
    """Compare sections deep-equal except meta.ts, meta.usage."""
    file = 'toc_llm.json'
    gm, pm = golden['meta'], palace['meta']
    for k in ('corpus', 'corpus_chars', 'model', 'temperature', 'n_sections',
              'monotonic_offsets', 'distinct_offsets'):
        if gm.get(k) != pm.get(k):
            _row(rows, file, '-', f'meta.{k}', gm.get(k), pm.get(k))
    if len(golden['sections']) != len(palace['sections']):
        _row(rows, file, '-', 'n_sections', len(golden['sections']), len(palace['sections']))
        return
    section_fields = ('idx', 'name', 'start_marker', 'start_offset',
                      'end_offset', 'length_chars', 'match_strategy',
                      'marker_occurrences_in_corpus')
    for i, (gs, ps) in enumerate(zip(golden['sections'], palace['sections'])):
        for k in section_fields:
            if gs.get(k) != ps.get(k):
                _row(rows, file, f'section[{i}]', k, gs.get(k), ps.get(k))


def compare_rooms(golden: dict, palace: dict, rows: list[dict]) -> None:
    """Compare rooms.json. meta.ts excluded. kept order matters; demoted as set."""
    file = 'rooms.json'
    gm, pm = golden['meta'], palace['meta']
    for k in ('run_id', 'snapshot', 'K', 'k_base', 'merge_strategy',
              'n_runs', 'node_budget', 'domain', 'model', 'toc_source'):
        if gm.get(k) != pm.get(k):
            _row(rows, file, '-', f'meta.{k}', gm.get(k), pm.get(k))
    gsm = gm.get('snapshot_meta') or {}
    psm = pm.get('snapshot_meta') or {}
    for k in ('snapshot_path', 'n_entities'):
        if gsm.get(k) != psm.get(k):
            _row(rows, file, '-', f'meta.snapshot_meta.{k}', gsm.get(k), psm.get(k))

    if len(golden['rooms']) != len(palace['rooms']):
        _row(rows, file, '-', 'n_rooms', len(golden['rooms']), len(palace['rooms']))
        return
    for i, (gr, pr) in enumerate(zip(golden['rooms'], palace['rooms'])):
        rid = f'room_{i}'
        for k in ('room_id', 'name', 'coherence_flag'):
            if gr.get(k) != pr.get(k):
                _row(rows, file, rid, k, gr.get(k), pr.get(k))
        g_kept = [k['title'] for k in gr.get('kept', [])]
        p_kept = [k['title'] for k in pr.get('kept', [])]
        if g_kept != p_kept:
            _row(rows, file, rid, 'kept_titles_in_order', g_kept, p_kept)
        g_dem = sorted(d['title'] for d in gr.get('demoted', []))
        p_dem = sorted(d['title'] for d in pr.get('demoted', []))
        if g_dem != p_dem:
            _row(rows, file, rid, 'demoted_titles_set',
                 f'len={len(g_dem)}, only_in_golden={sorted(set(g_dem)-set(p_dem))[:5]}',
                 f'len={len(p_dem)}, only_in_palace={sorted(set(p_dem)-set(g_dem))[:5]}')
        g_meta = gr.get('_meta') or {}
        p_meta = pr.get('_meta') or {}
        for k in ('section_idx', 'section_name', 'section_span'):
            if g_meta.get(k) != p_meta.get(k):
                _row(rows, file, rid, f'_meta.{k}', g_meta.get(k), p_meta.get(k))


def compare_palace(golden: dict, palace: dict, rows: list[dict]) -> None:
    """Compare palace.json. generated_at excluded."""
    file = 'palace.json'
    gp, pp = golden['palace'], palace['palace']
    for k in ('id', 'title', 'room_count'):
        if gp.get(k) != pp.get(k):
            _row(rows, file, '-', f'palace.{k}', gp.get(k), pp.get(k))
    gs, ps = gp.get('source') or {}, pp.get('source') or {}
    for k in ('corpus', 'language', 'entity_count'):
        if gs.get(k) != ps.get(k):
            _row(rows, file, '-', f'palace.source.{k}', gs.get(k), ps.get(k))
    gpipe, ppipe = gp.get('pipeline') or {}, pp.get('pipeline') or {}
    for k in ('snapshot', 'k', 'merge', 'embedding_model', 'llm_model', 'node_budget'):
        if gpipe.get(k) != ppipe.get(k):
            _row(rows, file, '-', f'palace.pipeline.{k}', gpipe.get(k), ppipe.get(k))

    if len(golden['rooms']) != len(palace['rooms']):
        _row(rows, file, '-', 'n_rooms', len(golden['rooms']), len(palace['rooms']))
        return
    for i, (gr, pr) in enumerate(zip(golden['rooms'], palace['rooms'])):
        rid = gr.get('id', f'idx={i}')
        for k in ('id', 'index', 'name', 'kept_count'):
            if gr.get(k) != pr.get(k):
                _row(rows, file, rid, k, gr.get(k), pr.get(k))
        gk, pk = gr.get('kept') or [], pr.get('kept') or []
        if len(gk) != len(pk):
            _row(rows, file, rid, 'kept_len', len(gk), len(pk))
        else:
            for j, (gke, pke) in enumerate(zip(gk, pk)):
                for f in ('id', 'title', 'source_offset', 'offset_confidence', 'sequence'):
                    if gke.get(f) != pke.get(f):
                        _row(rows, file, rid, f'kept[{j}].{f}',
                             gke.get(f), pke.get(f))
        g_dem_ids = sorted(d.get('id') for d in (gr.get('demoted') or []))
        p_dem_ids = sorted(d.get('id') for d in (pr.get('demoted') or []))
        if g_dem_ids != p_dem_ids:
            only_g = sorted(set(g_dem_ids) - set(p_dem_ids))[:5]
            only_p = sorted(set(p_dem_ids) - set(g_dem_ids))[:5]
            _row(rows, file, rid, 'demoted_ids_set',
                 f'len={len(g_dem_ids)}, only_in_golden={only_g}',
                 f'len={len(p_dem_ids)}, only_in_palace={only_p}')


def format_diff(rows: list[dict]) -> str:
    if not rows:
        return ''
    lines = []
    lines.append(f'{"file":<16}  {"room":<14}  {"field":<32}  golden  →  palace')
    lines.append('-' * 100)
    for r in rows:
        g = repr(r['golden'])
        p = repr(r['palace'])
        if len(g) > 120:
            g = g[:117] + '...'
        if len(p) > 120:
            p = p[:117] + '...'
        lines.append(f'{r["file"]:<16}  {str(r["room"]):<14}  {r["field"]:<32}  {g}  →  {p}')
    return '\n'.join(lines)


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-id', required=True)
    ap.add_argument('--runs-dir', default=None,
                    help='palace run output dir (default: palace/tests/runs/<run-id>)')
    ap.add_argument('--golden-dir', default='palace/tests/golden')
    args = ap.parse_args()

    runs_dir = Path(args.runs_dir) if args.runs_dir else (
        REPO / 'palace' / 'tests' / 'runs' / args.run_id
    )
    if not runs_dir.is_absolute():
        runs_dir = REPO / runs_dir
    golden_dir = Path(args.golden_dir)
    if not golden_dir.is_absolute():
        golden_dir = REPO / golden_dir

    rows: list[dict] = []

    g_toc = golden_dir / f'{args.run_id}.toc_llm.json'
    p_toc = runs_dir / f'{args.run_id}.toc_llm.json'
    if not g_toc.exists():
        print(f'STOP: golden missing: {g_toc}')
        return 2
    if not p_toc.exists():
        print(f'STOP: palace toc output missing: {p_toc}')
        return 2
    compare_toc_llm(_load(g_toc), _load(p_toc), rows)

    g_rooms = golden_dir / f'{args.run_id}.json'
    p_rooms = runs_dir / f'{args.run_id}.json'
    g_palace = golden_dir / f'{args.run_id}.palace.json'
    p_palace = runs_dir / f'{args.run_id}.palace.json'
    rooms_phase_present = p_rooms.exists() and p_palace.exists()
    if not rooms_phase_present:
        print('NOTE: palace rooms-phase outputs not found; comparing toc_llm only.')
    else:
        if not g_rooms.exists() or not g_palace.exists():
            print(f'STOP: golden rooms/palace missing in {golden_dir}')
            return 2
        compare_rooms(_load(g_rooms), _load(p_rooms), rows)
        compare_palace(_load(g_palace), _load(p_palace), rows)

    if not rows:
        print(f'MATCH: run-id={args.run_id} palace == golden '
              f'(toc_llm{" + rooms + palace" if rooms_phase_present else ""})')
        return 0
    print(f'MISMATCH: {len(rows)} differences')
    print(format_diff(rows))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
