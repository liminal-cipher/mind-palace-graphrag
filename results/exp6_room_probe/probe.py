"""exp6 방 토대 프로브. graph community 우회하고 entity embedding을 직접 ward 클러스터해서
stage2_emb_K10(community 병합)이랑 비교. orphan 통합·거대 덩어리 분해·주제 응집을 본다.
입력: repro_run3 (entities, communities, lancedb/entity_description),
      results/exp5/stage2_emb_K10.json (비교용).
출력: results/exp6_room_probe/report.md.
"""
from __future__ import annotations
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path
from collections import defaultdict, Counter
import pandas as pd
import numpy as np
import lancedb
from scipy.cluster.hierarchy import linkage, fcluster

BASE = Path('results/snapshots/repro_run3')
EXP5 = Path('results/exp5')
OUT = Path('results/exp6_room_probe')
OUT.mkdir(parents=True, exist_ok=True)


# === 데이터 ===
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


# === 직접 클러스터 (357 엔티티 ward) ===
ent_ids = list(ent.index)
mat = np.stack([vec_by_id[e] for e in ent_ids]).astype(np.float32)
norms = np.linalg.norm(mat, axis=1, keepdims=True)
mat_n = mat / np.clip(norms, 1e-12, None)
# ward는 euclidean 강제. L2 정규화된 벡터에서 euclidean^2 = 2(1-cos)이라 코사인과 동치 관계.
Z = linkage(mat_n, method='ward', metric='euclidean')


def assign(K):
    labels = fcluster(Z, t=K, criterion='maxclust')
    out = defaultdict(list)
    for eid, lab in zip(ent_ids, labels):
        out[int(lab) - 1].append(eid)  # 0..K-1
    return dict(out)


c10 = assign(10)
c5 = assign(5)

eid_to_c10 = {e: cid for cid, eids in c10.items() for e in eids}


# === 타입 버킷 (exp5 probe와 같은 매핑, 통계 일관성 위해) ===
KEEP = [
    ('인물', ['인물', '권력자', '군인']),
    ('사건/전쟁', ['사건', '전쟁', '전투']),
    ('문헌/저서/기록', ['문서', '문헌', '저서', '문집', '법전', '문학작품', '공문서', '기록']),
    ('발명품/기기', ['과학기기', '발명품', '기기']),
    ('문화재/작품', ['문화재', '문화유산', '기념물', '건축물']),
]
DEMOTE = [
    ('지역/지리', ['지역', '지리', '장소', '지명', '행정 구역']),
    ('국가', ['국가', '민족', '왕조']),
    ('시대', ['시대', '시기']),
    ('일반개념/사상', ['개념', '사상', '이념', '학문', '윤리']),
    ('집단/계층', ['집단', '계층', '구성원']),
]


def bucket(typ):
    for name, kws in KEEP:
        if any(kw in typ for kw in kws):
            return name
    for name, kws in DEMOTE:
        if any(kw in typ for kw in kws):
            return name
    return 'unknown'


# === 비교: stage2_emb_K10.json (community 병합) ===
emb_K10 = json.loads((EXP5 / 'stage2_emb_K10.json').read_text(encoding='utf-8'))
prev_buildings = []
for b in emb_K10['merged_rooms']:
    eids, seen = [], set()
    for cnum in b['members']:
        for e in cnum_to_eids[cnum]:
            if e not in seen:
                seen.add(e); eids.append(e)
    prev_buildings.append({'id': b['new_id'], 'eids': eids})

huge = max(prev_buildings, key=lambda b: len(b['eids']))


# === 앵커 ===
ANCHORS = {
    '세종-과학': ['세종', '집현전', '측우기', '자격루', '혼천의', '앙부일구', '훈민정음', '장영실', '김종서', '최윤덕'],
    '임진왜란': ['임진왜란', '이순신', '권율', '김시민', '곽재우', '거북선', '정유재란', '선조'],
    '실학': ['정약용', '박지원', '박제가', '유형원', '이익', '홍대용', '실학'],
}

title_to_id = {}
for eid, r in ent.iterrows():
    title_to_id.setdefault(str(r['title']), eid)


# === stdout 요약 ===
direct_K10_sizes = sorted([len(c10[k]) for k in c10], reverse=True)
direct_K5_sizes = sorted([len(c5[k]) for k in c5], reverse=True)
prev_sizes = sorted([len(b['eids']) for b in prev_buildings], reverse=True)
print('=== 크기 분포 ===')
print(f'  직접 K=10 (357): {direct_K10_sizes}')
print(f'  직접 K=5  (357): {direct_K5_sizes}')
print(f'  병합 K=10 (326): {prev_sizes}')

print('\n=== 거대 건물 분산 ===')
print(f'  병합 최대 건물 {huge["id"]} (size={len(huge["eids"])}) 멤버가 직접 K=10에서:')
huge_dist = Counter(eid_to_c10[e] for e in huge['eids'])
for cid, n in huge_dist.most_common():
    print(f'    클러스터 {cid}: {n}명')

print('\n=== 앵커 응집 ===')
for theme, names in ANCHORS.items():
    cids = []
    for name in names:
        eid = title_to_id.get(name)
        if eid is None:
            continue
        cids.append(eid_to_c10[eid])
    cnt = Counter(cids)
    if cnt:
        mode_c, mode_n = cnt.most_common(1)[0]
        n_total = len(cids)
        n_found = n_total
        not_found = len(names) - n_total
        print(f'  {theme}: 모드 클러스터 {mode_c}에 {mode_n}/{n_found} (not-found {not_found})')

print('\n=== orphan 분포 ===')
orphan_dist = Counter(eid_to_c10[e] for e in orphan_eids)
for cid, n in orphan_dist.most_common():
    print(f'  클러스터 {cid}: orphan {n}개')


