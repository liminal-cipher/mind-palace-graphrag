"""exp8 목차 방 feasibility 프로브. repro_run3가 인덱싱한 원문(국사교과서_조선_본문_정제.txt)에서
헤더로 섹션 잘라, text_unit → 섹션 → 엔티티 사슬 매핑이 되는지 / 그 분포가 방으로 쓸 만한지 확인.

입력: input/국사교과서_조선_본문_정제.txt, repro_run3/text_units.parquet, entities.parquet.
출력: results/exp08_toc_feasibility/report.md.
"""
from __future__ import annotations
import sys, io, re, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path
from collections import Counter, defaultdict
import pandas as pd

ROOT = Path('.')
BASE = Path('results/snapshots/repro_run3')
TXT_PATH = Path('input/국사교과서_조선_본문_정제.txt')
OUT = Path('results/exp08_toc_feasibility')
OUT.mkdir(parents=True, exist_ok=True)


text = TXT_PATH.read_text(encoding='utf-8')
lines = text.split('\n')


# === 헤더 파싱 ===
# 3단:
#   roman: 라인 시작이 로마숫자 + "."  ("V. ...")
#   number: 라인 시작이 숫자 + "."  ("1. ...")
#   sub: 빈 줄로 둘러싸인 짧은 줄(≤30자) 중 한국어 문장 종결(다/요/음/오/지/네/까/까요/까?) 없는 것
ROMAN_RE = re.compile(r'^[IVXLCDM]+\.\s*\S')
NUMBER_RE = re.compile(r'^\d+\.\s*\S')
# 문장 종결 휴리스틱: 마지막 두 글자에 종결 어미 흔적이 있나
END_TOKENS = ('다.', '다', '요.', '요', '음.', '음', '오.', '오',
              '오.', '었다', '였다', '한다', '였음', '음.', '?', '!',
              '입니다', '입니다.')


def is_sentence(s):
    s = s.strip()
    if not s: return False
    if s.endswith('.') or s.endswith('?') or s.endswith('!'):
        return True
    # 받침 다·요·음·오로 끝
    if s[-1] in '다요음오':
        return True
    return False


def classify_line(i):
    """헤더 종류 반환 또는 None."""
    s = lines[i]
    if not s.strip():
        return None
    stripped = s.strip()
    if ROMAN_RE.match(stripped):
        return 'roman'
    if NUMBER_RE.match(stripped):
        return 'number'
    prev_blank = (i == 0) or (not lines[i-1].strip())
    next_blank = (i == len(lines)-1) or (not lines[i+1].strip())
    if prev_blank and next_blank and len(stripped) <= 30 and not is_sentence(stripped):
        # 추가 안전장치: 콤마 없음 (본문 한 줄 짜리 방어)
        if ',' not in stripped and '.' not in stripped:
            return 'sub'
    return None


headers = []  # [{'line': i, 'type': 'roman|number|sub', 'title': str, 'char_start': int}]
# char offset per line
char_offsets = []
acc = 0
for ln in lines:
    char_offsets.append(acc)
    acc += len(ln) + 1  # +1 for newline

for i in range(len(lines)):
    kind = classify_line(i)
    if kind:
        headers.append({'line': i, 'type': kind, 'title': lines[i].strip(),
                        'char_start': char_offsets[i]})

print(f'=== 헤더 {len(headers)}개 ===')
for h in headers:
    print(f'  line {h["line"]:>4} [{h["type"]:<6}] {h["title"]}')


# === 섹션 빌드 (모든 헤더 기준; 다음 헤더 전까지) ===
sections = []  # [{'idx', 'title', 'type', 'char_start', 'char_end', 'breadcrumb'}]
last_roman = None
last_number = None
for idx, h in enumerate(headers):
    char_end = headers[idx+1]['char_start'] if idx+1 < len(headers) else len(text)
    if h['type'] == 'roman':
        last_roman = h['title']
    elif h['type'] == 'number':
        last_number = h['title']
    breadcrumb_parts = []
    if last_roman: breadcrumb_parts.append(last_roman)
    if last_number and h['type'] != 'roman': breadcrumb_parts.append(last_number)
    if h['type'] == 'sub': breadcrumb_parts.append(h['title'])
    breadcrumb = ' > '.join(breadcrumb_parts)
    sections.append({
        'idx': idx, 'title': h['title'], 'type': h['type'],
        'char_start': h['char_start'], 'char_end': char_end,
        'breadcrumb': breadcrumb,
        'length': char_end - h['char_start'],
    })


