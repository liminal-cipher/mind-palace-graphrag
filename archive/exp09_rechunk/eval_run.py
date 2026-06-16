"""exp9 step 3: run별 eval.
입력: results/snapshots/{semantic,pagesplit}_run1 스냅샷 (entities + lancedb).
산출: results/exp09_rechunk/eval_{label}.json — 엔티티 수, orphan율(degree0),
ward K=10 클러스터 크기, 클러스터별 top-15 (degree 내림차순), 앵커 체크리스트.

앵커 (한국사 자료 기준):
- should-show: 측우기·자격루·앙부일구·혼천의·곽재우·이순신·거북선·훈민정음
- should-demote: 조선·백성·성리학·붕당정치

매칭은 title 정확 일치. 자료 차이로 should-show 일부가 missing일 수 있음 (보고만).
"""
from __future__ import annotations
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path
import numpy as np
import pandas as pd
import lancedb
from scipy.cluster.hierarchy import linkage, fcluster

REPO = Path('.').resolve()
OUT_DIR = REPO / 'results/exp09_rechunk'

SHOULD_SHOW = ['측우기', '자격루', '앙부일구', '혼천의',
               '곽재우', '이순신', '거북선', '훈민정음']
SHOULD_DEMOTE = ['조선', '백성', '성리학', '붕당정치']
K = 10
TOP_N = 15


def load_run(snap_rel: str):
    snap = REPO / snap_rel
    ent = pd.read_parquet(snap / 'entities.parquet')
    db = lancedb.connect(str(snap / 'lancedb'))
    tbl = db.open_table('entity_description').to_pandas()
    # entity_description.lance의 id는 entities.id와 동일 (UUID)
    return ent, tbl


def align_vectors(ent: pd.DataFrame, tbl: pd.DataFrame):
    """entities 순서에 맞춰 (mat, ent_ordered) 반환. lancedb id ↔ entity id 매칭.
    매칭 안 되는 엔티티가 있으면 ★ 표시하고 드롭."""
    vec_by_id = dict(zip(tbl['id'], tbl['vector']))
    rows = []
    missing = []
    for _, e in ent.iterrows():
        v = vec_by_id.get(e['id'])
        if v is None:
            missing.append(e['title'])
            continue
        rows.append((e['id'], e['title'], e['type'], e['degree'], v))
    if missing:
        print(f'  ★ vector missing for {len(missing)} entities (first 5: {missing[:5]})')
    df = pd.DataFrame(rows, columns=['id', 'title', 'type', 'degree', 'vector'])
    mat = np.stack(df['vector'].values).astype(np.float32)
    # L2 정규화 (cosine 거리 일관성)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    mat = mat / np.clip(norms, 1e-9, None)
    return mat, df


def cluster_ward(mat: np.ndarray, K: int):
    Z = linkage(mat, method='ward', metric='euclidean')
    labels = fcluster(Z, t=K, criterion='maxclust')
    return labels


def top_per_cluster(df: pd.DataFrame, labels: np.ndarray, K: int, n: int):
    df = df.assign(cluster=labels)
    out = []
    for k in sorted(df['cluster'].unique()):
        sub = df[df['cluster'] == k].sort_values(
            ['degree', 'title'], ascending=[False, True])
        out.append({
            'cluster': int(k),
            'size': int(len(sub)),
            'top': [
                {'title': r['title'], 'type': r['type'], 'degree': int(r['degree'])}
                for _, r in sub.head(n).iterrows()
            ],
        })
    return out


def anchor_check(df: pd.DataFrame, labels: np.ndarray, names: list[str]):
    df = df.assign(cluster=labels)
    by_title = df.set_index('title')
    result = []
    for name in names:
        if name in by_title.index:
            row = by_title.loc[name]
            # 동명 entity 여러 개 있을 수 있음 → 첫 행
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            result.append({
                'name': name,
                'status': 'present',
                'cluster': int(row['cluster']),
                'degree': int(row['degree']),
                'type': str(row['type']),
            })
        else:
            result.append({'name': name, 'status': 'missing'})
    return result


def eval_run(snap_rel: str, label: str):
    print(f'\n=== eval: {label} ({snap_rel}) ===')
    ent, tbl = load_run(snap_rel)
    n_ent = len(ent)
    n_orphan = int((ent['degree'] == 0).sum())
    orphan_pct = 100.0 * n_orphan / max(n_ent, 1)
    print(f'  entities: {n_ent}')
    print(f'  orphans (degree==0): {n_orphan} ({orphan_pct:.1f}%)')
    print(f'  lancedb entity_description rows: {len(tbl)}')

    mat, df = align_vectors(ent, tbl)
    print(f'  matrix: {mat.shape}')
    labels = cluster_ward(mat, K)
    clusters = top_per_cluster(df, labels, K, TOP_N)
    print(f'  ward K={K} cluster sizes: {[c["size"] for c in clusters]}')

    show = anchor_check(df, labels, SHOULD_SHOW)
    demote = anchor_check(df, labels, SHOULD_DEMOTE)
    show_present = [a for a in show if a['status'] == 'present']
    show_missing = [a for a in show if a['status'] == 'missing']
    demote_present = [a for a in demote if a['status'] == 'present']
    demote_missing = [a for a in demote if a['status'] == 'missing']
    print(f'  should-show present: {len(show_present)}/{len(SHOULD_SHOW)} '
          f'missing: {[a["name"] for a in show_missing]}')
    print(f'  should-demote present: {len(demote_present)}/{len(SHOULD_DEMOTE)} '
          f'missing: {[a["name"] for a in demote_missing]}')

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        'label': label,
        'snapshot': snap_rel,
        'entities': n_ent,
        'orphan_count': n_orphan,
        'orphan_pct': round(orphan_pct, 2),
        'ward_K': K,
        'cluster_sizes': [c['size'] for c in clusters],
        'clusters': clusters,
        'anchors_should_show': show,
        'anchors_should_demote': demote,
        'anchors_show_present_pct': round(100.0 * len(show_present) / len(SHOULD_SHOW), 1),
        'anchors_demote_present_pct': round(100.0 * len(demote_present) / len(SHOULD_DEMOTE), 1),
    }
    out_path = OUT_DIR / f'eval_{label}.json'
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding='utf-8')
    print(f'  wrote {out_path}')
    return payload


def main():
    targets = sys.argv[1:] or ['semantic_run1', 'pagesplit_run1']
    for lbl in targets:
        snap_rel = f'results/snapshots/{lbl}'
        if not (REPO / snap_rel).exists():
            print(f'★ snapshot missing: {snap_rel}')
            continue
        eval_run(snap_rel, lbl)


if __name__ == '__main__':
    main()
