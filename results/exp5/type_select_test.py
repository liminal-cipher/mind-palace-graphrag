"""type 선택 일회성 프로브. degree top-N vs type 버킷(keep)만 거르기 비교.
repro_run3 위에서 읽기 전용으로만 동작. 공유 lib에 들어가는 매퍼가 아니라 이 실험용.
입력: repro_run3 (entities, communities, lancedb/entity_description),
      results/exp5/stage2_emb_K10.json (이미 만들어진 ward K=10 partition).
출력: results/exp5/type_select_test.md.
"""
from __future__ import annotations
import json
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path
from collections import defaultdict, Counter
import pandas as pd
import numpy as np
import lancedb

BASE = Path('results/snapshots/repro_run3')
OUT = Path('results/exp5')


# === 데이터 로드 ===
ent = pd.read_parquet(BASE / 'entities.parquet').set_index('id')
com = pd.read_parquet(BASE / 'communities.parquet')
com_l0 = com[com['level'] == 0].copy().reset_index(drop=True)
cnum_to_eids = {int(c['community']): list(c['entity_ids']) for _, c in com_l0.iterrows()}

db = lancedb.connect(str(BASE / 'lancedb'))
vec_df = db.open_table('entity_description').to_pandas()
vec_by_id = {row['id']: np.array(row['vector'], dtype=np.float32) for _, row in vec_df.iterrows()}

in_eids = set()
for eids in cnum_to_eids.values():
    in_eids.update(eids)
orphan_eids = set(ent.index) - in_eids
assert len(orphan_eids) == 31, f'expected 31 orphans, got {len(orphan_eids)}'


# === 건물 partition (재사용) ===
emb_K10 = json.loads((OUT / 'stage2_emb_K10.json').read_text(encoding='utf-8'))
buildings = []  # [{'id', 'communities', 'eids'}]
for b in emb_K10['merged_rooms']:
    eids, seen = [], set()
    for cnum in b['members']:
        for e in cnum_to_eids[cnum]:
            if e not in seen:
                seen.add(e); eids.append(e)
    buildings.append({'id': b['new_id'], 'communities': sorted(b['members']), 'eids': eids})


# === 타입 버킷 매퍼 (이 프로브 한정) ===
KEEP_BUCKETS = [
    ('인물', ['인물', '권력자', '군인']),
    ('사건/전쟁', ['사건', '전쟁', '전투']),
    ('문헌/저서/기록', ['문서', '문헌', '저서', '문집', '법전', '문학작품', '공문서', '기록']),
    ('발명품/기기', ['과학기기', '발명품', '기기']),
    ('문화재/작품', ['문화재', '문화유산', '기념물', '건축물']),
]
DEMOTE_BUCKETS = [
    ('지역/지리', ['지역', '지리', '장소', '지명', '행정 구역']),
    ('국가', ['국가', '민족', '왕조']),
    ('시대', ['시대', '시기']),
    ('일반개념/사상', ['개념', '사상', '이념', '학문', '윤리']),
    ('집단/계층', ['집단', '계층', '구성원']),
]


def bucket(typ):
    for name, kws in KEEP_BUCKETS:
        if any(kw in typ for kw in kws):
            return ('keep', name)
    for name, kws in DEMOTE_BUCKETS:
        if any(kw in typ for kw in kws):
            return ('demote', name)
    return ('unknown', 'unknown')


# 버킷 분포 print + 모아 두기
bucket_counter = Counter()
bucket_examples = defaultdict(list)
for eid, r in ent.iterrows():
    side, name = bucket(str(r['type']))
    bucket_counter[(side, name)] += 1
    bucket_examples[(side, name)].append(str(r['title']))

print('=== 타입 버킷 분포 ===')
ORDER = {'keep': 0, 'demote': 1, 'unknown': 2}
for (side, name), n in sorted(bucket_counter.items(), key=lambda x: (ORDER[x[0][0]], -x[1])):
    examples = ', '.join(bucket_examples[(side, name)][:5])
    print(f'  [{side:7}] {name:<15} {n:>4}개  예: {examples}')


# === orphan homing (centroid 코사인) ===
centroids = []
for b in buildings:
    vecs = np.stack([vec_by_id[e] for e in b['eids']])
    c = vecs.mean(axis=0)
    c = c / max(np.linalg.norm(c), 1e-12)
    centroids.append(c)
centroids_mat = np.stack(centroids)

