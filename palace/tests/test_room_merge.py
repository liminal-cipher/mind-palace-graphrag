"""Unit tests for build_rooms.absorb_empty_rooms (undersized merge + K cap).

Deterministic, no LLM, no snapshot. Asserts the confirmed merge rules:
  - undersized = total nodes (kept + demoted) < min_room_nodes
  - merge the smallest room (tie -> earliest) into its preceding neighbor;
    the first room merges into its successor instead
  - keep ∪ demote conserved; earlier room's members first
  - absorber keeps its own name/summary; absorbed dropped
  - result room count within [1, max_rooms]
  - no-op (input untouched) when already within bounds

Run:
    python palace/tests/test_room_merge.py
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from palace.build_rooms import absorb_empty_rooms  # noqa: E402


def mk(room_id: int, kept: list[str], demoted: list[str], name: str | None = None) -> dict:
    return {
        'room_id': room_id,
        'name': name or f'room{room_id}',
        'kept': [{'title': t} for t in kept],
        'demoted': [{'title': t} for t in demoted],
        'coherence_flag': 'ok',
        '_meta': {
            'section_idx': room_id,
            'section_name': f'sec{room_id}',
            'coherence_reason': f'summary{room_id}',
        },
    }


def rj(rooms: list[dict]) -> dict:
    return {'meta': {}, 'rooms': rooms, 'unassigned': []}


def titles(room: dict, bucket: str) -> list[str]:
    return [x['title'] for x in room.get(bucket, [])]


def all_titles(payload: dict) -> list[str]:
    out: list[str] = []
    for r in payload['rooms']:
        out += titles(r, 'kept') + titles(r, 'demoted')
    return sorted(out)


def total(room: dict) -> int:
    return len(room.get('kept', [])) + len(room.get('demoted', []))


def canon(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------

def test_noop_within_bounds():
    """All rooms >= min and count <= max -> input returned untouched."""
    before = rj([mk(0, ['a', 'b'], []), mk(1, ['c'], ['d']), mk(2, ['e', 'f'], ['g'])])
    snap = canon(before)
    after = absorb_empty_rooms(before, min_room_nodes=2, max_rooms=10)
    assert after is before, 'no-op must return the same object'
    assert canon(after) == snap, 'no-op must not mutate the payload'
    assert [r['room_id'] for r in after['rooms']] == [0, 1, 2]


def test_empty_room_absorbed_into_preceding():
    """A 0-node room is removed; concepts conserved; merged into predecessor."""
    before = rj([mk(0, ['a', 'b'], ['p']), mk(1, [], []), mk(2, ['c'], ['d'])])
    after = absorb_empty_rooms(before, min_room_nodes=2, max_rooms=10)
    assert len(after['rooms']) == 2
    assert all_titles(before) == all_titles(after)
    # room 0 absorbed the empty room (nothing to move) and kept its name.
    assert after['rooms'][0]['name'] == 'room0'
    assert 'absorbed_from' in after['rooms'][0]['_meta']
    assert [r['room_id'] for r in after['rooms']] == [0, 1]


def test_one_node_room_merges_into_preceding_not_successor():
    """The key behavior change: undersized rooms go to the PRECEDING neighbor."""
    before = rj([mk(0, ['a', 'b'], ['p']), mk(1, [], ['x']), mk(2, ['c', 'd'], [])])
    after = absorb_empty_rooms(before, min_room_nodes=2, max_rooms=10)
    assert len(after['rooms']) == 2
    host = after['rooms'][0]
    assert host['name'] == 'room0'
    # 'x' moved into the predecessor, appended after the host's own demoted.
    assert titles(host, 'demoted') == ['p', 'x']
    # the successor (now room 1) did NOT receive 'x'.
    assert 'x' not in all_titles(rj([after['rooms'][1]]))
    assert all_titles(before) == all_titles(after)


def test_first_room_merges_into_successor_order_preserved():
    """First room has no predecessor -> merges into successor; earlier first."""
    before = rj([mk(0, ['a'], []), mk(1, ['b', 'c'], ['d'])])
    after = absorb_empty_rooms(before, min_room_nodes=2, max_rooms=10)
    assert len(after['rooms']) == 1
    host = after['rooms'][0]
    assert host['name'] == 'room1', 'absorber (successor) keeps its name'
    # earlier room (room0, "a") members come first.
    assert titles(host, 'kept') == ['a', 'b', 'c']
    assert all_titles(before) == all_titles(after)
    assert host['room_id'] == 0


def test_overflow_capped_smallest_first():
    """> max_rooms collapses to exactly max_rooms; conservation + K in range."""
    rooms = [mk(i, [f'k{i}a', f'k{i}b', f'k{i}c'], []) for i in range(12)]
    # make a couple genuinely small so smallest-first is observable
    rooms[5] = mk(5, ['solo5'], [])
    rooms[9] = mk(9, ['solo9'], [])
    before = rj(rooms)
    after = absorb_empty_rooms(before, min_room_nodes=2, max_rooms=10)
    assert len(after['rooms']) <= 10
    assert len(after['rooms']) >= 1
    assert all_titles(before) == all_titles(after)
    # every surviving room meets the threshold (or we collapsed to one room).
    assert len(after['rooms']) == 1 or all(total(r) >= 2 for r in after['rooms'])
    assert [r['room_id'] for r in after['rooms']] == list(range(len(after['rooms'])))


def test_tie_break_earliest_index():
    """Two equally-small rooms: the earlier one is absorbed first."""
    before = rj([
        mk(0, ['a', 'b'], []),
        mk(1, ['x'], []),          # undersized, earlier
        mk(2, ['c', 'd'], []),
        mk(3, ['y'], []),          # undersized, later
        mk(4, ['e', 'f'], []),
    ])
    after = absorb_empty_rooms(before, min_room_nodes=2, max_rooms=10)
    assert all_titles(before) == all_titles(after)
    assert all(total(r) >= 2 for r in after['rooms'])
    # 'x' (room1) merged into room0; 'y' (room3) merged into room2.
    names = {r['name']: titles(r, 'kept') for r in after['rooms']}
    assert 'x' in names['room0']
    assert 'y' in names['room2']


def test_single_room_left_accepts_below_min():
    """No lower bound is forced: collapsing to 1 room is accepted even < min."""
    before = rj([mk(0, ['a'], []), mk(1, [], [])])
    after = absorb_empty_rooms(before, min_room_nodes=2, max_rooms=10)
    assert len(after['rooms']) == 1
    assert all_titles(before) == all_titles(after)


def test_conservation_and_bounds_stress():
    """keep ∪ demote conserved and K within [1, max_rooms] across a mix."""
    before = rj([
        mk(0, [], []),                       # empty
        mk(1, ['a'], ['b', 'c']),            # ok
        mk(2, ['d'], []),                    # undersized
        mk(3, ['e', 'f', 'g'], ['h']),      # ok
        mk(4, [], ['i']),                    # undersized
        mk(5, ['j', 'k'], []),              # ok
    ])
    after = absorb_empty_rooms(before, min_room_nodes=2, max_rooms=4)
    assert all_titles(before) == all_titles(after)
    assert 1 <= len(after['rooms']) <= 4
    assert all(total(r) >= 2 for r in after['rooms'])


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failures = 0
    for t in tests:
        try:
            t()
            print(f'PASS  {t.__name__}')
        except AssertionError as e:
            failures += 1
            print(f'FAIL  {t.__name__}: {e}')
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f'ERROR {t.__name__}: {type(e).__name__}: {e}')
    print(f'\n{len(tests) - failures}/{len(tests)} passed')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
