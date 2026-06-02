"""실험 5 공통 라이브러리: 페이로드 빌더, 정렬, 검증, 슬롯 빌드."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
import numpy as np
import lancedb

BASE = Path('results/snapshots/repro_run3')
OUT = Path('results/exp5')
OUT.mkdir(parents=True, exist_ok=True)


def load_base():
    ent = pd.read_parquet(BASE / 'entities.parquet').set_index('id')
    com = pd.read_parquet(BASE / 'communities.parquet')
    rep = pd.read_parquet(BASE / 'community_reports.parquet')
    com_l0 = com[com['level'] == 0].copy().reset_index(drop=True)
    rep_l0 = rep[rep['level'] == 0].copy().reset_index(drop=True)
    return ent, com_l0, rep_l0


def build_room_payloads(ent, com_l0, rep_l0):
    rep_by_cnum = rep_l0.set_index('community')
    rooms = []
    for _, c in com_l0.iterrows():
        cnum = int(c['community'])
        r = rep_by_cnum.loc[cnum]
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
    blocks = []
    for r in rooms:
        b = (f"방 {r['community']} (size={r['size']}): {r['title']}\n"
             f"요약: {r['summary']}\n"
             f"멤버: {', '.join(r['members'])}")
        blocks.append(b)
    return "\n---\n".join(blocks)


def validate_grouping(merged_rooms, all_communities, K):
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
    """멤버 community 중 size 최대인 community의 title을 빌림."""
    sub = com_l0[com_l0['community'].isin(group_community_ids)].copy()
    largest_cnum = int(sub.sort_values('size', ascending=False).iloc[0]['community'])
    title = str(rep_l0[rep_l0['community'] == largest_cnum].iloc[0]['title'])
    return title, largest_cnum


def build_summary_a2(group_community_ids, rep_l0):
    """A2: 멤버 방의 title list."""
    titles = []
    for cnum in group_community_ids:
        t = str(rep_l0[rep_l0['community'] == cnum].iloc[0]['title'])
        titles.append(t)
    return "이 건물: " + ", ".join(titles)


def sort_loci(entities_df):
    """B1: degree↓, 동률은 title 사전순↑. 재현성 위해 함수 분리."""
    return entities_df.sort_values(['degree', 'title'],
                                   ascending=[False, True])


def build_slot_package(merged_rooms, ent, com_l0, rep_l0, *,
                       source_snapshot, method_label, K):
    """단계 3: stage2 결과 → 3D 슬롯 JSON."""
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
    """자기검증."""
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