# === text_unit → 섹션 매핑 ===
tu_df = pd.read_parquet(BASE / 'text_units.parquet')
print(f'\n=== text_units {len(tu_df)}개 ===')

# 각 text_unit의 원문 위치 추정: 앞쪽 100자로 검색
tu_records = []
for _, r in tu_df.iterrows():
    utext = str(r['text'])
    needle = utext[:100].strip()
    pos = text.find(needle) if needle else -1
    if pos < 0:
        # 다시 시도: 첫 50자
        needle = utext[:50].strip()
        pos = text.find(needle) if needle else -1
    if pos < 0:
        print(f'  unit {r["human_readable_id"]}: ★원문에서 못 찾음★ len={len(utext)}')
        tu_records.append({'id': r['id'], 'hr_id': int(r['human_readable_id']),
                          'char_start': -1, 'char_end': -1, 'sections': []})
        continue
    tu_records.append({'id': r['id'], 'hr_id': int(r['human_readable_id']),
                      'char_start': pos, 'char_end': pos + len(utext), 'sections': []})

# 정렬해 위치 확인용
tu_records.sort(key=lambda x: x['hr_id'])
for tr in tu_records:
    if tr['char_start'] < 0:
        continue
    # 이 unit이 닿는 섹션들 (overlap > 0)
    overlap = []
    for s in sections:
        if tr['char_start'] < s['char_end'] and tr['char_end'] > s['char_start']:
            overlap.append(s['idx'])
    tr['sections'] = overlap

print('\ntext_unit → 섹션 분포:')
for tr in tu_records:
    print(f'  unit {tr["hr_id"]:>2} [{tr["char_start"]:>5}..{tr["char_end"]:>5}] → 섹션 {tr["sections"]}')


# === 섹션별 text_unit 수 ===
sec_to_units = defaultdict(set)
for tr in tu_records:
    for sidx in tr['sections']:
        sec_to_units[sidx].add(tr['hr_id'])


# === 엔티티 → 섹션 (text_unit_ids 따라가서 union) ===
ent = pd.read_parquet(BASE / 'entities.parquet').set_index('id')
unit_id_to_sections = {tr['id']: set(tr['sections']) for tr in tu_records}

ent_sections = {}  # eid → set[sec_idx]
for eid, r in ent.iterrows():
    uids = list(r['text_unit_ids']) if r['text_unit_ids'] is not None else []
    secs = set()
    for uid in uids:
        secs |= unit_id_to_sections.get(uid, set())
    ent_sections[eid] = secs

# 섹션별 엔티티 수
sec_to_ents = defaultdict(set)
for eid, secs in ent_sections.items():
    for s in secs:
        sec_to_ents[s].add(eid)


# === 1섹션 vs 다섹션 ===
n_zero = sum(1 for e, s in ent_sections.items() if len(s) == 0)
n_one = sum(1 for e, s in ent_sections.items() if len(s) == 1)
n_multi = sum(1 for e, s in ent_sections.items() if len(s) >= 2)
multi_counts = [len(s) for e, s in ent_sections.items() if len(s) >= 2]
avg_multi = sum(multi_counts) / len(multi_counts) if multi_counts else 0
print(f'\n=== 엔티티 섹션 분포 (총 {len(ent_sections)}) ===')
print(f'  0 섹션: {n_zero}')
print(f'  1 섹션: {n_one}')
print(f'  2+ 섹션: {n_multi} (평균 {avg_multi:.2f})')

# 섹션 → 엔티티 수 분포
sec_ent_counts = sorted([(s['idx'], len(sec_to_ents[s['idx']])) for s in sections],
                        key=lambda x: -x[1])
print(f'\n=== 섹션별 엔티티 수 분포 ===')
for sidx, n in sec_ent_counts:
    s = sections[sidx]
    n_units = len(sec_to_units[sidx])
    print(f'  [{s["type"]:<6}] sec {sidx:>2} ({n_units} units, {n:>3} ents): {s["breadcrumb"]}')


# === 스팟체크 ===
SPOTS = ['측우기', '자격루', '혼천의', '앙부일구', '이순신', '임진왜란',
         '권율', '김시민', '정도전', '이성계', '훈민정음', '거북선',
         '세종', '광해군', '정약용']
title_to_id = {}
for eid, r in ent.iterrows():
    title_to_id.setdefault(str(r['title']), eid)

