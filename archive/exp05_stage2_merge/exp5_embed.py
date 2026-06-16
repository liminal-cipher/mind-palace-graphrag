"""실험 5 stage2 임베딩 경로. level 0 community_full_content 벡터(40, 1536)를 scipy
hierarchical clustering으로 묶어 K=5/8/10 MergeResult를 만든다.

파이프라인 단계: stage2(병합). stage1 페이로드와 lancedb 벡터를 함께 입력으로 받는다.

방법: ward와 average 두 linkage를 다 돌려 K=8 silhouette이 더 좋은 쪽을 winner로 고르고,
같은 입력으로 두 번 돌려 결과가 동일한지(재현성) 확인한 뒤 저장한다.

핵심 입출력:
- 입력: results/snapshots/repro_run3/ (lancedb 포함).
- 출력: results/exp05_stage2_merge/stage2_emb_K{K}.json (winner 채택), stage2_emb_K8_alt_{loser}.json (비교용),
  embed_silhouette_summary.json (ward/average × K 매트릭스).
"""
from __future__ import annotations
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np
from scipy.cluster.hierarchy import linkage, fcluster
from sklearn.metrics import silhouette_score
from exp5_lib import (load_base, build_room_payloads, load_level0_vectors,
                      validate_grouping, save_json, OUT)


def compute_linkage(mat, method):
    """입력 행렬에 대해 linkage 행렬 Z를 만들어 반환한다.
    method는 'ward' 또는 'average'만 허용."""
    # ward는 알고리즘상 euclidean만 받는다. average는 코사인을 쓰는 게 임베딩에선 자연스럽다.
    if method == 'ward':
        return linkage(mat, method='ward', metric='euclidean')
    elif method == 'average':
        return linkage(mat, method='average', metric='cosine')
    raise ValueError(method)


def labels_to_groups(labels, cnums, K):
    """fcluster가 뱉은 (labels, cnums) 페어를 stage2 MergeResult 형식
    (merged_rooms 리스트)으로 변환한다. scipy 라벨은 1부터 시작하고 비연속일 수 있으니
    new_id 0..K-1로 재매핑한다."""
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
    """주어진 linkage 방법으로 K_list 각각에 대해 fcluster를 돌려
    K별 {silhouette, merged_rooms, validation, linkage_method} 딕셔너리를 만든다.
    linkage는 한 번만 계산하고 K별로 fcluster를 잘라 K_list 전체를 한 번에 평가한다."""
    Z = compute_linkage(mat, method)
    out = {}
    for K in K_list:
        labels = fcluster(Z, t=K, criterion='maxclust')
        # silhouette는 linkage 방법과 무관하게 cosine으로 통일. 입력 벡터가 L2 정규화돼 있어서
        # 코사인 거리 해석이 일관된다.
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