# === 리포트 ===
md = []
md.append('# exp6 — 방 토대 프로브: 직접 엔티티 클러스터 vs community 병합')
md.append('')
md.append('베이스: `repro_run3` (357 엔티티, 31 orphan 포함). 비교 대상: `results/exp5/stage2_emb_K10.json`. 임베딩: lancedb `entity_description` (1536-dim, L2 정규화 후 scipy ward euclidean).')
md.append('')
md.append('질문: 방을 graph community 대신 엔티티 임베딩으로 직접 클러스터하면 (1) orphan 녹나, (2) 거대 덩어리 갈라지나, (3) 묶음이 주제별이냐 타입별이냐.')
md.append('')

# --- 1 ---
md.append('## 1. 직접 클러스터 K=10 — 멤버·타입 분포')
md.append('')
for cid in sorted(c10.keys()):
    eids = c10[cid]
    n = len(eids)
    n_orphan = sum(1 for e in eids if e in orphan_eids)
    md.append(f'### 클러스터 {cid} (size={n}, orphan={n_orphan})')
    md.append('')
    buckets = Counter(bucket(str(ent.loc[e, 'type'])) for e in eids)
    md.append('**타입 버킷 분포**')
    md.append('')
    md.append('| 버킷 | 개수 |')
    md.append('|---|---|')
    for bname, bn in buckets.most_common():
        md.append(f'| {bname} | {bn} |')
    md.append('')
    md.append('**멤버 (degree 내림차순, orphan=Y)**')
    md.append('')
    md.append('| title | type | degree | orphan |')
    md.append('|---|---|---|---|')
    rows = []
    for e in eids:
        r = ent.loc[e]
        rows.append((str(r['title']), str(r['type']), int(r['degree']), 'Y' if e in orphan_eids else ''))
    rows.sort(key=lambda x: (-x[2], x[0]))
    for title, typ, deg, o in rows:
        md.append(f'| {title} | {typ} | {deg} | {o} |')
    md.append('')

# --- 2 ---
md.append('## 2. 크기 분포 비교')
md.append('')
md.append('| 방법 | K | 분모 | 크기 분포 (내림차순) |')
md.append('|---|---|---|---|')
md.append(f'| 직접 클러스터 (357 엔티티 ward) | 10 | 357 | {direct_K10_sizes} |')
md.append(f'| 직접 클러스터 (357 엔티티 ward) | 5  | 357 | {direct_K5_sizes} |')
md.append(f'| community 병합 (stage2_emb_K10) | 10 | 326 (orphan 제외) | {prev_sizes} |')
md.append('')

# --- 3 ---
md.append('## 3. community 병합 거대 건물 멤버 → 직접 클러스터에선?')
md.append('')
md.append(f'community 병합 최대 건물: **건물 {huge["id"]} (size={len(huge["eids"])})**. 그 멤버들이 직접 K=10에서 한 곳에 남는지(임베딩 자체가 뭉치는 신호) 흩어지는지(graph 탓) 본다.')
md.append('')
md.append('| 직접 클러스터 | 거대 건물 멤버 수 |')
md.append('|---|---|')
for cid, n in huge_dist.most_common():
    md.append(f'| {cid} | {n} |')
md.append('')

# --- 4 ---
md.append('## 4. 주제 응집 프로브 (앵커)')
md.append('')
md.append('각 멤버가 들어간 K=10 클러스터 ID. 모드(최빈) 비율이 높으면 응집, 분산되면 X.')
md.append('')
for theme, names in ANCHORS.items():
    md.append(f'### {theme}')
    md.append('')
    md.append('| name | 클러스터 | degree | orphan | type |')
    md.append('|---|---|---|---|---|')
    cids = []
    for name in names:
        eid = title_to_id.get(name)
        if eid is None:
            md.append(f'| {name} | not-found | - | - | - |')
            continue
        cid = eid_to_c10[eid]
        cids.append(cid)
        r = ent.loc[eid]
        o = 'Y' if eid in orphan_eids else ''
        md.append(f'| {name} | {cid} | {int(r["degree"])} | {o} | {str(r["type"])} |')
    md.append('')
    if cids:
        cnt = Counter(cids)
        mode_c, mode_n = cnt.most_common(1)[0]
        md.append(f'**모드 클러스터 {mode_c}: {mode_n}/{len(cids)}** (not-found 제외)')
    md.append('')

# --- 5 ---
md.append('## 5. orphan 31개 — 직접 클러스터 어디에 묶이나')
md.append('')
md.append('| orphan | type | 클러스터 | 그 클러스터 size | 같은 클러스터 다른 멤버 (degree 큰 5명) |')
md.append('|---|---|---|---|---|')
for oid in sorted(orphan_eids, key=lambda e: str(ent.loc[e, 'title'])):
    title = str(ent.loc[oid, 'title'])
    typ = str(ent.loc[oid, 'type'])
    cid = eid_to_c10[oid]
    cluster_eids = c10[cid]
    others = [e for e in cluster_eids if e != oid]
    others_sorted = sorted(others, key=lambda e: -int(ent.loc[e, 'degree']))[:5]
    others_titles = ', '.join(str(ent.loc[e, 'title']) for e in others_sorted)
    md.append(f'| {title} | {typ} | {cid} | {len(cluster_eids)} | {others_titles} |')
md.append('')
md.append('### orphan 클러스터별 집계')
md.append('')
md.append('| 클러스터 | orphan 개수 |')
md.append('|---|---|')
for cid, n in orphan_dist.most_common():
    md.append(f'| {cid} | {n} |')
md.append('')

target = OUT / 'report.md'
target.write_text('\n'.join(md), encoding='utf-8')
print(f'\nsaved: {target}')
