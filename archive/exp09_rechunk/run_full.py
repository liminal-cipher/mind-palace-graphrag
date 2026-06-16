"""exp9 step 2: proj_{semantic, pagesplit}/settings.yaml의 워크플로 allowlist를 그대로
써서 build_index를 돌린다 (create_community_reports만 빠진 풀 파이프라인).
완료된 run의 output을 results/snapshots/{semantic,pagesplit}_run1로 즉시 복사하고,
lancedb/entity_description 테이블에 1536-dim 벡터가 행 수만큼 들었는지 검증한다.
실패하면 그 자리에서 멈춤.
"""
from __future__ import annotations
import sys, io, os, asyncio, shutil, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path
import pandas as pd
import lancedb
from graphrag.config.load_config import load_config
from graphrag.api.index import build_index

REPO = Path.cwd().resolve()


async def run_one(root_dir: str, snap_rel: str, label: str) -> bool:
    os.chdir(REPO)
    root = (REPO / root_dir).resolve()
    print(f'\n=== {label} ({root}) ===')
    config = load_config(root)
    print(f'  workflows: {config.workflows}')
    print(f'  embed_text.names: {config.embed_text.names}')
    print(f'  output_storage: {config.output_storage.base_dir}')

    t0 = time.time()
    results = await build_index(config=config)
    elapsed = time.time() - t0
    failures = []
    for r in results:
        status = '-' if not r.error else f'error={r.error}'
        print(f'  workflow={r.workflow:<30} {status}')
        if r.error:
            failures.append((r.workflow, r.error))
    print(f'  total runtime: {elapsed:.1f}s')
    if failures:
        print(f'  [STOP] failed workflows: {failures}')
        return False

    out_base = Path(config.output_storage.base_dir)
    snap = REPO / snap_rel
    if snap.exists():
        shutil.rmtree(snap)
    shutil.copytree(out_base, snap)
    print(f'  snapshot: {snap}')

    ent_path = snap / 'entities.parquet'
    if not ent_path.exists():
        print(f'  [STOP] entities.parquet missing in snapshot')
        return False
    ent = pd.read_parquet(ent_path)
    n_ent = len(ent)
    print(f'  entities: {n_ent}')

    ldb_dir = snap / 'lancedb'
    if not (ldb_dir / 'entity_description.lance').exists():
        print(f'  [STOP] lancedb/entity_description.lance missing')
        return False
    db = lancedb.connect(str(ldb_dir))
    if 'entity_description' not in db.table_names():
        print(f'  [STOP] entity_description table missing in lancedb')
        return False
    tbl = db.open_table('entity_description').to_pandas()
    n_vec = len(tbl)
    dim = len(tbl['vector'].iloc[0]) if n_vec else None
    if dim != 1536:
        print(f'  [STOP] entity_description vector dim={dim} (expected 1536)')
        return False
    if n_vec != n_ent:
        print(f'  [STOP] entity_description rows={n_vec} != entities {n_ent}')
        return False
    print(f'  OK: entity_description {n_vec} vectors x {dim} dims')
    return True


async def main():
    target = sys.argv[1] if len(sys.argv) > 1 else 'both'
    if target in ('semantic', 'both'):
        ok = await run_one('results/exp09_rechunk/proj_semantic', 'results/snapshots/semantic_run1', 'SEMANTIC')
        if not ok:
            print('\nSEMANTIC failed. halting before pagesplit.')
            sys.exit(2)
    if target in ('pagesplit', 'both'):
        ok = await run_one('results/exp09_rechunk/proj_pagesplit', 'results/snapshots/pagesplit_run1', 'PAGESPLIT')
        if not ok:
            print('\nPAGESPLIT failed.')
            sys.exit(3)
    print('\nall runs done.')


if __name__ == '__main__':
    asyncio.run(main())