orphan_home = {}  # eid → (building_id, sim)
for oid in orphan_eids:
    v = vec_by_id[oid]
    v = v / max(np.linalg.norm(v), 1e-12)
    sims = centroids_mat @ v
    bidx = int(np.argmax(sims))
    orphan_home[oid] = (buildings[bidx]['id'], float(sims[bidx]))

print('\n=== orphan homing (31개) ===')
for oid in sorted(orphan_eids, key=lambda e: str(ent.loc[e, 'title'])):
    title = str(ent.loc[oid, 'title'])
    typ = str(ent.loc[oid, 'type'])
    bid, sim = orphan_home[oid]
    side, _ = bucket(typ)
    flag = 'KEEP' if side == 'keep' else ('DEMOTE' if side == 'demote' else 'unk')
    print(f'  {title:<18} → 건물 {bid:<2} sim={sim:.3f} | [{flag:6}] {typ}')


# === 두 선택 만들기 ===
def degree_top_n(eids, n=20):
    rows = []
    for e in eids:
        r = ent.loc[e]
        rows.append((str(r['title']), str(r['type']), int(r['degree']), e))
    rows.sort(key=lambda x: (-x[2], x[0]))
    return rows[:n]


def type_keep(eids):
    rows = []
    for e in eids:
        r = ent.loc[e]
        side, name = bucket(str(r['type']))
        if side == 'keep':
            rows.append((str(r['title']), str(r['type']), int(r['degree']), e, name))
    rows.sort(key=lambda x: (-x[2], x[0]))
    return rows


# 건물별 type-method 멤버 = 원멤버 + homed orphan
building_type_members = {b['id']: list(b['eids']) for b in buildings}
for oid, (bid, _) in orphan_home.items():
    building_type_members[bid].append(oid)

deg_sel = {b['id']: degree_top_n(b['eids'], 20) for b in buildings}
type_sel = {b['id']: type_keep(building_type_members[b['id']]) for b in buildings}

print('\n=== 건물별 keep 엔티티 개수 ===')
for b in buildings:
    orig = len(b['eids'])
    homed = len(building_type_members[b['id']]) - orig
    print(f'  건물 {b["id"]:<2}: 원 {orig:>3}개 + homed {homed:>2}개 / degree top20={len(deg_sel[b["id"]]):>2} / type keep={len(type_sel[b["id"]]):>3}')


# === 판정 ===
SHOULD_SHOW = ['측우기', '자격루', '혼천의', '앙부일구', '인지의',
               '이순신', '권율', '곽재우', '김시민', '정도전', '이성계',
               '임진왜란', '훈민정음', '거북선']
SHOULD_DEMOTE = ['조선', '백성', '백성들', '성리학', '붕당정치',
                 '경상도', '전라도', '함경도']
ALIASES = {'붕당정치': '붕당 정치'}

title_to_id = {}
for eid, r in ent.iterrows():
    title_to_id.setdefault(str(r['title']), eid)


def find_info(name):
    actual = ALIASES.get(name, name)
    eid = title_to_id.get(actual)
    if eid is None:
        return None
    r = ent.loc[eid]
    is_orphan = eid in orphan_eids
    if is_orphan:
        bid = orphan_home[eid][0]
    else:
        bid = next((b['id'] for b in buildings if eid in b['eids']), None)
    return {'eid': eid, 'title': str(r['title']), 'type': str(r['type']),
            'degree': int(r['degree']), 'building': bid, 'orphan': is_orphan}


def shown_in(eid, sel):
    return any(row[3] == eid for row in sel)


def judge(name_list):
    rows = []
    for name in name_list:
        info = find_info(name)
        if info is None:
            rows.append({'name': name, 'status': 'not-found', 'building': '-',
                         'degree': '-', 'type': '-',
                         'deg_method': '-', 'type_method': '-'})
            continue
        bid = info['building']
        deg_ok = shown_in(info['eid'], deg_sel[bid])
        type_ok = shown_in(info['eid'], type_sel[bid])
        rows.append({
            'name': name, 'status': 'orphan' if info['orphan'] else 'ok',
            'building': str(bid), 'degree': str(info['degree']),
            'type': info['type'],
            'deg_method': 'O' if deg_ok else 'X',
            'type_method': 'O' if type_ok else 'X',
        })
    return rows


show_rows = judge(SHOULD_SHOW)
demote_rows = judge(SHOULD_DEMOTE)

