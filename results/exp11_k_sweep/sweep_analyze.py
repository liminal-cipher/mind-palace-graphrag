"""Sweep 결과 + 기존 K5/K10 embedding 결과 읽기 분석. 쓰기 없음."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SWEEP = Path('results/exp11_k_sweep')
EXISTING = Path('results/rooms')
ANCHORS = json.loads(Path('results/exp10_room_gen/anchors_korean_history.json').read_text(encoding='utf-8'))
SHOULD_SHOW = ANCHORS['should_show']
TARGET = '이성계'
PEEK = ['정도전', '이순신', '권율', '측우기']


def load_sweep(K):
    return json.loads((SWEEP / f'sweep_K{K}.json').read_text(encoding='utf-8'))


def find_room_of(spec, title):
    for r in spec['rooms']:
        for m in r['members']:
            if m['title'] == title:
                return r
    return None


print('=' * 70)
print('1. K 표 (방 개수 / 크기 / max/min)')
print('=' * 70)
print(f'{"K":>3} | {"방":>3} | {"max/min":>7} | sizes (desc)')
for K in range(2, 11):
    spec = load_sweep(K)
    sizes = sorted([r['size'] for r in spec['rooms']], reverse=True)
    ratio = sizes[0] / sizes[-1]
    print(f'{K:>3} | {len(spec["rooms"]):>3} | {ratio:>7.2f} | {sizes}')

print()
print('=' * 70)
print(f'2. {TARGET} 방 멤버 (K=2..10)')
print('=' * 70)
for K in range(2, 11):
    spec = load_sweep(K)
    room = find_room_of(spec, TARGET)
    size = room['size']
    members = room['members']
    if size > 30:
        members = members[:30]
        suffix = f' ... (총 {size}명, degree top 30만 표시)'
    else:
        suffix = f' (총 {size}명)'
    titles = ', '.join(m['title'] for m in members)
    print(f'\n[K={K}] room_id={room["room_id"]}{suffix}')
    print(f'  {titles}')

print()
print('=' * 70)
print(f'3. 참고 앵커 room id (이성계 비교)')
print('=' * 70)
print(f'{"K":>3} | {"이성계":>6} | {"정도전":>6} | {"이순신":>6} | {"권율":>5} | {"측우기":>6}')
for K in range(2, 11):
    spec = load_sweep(K)
    row = []
    for name in [TARGET] + PEEK:
        r = find_room_of(spec, name)
        row.append(str(r['room_id']) if r else 'MISS')
    print(f'{K:>3} | {row[0]:>6} | {row[1]:>6} | {row[2]:>6} | {row[3]:>5} | {row[4]:>6}')

print()
print('=' * 70)
print('4. 기존 결과 (repro_run3_K5/K10_embedding)')
print('=' * 70)


def classify_anchor(spec, title):
    """returns (classification, room_id, room_name) or (None, None, None)"""
    for r in spec['rooms']:
        for m in r['kept']:
            if m['title'] == title:
                return 'keep', r['room_id'], r['name']
        for m in r['demoted']:
            if m['title'] == title:
                return 'demote', r['room_id'], r['name']
    return None, None, None


for tag, K in [('K5', 5), ('K10', 10)]:
    spec = json.loads((EXISTING / f'repro_run3_K{K}_embedding.json').read_text(encoding='utf-8'))
    cls, rid, rname = classify_anchor(spec, TARGET)
    print(f'\n[{tag}] 이성계: classification={cls} room_id={rid} room_name={rname!r}')

    missed = []
    for a in SHOULD_SHOW:
        cls2, rid2, rname2 = classify_anchor(spec, a)
        if cls2 != 'keep':
            missed.append((a, cls2, rid2, rname2))
    print(f'  should_show 놓친 항목 ({len(missed)}/{len(SHOULD_SHOW)}):')
    for a, c, rid2, rname2 in missed:
        tag2 = 'missing' if c is None else c
        print(f'    - {a}: {tag2}  room={rid2} ({rname2!r})')
