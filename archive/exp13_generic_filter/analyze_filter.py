"""필터 sweep 분석. 읽기만, 쓰기 없음."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

OUT = Path('results/exp13_generic_filter')
ANCHORS = json.loads(
    Path('results/exp10_room_gen/anchors_korean_history.json').read_text(encoding='utf-8')
)
SHOULD_SHOW = set(ANCHORS['should_show'])
SHOULD_DEMOTE = set(ANCHORS['should_demote'])
ALIASES = ANCHORS.get('aliases', {})
TARGET = '이성계'
COMP = ['이순신', '권율', '정도전', '측우기']
LEVELS = [0, 10, 20, 30]


def load_N(N):
    return json.loads((OUT / f'filter_N{N}.json').read_text(encoding='utf-8'))


def find_room(spec, title):
    for r in spec['rooms']:
        for m in r['members']:
            if m['title'] == title:
                return r
    return None


print('=' * 72)
print('1. 제거 수준별 표')
print('=' * 72)
print(f'{"N":>3} | {"방수":>4} | {"max":>4} | {"min":>4} | {"max/min":>8} | sizes')
for N in LEVELS:
    spec = load_N(N)
    sizes = sorted([r['size'] for r in spec['rooms']], reverse=True)
    print(f'{N:>3} | {len(spec["rooms"]):>4} | {sizes[0]:>4} | {sizes[-1]:>4} | '
          f'{sizes[0]/sizes[-1]:>8.2f} | {sizes}')

print()
print('=' * 72)
print('2. 제거된 엔티티 + 앵커 겹침')
print('=' * 72)
for N in [10, 20, 30]:
    spec = load_N(N)
    removed = spec['meta']['removed_titles']
    print(f'\n--- N={N} 제거 (degree desc top {N}) ---')
    print(f'  {removed}')
    overlap_show = [t for t in removed if t in SHOULD_SHOW]
    overlap_demote = [t for t in removed if t in SHOULD_DEMOTE]
    print(f'  should_show 겹침 (적신호): {overlap_show or "없음"}')
    print(f'  should_demote 겹침 (청신호): {overlap_demote or "없음"}')

print()
print('=' * 72)
print(f'3. {TARGET} 추적 (room top 15 by degree)')
print('=' * 72)
for N in LEVELS:
    spec = load_N(N)
    room = find_room(spec, TARGET)
    if room is None:
        print(f'\n[N={N}] {TARGET} 자체가 제거됨 (degree top {N}에 포함)')
        continue
    members = room['members'][:15]
    titles = ', '.join(m['title'] for m in members)
    print(f'\n[N={N}] room {room["room_id"]} (size {room["size"]}, top 15):')
    print(f'  {titles}')
    # 비교 앵커 위치
    locs = {}
    for c in COMP:
        r = find_room(spec, c)
        locs[c] = r['room_id'] if r else 'MISS'
    same_iseong = [c for c in COMP if locs[c] == room['room_id']]
    diff = [f'{c}={locs[c]}' for c in COMP if locs[c] != room['room_id']]
    print(f'  같은 방: {same_iseong or "없음"} | 다른 방: {diff or "없음"}')

print()
print('=' * 72)
print('참고: 비교 앵커 room id 매트릭스')
print('=' * 72)
print(f'{"N":>3} | 이성계 | 이순신 | 권율 | 정도전 | 측우기')
for N in LEVELS:
    spec = load_N(N)
    row = []
    for name in [TARGET] + COMP:
        r = find_room(spec, name)
        row.append(str(r['room_id']) if r else 'OUT')
    print(f'{N:>3} | {row[0]:>6} | {row[1]:>6} | {row[2]:>4} | {row[3]:>6} | {row[4]:>6}')
