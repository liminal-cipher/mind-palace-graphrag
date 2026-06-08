"""exp9 입력 준비. input/ 의 원천을 GraphRAG가 그대로 먹는 JSON 객체 배열로 변환.
semantic은 의미 단위(semantic) export d['documents'] 그대로 꺼냄, pagesplit은 '--- page N ---'로 잘라
{text, page} 객체 배열로. 빈/짧은(<10) text 객체 제외.
입출력: input/* (원천, 읽기) → proj_semantic/input/semantic_docs.json,
       proj_pagesplit/input/pagesplit_docs.json (생성, gitignore에 걸려 결과만 따로 보관).
"""
from __future__ import annotations
import sys, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path

MIN_LEN = 10
OUT_SEM = Path('proj_semantic/input')
OUT_PAGE = Path('proj_pagesplit/input')
OUT_SEM.mkdir(parents=True, exist_ok=True)
OUT_PAGE.mkdir(parents=True, exist_ok=True)


# === semantic ===
src = json.loads(Path('input/history_joseon_semantic.json').read_text(encoding='utf-8'))
docs = src.get('documents', [])
kept = []
dropped = []
for d in docs:
    t = (d.get('text') or '').strip()
    if len(t) < MIN_LEN:
        dropped.append((d.get('chunk_id', '?'), len(t)))
        continue
    # 원천 보존: chunk_id, page, title, section_path, text 등 다 둠
    kept.append(d)

print(f'semantic: 원천 documents={len(docs)} kept={len(kept)} dropped={len(dropped)} (이유: len<{MIN_LEN})')
if dropped:
    for cid, n in dropped[:5]:
        print(f'  dropped: chunk_id={cid} len={n}')

(OUT_SEM / 'semantic_docs.json').write_text(
    json.dumps(kept, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'  written: {OUT_SEM/"semantic_docs.json"}')


# === pagesplit ===
txt = Path('input/history_joseon_pagesplit.txt').read_text(encoding='utf-8')
parts = re.split(r'---\s*page\s+(\d+)\s*---', txt)
pages_raw = []
for i in range(1, len(parts), 2):
    n = int(parts[i])
    body = parts[i + 1].strip() if i + 1 < len(parts) else ''
    pages_raw.append((n, body))

pages_kept = []
pages_drop = []
for n, body in pages_raw:
    if len(body) < MIN_LEN:
        pages_drop.append((n, len(body)))
        continue
    pages_kept.append({'page': n, 'text': body})

print(f'\npagesplit: 원천 pages={len(pages_raw)} kept={len(pages_kept)} dropped={len(pages_drop)} (이유: len<{MIN_LEN})')
if pages_drop:
    for n, ln in pages_drop[:5]:
        print(f'  dropped: page={n} len={ln}')

(OUT_PAGE / 'pagesplit_docs.json').write_text(
    json.dumps(pages_kept, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'  written: {OUT_PAGE/"pagesplit_docs.json"}')
