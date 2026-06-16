"""실험 5 공통 라이브러리. 임베딩 경로와 LLM 경로가 같이 쓰는 데이터 로더, 페이로드 빌더,
검증, 3D 슬롯 빌더를 모은다.

파이프라인 단계:
- stage1 (방 페이로드): load_base + build_room_payloads + format_for_llm.
  repro_run3 스냅샷에서 RoomPayload 40개를 만들고 LLM 입력 텍스트로 직렬화한다.
- stage2 (병합): validate_grouping이 임베딩과 LLM 양쪽 결과를 같은 완전성 기준으로 검사한다.
- stage3 (3D 슬롯): build_slot_package가 stage2 MergeResult를 1인칭 3D용 슬롯 JSON으로 푼다.

입출력:
- 입력 베이스: results/snapshots/repro_run3 (entities.parquet, communities.parquet,
  community_reports.parquet, lancedb/). 이 스냅샷은 재추출 금지, 항상 입력으로만 쓴다.
- 출력 디렉터리: results/exp05_stage2_merge/.
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
import numpy as np
import lancedb

BASE = Path('results/snapshots/repro_run3')
OUT = Path('results/exp05_stage2_merge')
OUT.mkdir(parents=True, exist_ok=True)


def load_base():
    """repro_run3 스냅샷에서 entities, communities, community_reports를 읽고
    communities와 reports는 level 0만 추린 뒤 (ent, com_l0, rep_l0) 튜플로 반환.
    ent는 UUID id를 인덱스로 가진다."""
    ent = pd.read_parquet(BASE / 'entities.parquet').set_index('id')
    com = pd.read_parquet(BASE / 'communities.parquet')
    rep = pd.read_parquet(BASE / 'community_reports.parquet')
    # 같은 자료가 level 0/1/2 세 입자도로 들어 있다. "건물"은 level 0(가장 큰 묶음)만.
    com_l0 = com[com['level'] == 0].copy().reset_index(drop=True)
    rep_l0 = rep[rep['level'] == 0].copy().reset_index(drop=True)
    return ent, com_l0, rep_l0


def build_room_payloads(ent, com_l0, rep_l0):
    """stage1 산출. 각 level 0 방마다 RoomPayload 한 개를 만든다.
    필드: community(정수 ID), title, summary, size, members(degree 상위 10명).
    community 번호 오름차순으로 정렬해 반환한다."""
    # join 키는 정수 community 컬럼. report의 id 해시가 아니라 community 정수를 쓴다.
    rep_by_cnum = rep_l0.set_index('community')
    rooms = []
    for _, c in com_l0.iterrows():
        cnum = int(c['community'])
        r = rep_by_cnum.loc[cnum]
        # entity_ids는 UUID 리스트. ent는 UUID 인덱스라 .loc로 바로 조회 가능.
        eids = list(c['entity_ids'])
        members_df = ent.loc[eids].sort_values(
            ['degree', 'title'], ascending=[False, True])
        top = members_df.head(10) if len(members_df) > 10 else members_df
        rooms.append({
            'community': cnum,
            'title': str(r['title']),
            'summary': str(r['summary']),
            'size': int(c['size']),
            'members': top['title'].tolist(),
        })
    return sorted(rooms, key=lambda x: x['community'])


def format_for_llm(rooms):
    """RoomPayload 리스트를 LLM 입력용 단일 텍스트 블록으로 직렬화.
    블록 사이는 '---' 라인으로 구분한다. 임베딩 경로에서는 안 쓰고 LLM 경로에서만 사용."""
    blocks = []
    for r in rooms:
        b = (f"방 {r['community']} (size={r['size']}): {r['title']}\n"
             f"요약: {r['summary']}\n"
             f"멤버: {', '.join(r['members'])}")
        blocks.append(b)
    return "\n---\n".join(blocks)


def validate_grouping(merged_rooms, all_communities, K):
    """stage2 MergeResult가 community 40개를 정확히 K개 그룹으로 분할하는지 검증.
    ok=True 조건: 누락 0, 중복 0, 그룹 수 == K, 총 멤버 수 == community 수.
    임베딩 경로와 v1 LLM partition 경로가 공용한다. v2 assignment는 별도 검증을 쓴다."""
    assigned = []
    for g in merged_rooms:
        assigned.extend(g['members'])
    missing = set(all_communities) - set(assigned)
    dup = [x for x in assigned if assigned.count(x) > 1]
    ok = (not missing) and (not dup) and (len(merged_rooms) == K) \
         and (len(assigned) == len(all_communities))
    return {'ok': ok, 'missing': sorted(missing),
            'duplicate': sorted(set(dup)),
            'K_actual': len(merged_rooms)}


def load_level0_vectors(rep_l0):
    """lancedb의 community_full_content 테이블에서 level 0 방 임베딩만 골라
    (mat, cnums) 반환. mat은 (40, 1536) float32, cnums는 community 번호 오름차순.

    함정: 이 테이블은 level 0/1/2 전부 73행을 들고 있다. level 0 report id 리스트로
    필터해야 40행이 된다. 또한 lancedb의 키는 128자 해시 id이고 community 정수가 아니므로
    rep_l0의 id-to-community 매핑으로 변환한 뒤 community 번호로 정렬해야 cnums와
    행 순서가 맞는다."""
    db = lancedb.connect(str(BASE / 'lancedb'))
    com_lance = db.open_table('community_full_content').to_pandas()
    l0_ids = rep_l0['id'].tolist()
    vec_rows = com_lance[com_lance['id'].isin(l0_ids)].copy()
    # community 번호로 정렬 (id 매핑)
    id_to_cnum = dict(zip(rep_l0['id'], rep_l0['community']))
    vec_rows['community'] = vec_rows['id'].map(id_to_cnum)
    vec_rows = vec_rows.sort_values('community').reset_index(drop=True)
    mat = np.stack(vec_rows['vector'].values).astype(np.float32)
    cnums = vec_rows['community'].astype(int).tolist()
    return mat, cnums


# === 단계 3: borrow 이름 + 슬롯 빌드 ===
def borrow_name(group_community_ids, com_l0, rep_l0):
    """stage3 네이밍. 한 그룹(=건물)의 멤버 community 중 size가 가장 큰 community의
    title을 그대로 빌려 건물 이름으로 쓴다. 묶기와 네이밍을 분리하기 위한 규칙."""
    sub = com_l0[com_l0['community'].isin(group_community_ids)].copy()
    largest_cnum = int(sub.sort_values('size', ascending=False).iloc[0]['community'])
    title = str(rep_l0[rep_l0['community'] == largest_cnum].iloc[0]['title'])
    return title, largest_cnum


def build_summary_a2(group_community_ids, rep_l0):
    """stage3 빌딩 요약. 설계 결정 A2 채택: 멤버 방의 title 목록을 콤마로 이어
    한 줄 요약을 만든다."""
    titles = []
    for cnum in group_community_ids:
        t = str(rep_l0[rep_l0['community'] == cnum].iloc[0]['title'])
        titles.append(t)
    return "이 건물: " + ", ".join(titles)


def sort_loci(entities_df):
    """stage3 loci 순서. 설계 결정 B1 채택: degree 내림차순, 동률은 title 사전순.
    재현성을 위해 별도 함수로 뺐다."""
    return entities_df.sort_values(['degree', 'title'],
                                   ascending=[False, True])


def build_slot_package(merged_rooms, ent, com_l0, rep_l0, *,
                       source_snapshot, method_label, K):
    """stage3 산출. stage2 MergeResult를 3D 인테리어 빌더가 그대로 먹을 수 있는
    슬롯 JSON으로 변환한다. 각 그룹은 빌딩 하나가 되며 멤버 entity는 loci로 들어간다.
    relationships는 사용하지 않는다(설계 결정 C)."""
    buildings = []
    for g in merged_rooms:
        members = g['members']
        name, borrow_from = borrow_name(members, com_l0, rep_l0)
        summary = build_summary_a2(members, rep_l0)

        # 멤버 community들의 entity_ids 통합 (중복 제거, 순서 보존)
        all_eids = []
        seen = set()
        for cnum in members:
            crow = com_l0[com_l0['community'] == cnum].iloc[0]
            for eid in crow['entity_ids']:
                if eid not in seen:
                    seen.add(eid)
                    all_eids.append(eid)

        members_df = ent.loc[all_eids]
        sorted_df = sort_loci(members_df)
        loci = []
        for order, (eid, m) in enumerate(sorted_df.iterrows(), start=1):
            loci.append({
                'order': order,
                'concept': str(m['title']),
                'desc': str(m['description']),
                'entity_id': str(eid),
                'type': str(m['type']),
                'degree': int(m['degree']),
            })

        buildings.append({
            'id': int(g['new_id']),
            'name': name,
            'name_borrowed_from_community': borrow_from,
            'llm_suggested_title': g.get('llm_suggested_title'),
            'summary': summary,
            'size': len(loci),
            'source_rooms': sorted(members),
            'loci': loci,
        })

    buildings = sorted(buildings, key=lambda b: b['id'])

    return {
        'version': '1.0',
        'source': {
            'snapshot': source_snapshot,
            'method': method_label,
            'K': K,
            'entities_total': int(len(ent)),
        },
        'generated_at': pd.Timestamp.now(tz='UTC').isoformat(),
        'buildings': buildings,
    }


def selfcheck(slot_pkg, all_communities, K):
    """stage3 자기검증. 빌딩 수가 K와 맞는지, community가 빠짐없이 정확히 한 번씩
    배정됐는지, loci 총수가 entities 총수와 일치하는지를 확인해 dict로 돌려준다."""
    assigned_cnums = []
    total_loci = 0
    for b in slot_pkg['buildings']:
        assigned_cnums.extend(b['source_rooms'])
        total_loci += len(b['loci'])
    cnum_set = set(assigned_cnums)
    checks = {
        'K_match': len(slot_pkg['buildings']) == K,
        'all_communities_assigned': cnum_set == set(all_communities),
        'no_duplicate_community': len(assigned_cnums) == len(cnum_set),
        'loci_total_match_entities': total_loci == slot_pkg['source']['entities_total'],
        'total_loci': total_loci,
        'missing': sorted(set(all_communities) - cnum_set),
        'duplicate': sorted([c for c in assigned_cnums if assigned_cnums.count(c) > 1]),
    }
    checks['all_ok'] = all([
        checks['K_match'], checks['all_communities_assigned'],
        checks['no_duplicate_community'], checks['loci_total_match_entities'],
    ])
    return checks


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2),
                          encoding='utf-8')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))