print('\n=== 스팟체크 ===')
spot_rows = []
for name in SPOTS:
    eid = title_to_id.get(name)
    if eid is None:
        spot_rows.append({'name': name, 'status': 'not-found', 'sections': '-', 'breadcrumbs': '-'})
        continue
    secs = sorted(ent_sections.get(eid, set()))
    breadcrumbs = ' || '.join(sections[s]['breadcrumb'] for s in secs)
    spot_rows.append({'name': name, 'status': 'ok',
                      'sections': str(secs), 'breadcrumbs': breadcrumbs})
    print(f'  {name:<6}: 섹션 {secs} / {breadcrumbs[:100]}')


# === report.md ===
md = []
md.append('# exp8 — 목차 방 feasibility')
md.append('')
md.append(f'베이스: `{TXT_PATH}` (전체 {len(text)}자), `{BASE}/text_units.parquet` ({len(tu_df)} units), `entities.parquet` ({len(ent)} entities). PDF팀 구조 보존 없이 지금 원문 + repro_run3만으로 목차 → 섹션 → 엔티티 사슬이 잡히나.')
md.append('')

md.append('## 1. 헤더 파싱 — 섹션 목록')
md.append('')
md.append(f'총 헤더 {len(headers)}개 (roman={sum(1 for h in headers if h["type"]=="roman")}, number={sum(1 for h in headers if h["type"]=="number")}, sub={sum(1 for h in headers if h["type"]=="sub")}).')
md.append('')
md.append('| sec | type | title (breadcrumb 포함) | char span | length |')
md.append('|---|---|---|---|---|')
for s in sections:
    md.append(f'| {s["idx"]} | {s["type"]} | {s["breadcrumb"]} | {s["char_start"]}-{s["char_end"]} | {s["length"]} |')
md.append('')

md.append('## 2. text_unit별 섹션 매핑')
md.append('')
md.append(f'unit은 1200 토큰 단위 청크라 섹션 경계를 가로지른다. unit이 닿는 섹션은 다 기록.')
md.append('')
md.append('| unit | char_start | char_end | overlap 섹션들 |')
md.append('|---|---|---|---|')
for tr in tu_records:
    md.append(f'| {tr["hr_id"]} | {tr["char_start"]} | {tr["char_end"]} | {tr["sections"]} |')
md.append('')

md.append('## 3. 섹션별 text_unit 수와 엔티티 수')
md.append('')
md.append('| sec | type | breadcrumb | text_unit 수 | 엔티티 수 |')
md.append('|---|---|---|---|---|')
for s in sections:
    md.append(f'| {s["idx"]} | {s["type"]} | {s["breadcrumb"]} | {len(sec_to_units[s["idx"]])} | {len(sec_to_ents[s["idx"]])} |')
md.append('')

md.append('## 4. 엔티티 — 몇 개 섹션에 걸치나')
md.append('')
md.append(f'총 {len(ent_sections)}개 엔티티 중:')
md.append('')
md.append('| 섹션 수 | 엔티티 수 | 비율 |')
md.append('|---|---|---|')
md.append(f'| 0 (매핑 실패) | {n_zero} | {n_zero/len(ent_sections)*100:.1f}% |')
md.append(f'| 1 (단일 섹션) | {n_one} | {n_one/len(ent_sections)*100:.1f}% |')
md.append(f'| 2+ (다중 섹션) | {n_multi} | {n_multi/len(ent_sections)*100:.1f}% |')
md.append('')
md.append(f'**2+ 그룹 평균 섹션 수: {avg_multi:.2f}**')
md.append('')
# 다중 분포 히스토그램
multi_hist = Counter(multi_counts)
md.append('다중 섹션 분포:')
md.append('')
md.append('| 걸치는 섹션 수 | 엔티티 수 |')
md.append('|---|---|')
for k in sorted(multi_hist.keys()):
    md.append(f'| {k} | {multi_hist[k]} |')
md.append('')

md.append('## 5. 스팟체크')
md.append('')
md.append('| name | 상태 | 섹션 idx | breadcrumb |')
md.append('|---|---|---|---|')
for row in spot_rows:
    md.append(f'| {row["name"]} | {row["status"]} | {row["sections"]} | {row["breadcrumbs"]} |')
md.append('')

target = OUT / 'report.md'
target.write_text('\n'.join(md), encoding='utf-8')
print(f'\nsaved: {target}')
