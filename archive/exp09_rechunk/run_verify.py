"""exp9 무료 사전검증. proj_*/settings.yaml의 워크플로를 메모리에서
[load_input_documents, create_base_text_units]로 좁혀 GraphRAG를 돌린 뒤
text_units.parquet 행 수가 입력 객체 수랑 맞는지 본다. LLM 호출 없음.
"""
from __future__ import annotations
import sys, io, os, asyncio
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path
import pandas as pd
from graphrag.config.load_config import load_config
from graphrag.api.index import build_index

CWD_FIXED = Path.cwd().resolve()

VERIFY_WORKFLOWS = ['load_input_documents', 'create_base_text_units']


async def verify(root_dir: str, expected: int, label: str):
    os.chdir(CWD_FIXED)
    root = (CWD_FIXED / root_dir).resolve()
    print(f'\n=== {label} ({root}) ===')
    config = load_config(root)
    # 워크플로 좁히기
    config.workflows = VERIFY_WORKFLOWS
    # 임베딩도 비워 LLM·임베딩 API 호출 0
    config.embed_text.names = []

    print(f'  workflows override: {config.workflows}')
    print(f'  input_storage: {config.input_storage.base_dir}')
    print(f'  output_storage: {config.output_storage.base_dir}')

    results = await build_index(config=config)
    for r in results:
        ok = '-' if not r.error else f'error={r.error}'
        print(f'  workflow={r.workflow:<30} {ok}')

    # config.output_storage.base_dir은 load_config가 절대경로로 풀어둠
    out_base = Path(config.output_storage.base_dir)
    tu_path = out_base / 'text_units.parquet'
    print(f'  text_units path: {tu_path}')
    if not tu_path.exists():
        print(f'  ★ text_units.parquet 없음')
        return None
    df = pd.read_parquet(tu_path)
    n = len(df)
    match = '✓' if n == expected else '✗'
    print(f'  text_units rows = {n} (기대 {expected}) {match}')
    return n


async def main():
    sem = await verify('results/exp09_rechunk/proj_semantic', expected=105, label='semantic verify')
    page = await verify('results/exp09_rechunk/proj_pagesplit', expected=50, label='pagesplit verify')
    print('\n=== SUMMARY ===')
    print(f'  semantic  text_units = {sem} (기대 105)')
    print(f'  pagesplit text_units = {page} (기대 50)')
    if sem == 105 and page == 50:
        print('  → 둘 다 통과')
    else:
        print('  → 불일치. chunks.size 더 키워야 할 수도')


if __name__ == '__main__':
    asyncio.run(main())