print('\n=== SHOULD-SHOW (살아야 함) ===')
print(f'{"name":<10} {"건물":<4} {"deg":<3} {"type":<4} {"degree":<6} {"상태":<7} type')
for r in show_rows:
    print(f'{r["name"]:<10} {r["building"]:<4} {r["deg_method"]:<3} {r["type_method"]:<4} '
          f'{r["degree"]:<6} {r["status"]:<7} {r["type"]}')

print('\n=== SHOULD-DEMOTE (빠져야 함) ===')
print(f'{"name":<10} {"건물":<4} {"deg":<3} {"type":<4} {"degree":<6} {"상태":<7} type')
for r in demote_rows:
    print(f'{r["name"]:<10} {r["building"]:<4} {r["deg_method"]:<3} {r["type_method"]:<4} '
          f'{r["degree"]:<6} {r["status"]:<7} {r["type"]}')


# === 마크다운 출력 ===
md = []
md.append('# type 선택 테스트 결과')
md.append('')
md.append('베이스: `repro_run3` · 건물 partition: `stage2_emb_K10.json` (ward, K=10) · 엔티티 임베딩: lancedb `entity_description`')
md.append('')
md.append('테스트 질문: degree top-N 대신 type 버킷(keep)만 거르는 게 외울 만한 엔티티를 더 잘 살리나? orphan 31개는 entity_description centroid 코사인으로 가장 가까운 건물에 호밍.')
md.append('')

md.append('## 1. 타입 버킷 분포')
md.append('')
md.append('| side | 버킷 | 개수 | 예시 |')
md.append('|---|---|---|---|')
for (side, name), n in sorted(bucket_counter.items(), key=lambda x: (ORDER[x[0][0]], -x[1])):
    examples = ', '.join(bucket_examples[(side, name)][:5])
    md.append(f'| {side} | {name} | {n} | {examples} |')
md.append('')

md.append('## 2. orphan homing (31개)')
md.append('')
md.append('| orphan | type | side | homed 건물 | sim |')
md.append('|---|---|---|---|---|')
for oid in sorted(orphan_eids, key=lambda e: str(ent.loc[e, 'title'])):
    title = str(ent.loc[oid, 'title'])
    typ = str(ent.loc[oid, 'type'])
    bid, sim = orphan_home[oid]
    side, _ = bucket(typ)
    md.append(f'| {title} | {typ} | {side} | 건물 {bid} | {sim:.3f} |')
md.append('')

md.append('## 3. 건물별 두 선택 결과')
md.append('')
for b in buildings:
    bid = b['id']
    ds = deg_sel[bid]
    ts = type_sel[bid]
    orig = len(b['eids'])
    homed = len(building_type_members[bid]) - orig
    md.append(f'### 건물 {bid} | 멤버 방 {b["communities"]} | 원엔티티 {orig}개 + homed orphan {homed}개')
    md.append('')
    md.append(f'**degree top-20** (원멤버만, {len(ds)}개)')
    md.append('')
    md.append('| title | type | degree |')
    md.append('|---|---|---|')
    for title, typ, deg, _ in ds:
        md.append(f'| {title} | {typ} | {deg} |')
    md.append('')
    md.append(f'**type keep 전부** (homed 포함, {len(ts)}개, 캡 없음)')
    md.append('')
    md.append('| title | type | degree | 버킷 |')
    md.append('|---|---|---|---|')
    for title, typ, deg, _, bname in ts:
        md.append(f'| {title} | {typ} | {deg} | {bname} |')
    md.append('')

md.append('## 4. SHOULD-SHOW (살아야 함) O/X')
md.append('')
md.append('| name | 건물 | degree top20 | type keep | degree | 상태 | 엔티티 type |')
md.append('|---|---|---|---|---|---|---|')
for r in show_rows:
    md.append(f'| {r["name"]} | {r["building"]} | {r["deg_method"]} | {r["type_method"]} | {r["degree"]} | {r["status"]} | {r["type"]} |')
md.append('')

md.append('## 5. SHOULD-DEMOTE (빠져야 함) O/X')
md.append('')
md.append('| name | 건물 | degree top20 | type keep | degree | 상태 | 엔티티 type |')
md.append('|---|---|---|---|---|---|---|')
for r in demote_rows:
    md.append(f'| {r["name"]} | {r["building"]} | {r["deg_method"]} | {r["type_method"]} | {r["degree"]} | {r["status"]} | {r["type"]} |')
md.append('')

target = OUT / 'type_select_test.md'
target.write_text('\n'.join(md), encoding='utf-8')
print(f'\nsaved: {target}')
