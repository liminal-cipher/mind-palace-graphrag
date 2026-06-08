"""Agreement metrics across N runs of LLM-only room design.

Logic adapted from results/pipeline/run.py analyze_passes, but with an
upstream room-matching step: LLM partitions vary across runs in both
the number and labelling of rooms, so we Jaccard-match rooms across
runs (greedy max) before computing per-room agreement.

Metrics per run pair (1-2, 1-3, 2-3) and aggregated:
- room counts per run
- matched room Jaccard (mean / min over matched pairs)
- unmatched rooms (rooms with no partner of jaccard > 0)
- entities whose room changed across runs
- entities whose visibility changed across runs
- anchor stability: any non-background visibility for each should_show title,
  and which room contains 이성계 per run
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from itertools import combinations
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

EXP_DIR = Path('results/exp14_overlap200_stability')
ANCHORS_PATH = Path('results/exp10_room_gen/anchors_korean_history.json')
SPECIAL_ANCHOR = '이성계'


def load_run(idx: int) -> dict:
    return json.loads((EXP_DIR / f'run{idx}.json').read_text(encoding='utf-8'))


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 1.0


def room_members(run: dict) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {r['id']: set() for r in run['rooms']}
    for title, asn in run['assignments'].items():
        rid = asn['room_id']
        if rid in out:
            out[rid].add(title)
    return out


def greedy_match(
    rooms_a: dict[int, set[str]],
    rooms_b: dict[int, set[str]],
) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
    """Greedy pairing: pick the (a,b) pair with the highest Jaccard, lock both,
    repeat until no positive-Jaccard pair remains.

    Returns (matches, unmatched_a, unmatched_b). matches is a list of
    (a_id, b_id, jaccard).
    """
    pairs = []
    for ai, am in rooms_a.items():
        for bi, bm in rooms_b.items():
            j = jaccard(am, bm)
            if j > 0:
                pairs.append((j, ai, bi))
    pairs.sort(reverse=True)

    used_a: set[int] = set()
    used_b: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for j, ai, bi in pairs:
        if ai in used_a or bi in used_b:
            continue
        used_a.add(ai)
        used_b.add(bi)
        matches.append((ai, bi, j))

    unmatched_a = [i for i in rooms_a if i not in used_a]
    unmatched_b = [i for i in rooms_b if i not in used_b]
    return matches, unmatched_a, unmatched_b


def pair_stats(
    run_a: dict,
    run_b: dict,
) -> dict:
    rooms_a = room_members(run_a)
    rooms_b = room_members(run_b)
    matches, unA, unB = greedy_match(rooms_a, rooms_b)
    jvals = [j for _, _, j in matches]
    mean_j = sum(jvals) / len(jvals) if jvals else 0.0
    min_j = min(jvals) if jvals else 0.0

    # Build entity-level comparison using the matching as ground truth.
    a_room_of = {t: a['room_id'] for t, a in run_a['assignments'].items()}
    a_vis_of = {t: a['visibility'] for t, a in run_a['assignments'].items()}
    b_room_of = {t: a['room_id'] for t, a in run_b['assignments'].items()}
    b_vis_of = {t: a['visibility'] for t, a in run_b['assignments'].items()}

    # Map each matched b-room -> a-room; unmatched b-rooms keep their own id.
    b_to_a = {bi: ai for ai, bi, _ in matches}

    common = set(a_room_of) & set(b_room_of)
    moved_room = 0
    moved_vis = 0
    for t in common:
        b_canon = b_to_a.get(b_room_of[t], (-1, b_room_of[t]))
        # If b's room has no match in a, treat as different room.
        if b_to_a.get(b_room_of[t]) is None:
            moved_room += 1
        elif a_room_of[t] != b_to_a[b_room_of[t]]:
            moved_room += 1
        if a_vis_of[t] != b_vis_of[t]:
            moved_vis += 1
        _ = b_canon

    return {
        'room_count_a': len(rooms_a),
        'room_count_b': len(rooms_b),
        'matches': [
            {'a': ai, 'b': bi, 'jaccard': round(j, 4),
             'a_size': len(rooms_a[ai]), 'b_size': len(rooms_b[bi])}
            for ai, bi, j in matches
        ],
        'mean_matched_jaccard': round(mean_j, 4),
        'min_matched_jaccard': round(min_j, 4),
        'unmatched_a': unA,
        'unmatched_b': unB,
        'unmatched_count': len(unA) + len(unB),
        'common_entities': len(common),
        'moved_room_entities': moved_room,
        'moved_visibility_entities': moved_vis,
        'moved_room_fraction': round(moved_room / max(len(common), 1), 4),
        'moved_visibility_fraction': round(moved_vis / max(len(common), 1), 4),
    }


def anchor_stability(runs: list[dict], anchors: list[str]) -> dict:
    per_anchor = []
    for a in anchors:
        per_run: list[dict] = []
        non_bg_count = 0
        for r in runs:
            asn = r['assignments'].get(a)
            if not asn:
                per_run.append({'present': False})
                continue
            room = next(
                (x for x in r['rooms'] if x['id'] == asn['room_id']),
                None,
            )
            visible = asn['visibility'] != 'background'
            if visible:
                non_bg_count += 1
            per_run.append({
                'present': True,
                'room_id': asn['room_id'],
                'room_title': room['title'] if room else None,
                'visibility': asn['visibility'],
                'visible': visible,
            })
        per_anchor.append({
            'title': a,
            'visible_in_n_runs': non_bg_count,
            'per_run': per_run,
        })
    visible_all = sum(1 for x in per_anchor if x['visible_in_n_runs'] == len(runs))
    visible_some = sum(1 for x in per_anchor if x['visible_in_n_runs'] > 0)
    return {
        'n_anchors': len(anchors),
        'visible_in_all_runs': visible_all,
        'visible_in_any_run': visible_some,
        'per_anchor': per_anchor,
    }


def special_anchor_stability(runs: list[dict], title: str) -> dict:
    rooms_per_run: list[dict] = []
    for r in runs:
        asn = r['assignments'].get(title)
        if not asn:
            rooms_per_run.append({'present': False})
            continue
        room = next(
            (x for x in r['rooms'] if x['id'] == asn['room_id']),
            None,
        )
        rooms_per_run.append({
            'present': True,
            'room_id': asn['room_id'],
            'room_title': room['title'] if room else None,
            'flow_note': room.get('flow_note') if room else None,
            'visibility': asn['visibility'],
        })
    # Cross-run room consistency: do the room titles refer to founding-of-Joseon?
    titles = [x.get('room_title') for x in rooms_per_run if x.get('present')]
    return {
        'title': title,
        'per_run': rooms_per_run,
        'all_visible': all(
            x.get('visibility') != 'background'
            for x in rooms_per_run if x.get('present')
        ),
        'all_present': all(x.get('present') for x in rooms_per_run),
        'room_titles_across_runs': titles,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=3)
    args = ap.parse_args()

    runs = [load_run(i) for i in range(1, args.n + 1)]
    anchors_data = json.loads(ANCHORS_PATH.read_text(encoding='utf-8'))
    anchors = anchors_data['should_show']

    pairwise: list[dict] = []
    for i, j in combinations(range(1, args.n + 1), 2):
        ps = pair_stats(runs[i - 1], runs[j - 1])
        ps['pair'] = f'run{i}-run{j}'
        pairwise.append(ps)

    mean_j_list = [p['mean_matched_jaccard'] for p in pairwise]
    min_j_list = [p['min_matched_jaccard'] for p in pairwise]
    unmatched_list = [p['unmatched_count'] for p in pairwise]
    moved_room_list = [p['moved_room_entities'] for p in pairwise]
    moved_vis_list = [p['moved_visibility_entities'] for p in pairwise]

    aggregate = {
        'n_runs': args.n,
        'room_counts': [len(r['rooms']) for r in runs],
        'assignments_per_run': [len(r['assignments']) for r in runs],
        'mean_pair_matched_jaccard': round(sum(mean_j_list) / len(mean_j_list), 4),
        'min_pair_matched_jaccard': round(min(min_j_list), 4),
        'avg_unmatched_rooms_per_pair': round(sum(unmatched_list) / len(unmatched_list), 4),
        'avg_moved_room_entities_per_pair': round(sum(moved_room_list) / len(moved_room_list), 4),
        'avg_moved_visibility_entities_per_pair': round(sum(moved_vis_list) / len(moved_vis_list), 4),
    }

    anchors_summary = anchor_stability(runs, anchors)
    yi_seonggye = special_anchor_stability(runs, SPECIAL_ANCHOR)

    out = {
        'aggregate': aggregate,
        'pairwise': pairwise,
        'anchors': anchors_summary,
        'yi_seonggye': yi_seonggye,
    }
    (EXP_DIR / 'agreement.json').write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8',
    )

    # Console
    print('=== aggregate ===')
    for k, v in aggregate.items():
        print(f'  {k}: {v}')
    print('\n=== pairwise ===')
    for p in pairwise:
        print(f'  {p["pair"]}: mean_jacc={p["mean_matched_jaccard"]} '
              f'min={p["min_matched_jaccard"]} unmatched={p["unmatched_count"]} '
              f'room_moved={p["moved_room_entities"]} '
              f'vis_moved={p["moved_visibility_entities"]}')
    print('\n=== anchors should_show ===')
    print(f'  {anchors_summary["visible_in_all_runs"]}/{anchors_summary["n_anchors"]} '
          f'visible (non-background) in all {args.n} runs')
    print(f'  {anchors_summary["visible_in_any_run"]}/{anchors_summary["n_anchors"]} '
          f'visible in at least one run')
    print('\n=== 이성계 ===')
    for i, pr in enumerate(yi_seonggye['per_run'], 1):
        print(f'  run{i}: room "{pr.get("room_title")}" '
              f'visibility={pr.get("visibility")}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
