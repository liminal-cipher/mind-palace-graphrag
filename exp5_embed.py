"""실험 5 경로 2: 임베딩 병합. scipy hierarchical. ward/average 비교, K=5,8,10."""
from __future__ import annotations
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np
from scipy.cluster.hierarchy import linkage, fcluster
from sklearn.metrics import silhouette_score
from exp5_lib import (load_base, build_room_payloads, load_level0_vectors,
                      validate_grouping, save_json, OUT)


def compute_linkage(mat, method):
    # ward는 euclidean 강제, average는 cosine 권장
    if method == 'ward':
        return linkage(mat, method='ward', metric='euclidean')
    elif method == 'average':
        return linkage(mat, method='average', metric='cosine')
    raise ValueError(method)


def labels_to_groups(labels, cnums, K):
    groups = {}
    for cnum, lab in zip(cnums, labels):
        groups.setdefault(int(lab), []).append(int(cnum))
    # new_id: 0..K-1로 재매핑 (label 정렬)
    ordered_labels = sorted(groups.keys())
    merged_rooms = []
    for new_id, lab in enumerate(ordered_labels):
        merged_rooms.append({
            'new_id': new_id,
            'members': sorted(groups[lab]),
            'llm_suggested_title': None,
        })
    return merged_rooms


def evaluate_method(mat, cnums, method, K_list, all_cnums):
    Z = compute_linkage(mat, method)
    out = {}
    for K in K_list:
        labels = fcluster(Z, t=K, criterion='maxclust')
        # silhouette는 항상 cosine (벡터가 normalized라 의미 일관)
        sil = float(silhouette_score(mat, labels, metric='cosine'))
        merged_rooms = labels_to_groups(labels, cnums, K)
        v = validate_grouping(merged_rooms, all_cnums, K)
        out[K] = {'silhouette': sil, 'merged_rooms': merged_rooms,
                  'validation': v, 'linkage_method': method}
    return out


if __name__ == '__main__':
    ent, com_l0, rep_l0 = load_base()
    rooms = build_room_payloads(ent, com_l0, rep_l0)
    all_cnums = [r['community'] for r in rooms]
    print(f'rooms: {len(rooms)}')

    mat, cnums = load_level0_vectors(rep_l0)
    print(f'embed matrix: {mat.shape}, L2 norm sample: {np.linalg.norm(mat[:3], axis=1)}')
    # cnums와 rooms의 community 순서가 일치하는지
    assert cnums == sorted(all_cnums), 'community 순서 불일치'

    K_LIST = [5, 8, 10]
    METHODS = ['ward', 'average']

    # 두 방법 비교 → silhouette 좋은 쪽 선택
    print('\n=== ward vs average silhouette ===')
    per_method = {}
    for m in METHODS:
        per_method[m] = evaluate_method(mat, cnums, m, K_LIST, all_cnums)
        for K in K_LIST:
            print(f'  {m} K={K}: silhouette={per_method[m][K]["silhouette"]:.4f}, '
                  f'validation={per_method[m][K]["validation"]["ok"]}')

    # K=8 기준으로 더 좋은 쪽 선택
    best_method = max(METHODS, key=lambda m: per_method[m][8]['silhouette'])
    print(f'\nbest linkage (K=8 silhouette 기준): {best_method}')

    # 재현성: 같은 입력 두 번 → 같은 결과
    rep2 = evaluate_method(mat, cnums, best_method, K_LIST, all_cnums)
    for K in K_LIST:
        a = per_method[best_method][K]['merged_rooms']
        b = rep2[K]['merged_rooms']
        same = (a == b)
        print(f'재현성 (best={best_method}) K={K}: {"OK" if same else "DIFFER!"}')

    # 저장: best_method를 정식 채택, 다른 쪽도 비교용으로
    for K in K_LIST:
        winner = per_method[best_method][K]
        stage2 = {
            'method': f'emb_{best_method}_K{K}',
            'K': K,
            'linkage_method': best_method,
            'silhouette': winner['silhouette'],
            'merged_rooms': [
                {**g, 'silhouette': winner['silhouette']}
                for g in winner['merged_rooms']
            ],
        }
        save_json(OUT / f'stage2_emb_K{K}.json', stage2)
        print(f'\n=== emb_{best_method} K={K} ===')
        print(f'  silhouette: {winner["silhouette"]:.4f}')
        for g in winner['merged_rooms']:
            print(f'  new_id={g["new_id"]} | members={g["members"]}')

    # 비교용: 진 쪽도 K=8만 저장
    loser = 'average' if best_method == 'ward' else 'ward'
    save_json(OUT / f'stage2_emb_K8_alt_{loser}.json', {
        'method': f'emb_{loser}_K8_alt',
        'K': 8,
        'linkage_method': loser,
        'silhouette': per_method[loser][8]['silhouette'],
        'merged_rooms': per_method[loser][8]['merged_rooms'],
    })

    # silhouette 종합 표
    save_json(OUT / 'embed_silhouette_summary.json', {
        m: {K: per_method[m][K]['silhouette'] for K in K_LIST} for m in METHODS
    })
