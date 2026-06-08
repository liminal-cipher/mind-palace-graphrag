"""n=3 집계. 다수결 + flip rate + 앵커 hit 재계산. 읽기만, 쓰기 없음."""
from __future__ import annotations

import io
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

N3 = Path('results/exp12_n3_stability')
ANCHORS = json.loads(
    Path('results/exp10_room_gen/anchors_korean_history.json').read_text(encoding='utf-8')
)
SHOULD_SHOW = ANCHORS['should_show']
SHOULD_DEMOTE = ANCHORS['should_demote']
ALIASES = ANCHORS.get('aliases', {})


def load_run(K, run_idx):
    return json.loads((N3 / f'K{K}_run{run_idx}.json').read_text(encoding='utf-8'))


def title_to_state(spec):
    """title -> (room_id, classification, room_name)"""
    out = {}
    for r in spec['rooms']:
        for m in r['kept']:
            out[m['title']] = (r['room_id'], 'keep', r['name'])
        for m in r['demoted']:
            out[m['title']] = (r['room_id'], 'demote', r['name'])
    return out


def alias(name):
    return ALIASES.get(name, name)


def hits_per_run(states, anchors_list, want):
    """want: 'keep' or 'demote'."""
    hits = 0
    missed = []
    for a in anchors_list:
        a2 = alias(a)
        st = states.get(a2)
        if st is None:
            missed.append((a, 'missing', None))
            continue
        if st[1] == want:
            hits += 1
        else:
            missed.append((a, st[1], st[0]))
    return hits, missed


def majority_states(states_list):
    """3 runs → per-title majority. Returns title -> (room_id, classification)."""
    titles = set()
    for s in states_list:
        titles.update(s.keys())
    out = {}
    for t in titles:
        classes = [s.get(t, (None, 'missing', None))[1] for s in states_list]
        room_ids = [s.get(t, (None, 'missing', None))[0] for s in states_list]
        keep_votes = sum(1 for c in classes if c == 'keep')
        final = 'keep' if keep_votes >= 2 else 'demote'
        # room_id: take run1 (clusters are deterministic so all 3 agree)
        rid = next((r for r in room_ids if r is not None), None)
        out[t] = (rid, final)
    return out


def flip_rate(states_list, subset=None):
    """Title is 'flipped' if classifications across 3 runs are NOT unanimous."""
    titles = set()
    for s in states_list:
        titles.update(s.keys())
    if subset is not None:
        titles &= set(alias(x) for x in subset)
    if not titles:
        return 0.0, 0, 0
    flipped = 0
    for t in titles:
        cls = {s.get(t, (None, 'missing', None))[1] for s in states_list}
        if len(cls) > 1:
            flipped += 1
    return flipped / len(titles), flipped, len(titles)


# === 메인 ===
TARGET = '이성계'

print('=' * 72)
print('1. K별 hits (run1/run2/run3 + 다수결)')
print('=' * 72)

per_K = {}
for K in [10, 5]:
    runs = [load_run(K, i) for i in (1, 2, 3)]
    states_list = [title_to_state(r) for r in runs]
    maj = majority_states(states_list)
    # majority states 형식 통일: title -> (rid, cls, name=None)
    maj_states_for_hit = {t: (rid, cls, None) for t, (rid, cls) in maj.items()}

    per_K[K] = {
        'runs': runs,
        'states_list': states_list,
        'majority': maj,
        'maj_states_for_hit': maj_states_for_hit,
    }

    print(f'\n--- K={K} ---')
    print(f'{"":>10} | should_show /14 | should_demote /8')
    for i, s in enumerate(states_list, 1):
        sh, _ = hits_per_run(s, SHOULD_SHOW, 'keep')
        sd, _ = hits_per_run(s, SHOULD_DEMOTE, 'demote')
        print(f'{"run"+str(i):>10} | {sh:>15} | {sd:>16}')
    sh, sh_miss = hits_per_run(maj_states_for_hit, SHOULD_SHOW, 'keep')
    sd, sd_miss = hits_per_run(maj_states_for_hit, SHOULD_DEMOTE, 'demote')
    print(f'{"majority":>10} | {sh:>15} | {sd:>16}')

print()
print('=' * 72)
print('2. flip rate (런간 분류 불일치 비율)')
print('=' * 72)
print(f'{"K":>3} | {"전체":>14} | {"should_show":>14} | {"should_demote":>14}')
for K in [10, 5]:
    s_list = per_K[K]['states_list']
    fr_all, flips_all, tot_all = flip_rate(s_list)
    fr_show, flips_show, tot_show = flip_rate(s_list, SHOULD_SHOW)
    fr_dem, flips_dem, tot_dem = flip_rate(s_list, SHOULD_DEMOTE)
    print(f'{K:>3} | {flips_all:>3}/{tot_all:>3} ({fr_all*100:5.1f}%) | '
          f'{flips_show:>3}/{tot_show:>3} ({fr_show*100:5.1f}%) | '
          f'{flips_dem:>3}/{tot_dem:>3} ({fr_dem*100:5.1f}%)')

print()
print('=' * 72)
print(f'3. {TARGET} (3런 + 다수결 + room id)')
print('=' * 72)
print(f'{"K":>3} | run1 | run2 | run3 | maj  | room_id | room_name(run1)')
for K in [10, 5]:
    s_list = per_K[K]['states_list']
    seq = []
    rid = None
    rname = None
    for s in s_list:
        st = s.get(TARGET)
        if st is None:
            seq.append('?')
        else:
            seq.append('K' if st[1] == 'keep' else 'D')
            rid = st[0]
            rname = st[2]
    maj = per_K[K]['majority'].get(TARGET)
    maj_tag = 'K' if maj and maj[1] == 'keep' else 'D' if maj else '?'
    print(f'{K:>3} | {seq[0]:>4} | {seq[1]:>4} | {seq[2]:>4} | {maj_tag:>4} | '
          f'{rid:>7} | {rname!r}')

print()
print('=' * 72)
print('4. 다수결 should_show 놓침')
print('=' * 72)
for K in [10, 5]:
    maj_states = per_K[K]['maj_states_for_hit']
    sh, sh_miss = hits_per_run(maj_states, SHOULD_SHOW, 'keep')
    sd, sd_miss = hits_per_run(maj_states, SHOULD_DEMOTE, 'demote')
    print(f'\n--- K={K} (should_show {sh}/14, should_demote {sd}/8) ---')
    print('  should_show 놓침:')
    for name, cls, rid in sh_miss:
        print(f'    - {name}: {cls} room={rid}')
    print('  should_demote 놓침:')
    for name, cls, rid in sd_miss:
        print(f'    - {name}: {cls} room={rid}')

print()
print('=' * 72)
print('참고: 방 이름 일관성 (런별 같은 room_id 이름 비교)')
print('=' * 72)
for K in [10, 5]:
    runs = per_K[K]['runs']
    print(f'\n--- K={K} ---')
    for room_id in range(K):
        names = [r['rooms'][room_id]['name'] for r in runs]
        same = len(set(names)) == 1
        tag = 'SAME' if same else 'DIFF'
        print(f'  room {room_id} [{tag}]: {names}')
