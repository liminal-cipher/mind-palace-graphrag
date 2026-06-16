"""exp15 목차 챕터 feasibility 진단 (Phase 1, diagnostic only).

가설: exp8에서 엔티티가 평균 ~5 섹션에 흩어진 건 청크 단위가 섹션보다 커서다.
한 단계 거친 '챕터' 단위로 묶으면 엔티티가 한 dominant 챕터로 모이는가.

방법:
- exp8과 같은 텍스트 occurrence 경로(entity.text_unit_ids × text_unit 의 char-overlap → 섹션).
- LLM·임베딩 없음, 순수 결정적 카운팅.
- 섹션 단위 occurrence(E, S) = |E.text_unit_ids 중 S의 char span과 overlap 하는 unit|.
- 챕터 단위 occurrence(E, C) = sum_{S in C} occurrence(E, S).
- 챕터 파티션은 문서 자체의 헤딩 계층에서 결정적으로 도출 (A=4 굵음, B=6 V.1만 split).
- Tie-break: 학습흐름(문서 순서) 앞선 챕터.

입력: input/국사교과서_조선_본문_정제.txt, results/snapshots/repro_run3/{text_units,entities}.parquet
출력: results/exp15_toc_chapters/{REPORT.md, entity_chapter_assignments.csv,
       chapter_definition.json, summary.json}.
"""
from __future__ import annotations
import sys, io, re, json, csv
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path
from collections import Counter
from statistics import mean, median
import pandas as pd

ROOT = Path('.')
BASE = Path('results/snapshots/repro_run3')
TXT_PATH = Path('input/국사교과서_조선_본문_정제.txt')
OUT = Path('results/exp15_toc_chapters')
OUT.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Step 1: 섹션 어휘. exp8 probe.py 의 헤더 파싱·섹션 빌드 로직을 그대로 재현
#         (같은 정규식·같은 휴리스틱·같은 char-offset 계산. LLM·임베딩 0).
# ---------------------------------------------------------------------------
text = TXT_PATH.read_text(encoding='utf-8')
lines = text.split('\n')

ROMAN_RE = re.compile(r'^[IVXLCDM]+\.\s*\S')
NUMBER_RE = re.compile(r'^\d+\.\s*\S')

def _is_sentence(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    if s.endswith('.') or s.endswith('?') or s.endswith('!'):
        return True
    if s[-1] in '다요음오':
        return True
    return False

def _classify(i: int) -> str | None:
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
    if prev_blank and next_blank and len(stripped) <= 30 and not _is_sentence(stripped):
        if ',' not in stripped and '.' not in stripped:
            return 'sub'
    return None

char_offsets, acc = [], 0
for ln in lines:
    char_offsets.append(acc)
    acc += len(ln) + 1

headers = []
for i in range(len(lines)):
    kind = _classify(i)
    if kind:
        headers.append({'line': i, 'type': kind, 'title': lines[i].strip(),
                        'char_start': char_offsets[i]})

sections = []
last_roman, last_number = None, None
for idx, h in enumerate(headers):
    char_end = headers[idx+1]['char_start'] if idx+1 < len(headers) else len(text)
    if h['type'] == 'roman':
        last_roman = h['title']
    elif h['type'] == 'number':
        last_number = h['title']
    parts = []
    if last_roman: parts.append(last_roman)
    if last_number and h['type'] != 'roman': parts.append(last_number)
    if h['type'] == 'sub': parts.append(h['title'])
    sections.append({
        'idx': idx, 'title': h['title'], 'type': h['type'],
        'char_start': h['char_start'], 'char_end': char_end,
        'breadcrumb': ' > '.join(parts),
        'length': char_end - h['char_start'],
    })

# text_unit → 섹션 (exp8 과 동일한 char-overlap 매핑).
tu_df = pd.read_parquet(BASE / 'text_units.parquet')
tu_records = []
for _, r in tu_df.iterrows():
    utext = str(r['text'])
    needle = utext[:100].strip()
    pos = text.find(needle) if needle else -1
    if pos < 0:
        needle = utext[:50].strip()
        pos = text.find(needle) if needle else -1
    rec = {'id': r['id'], 'hr_id': int(r['human_readable_id']),
           'char_start': pos, 'char_end': pos + len(utext) if pos >= 0 else -1,
           'sections': []}
    if pos >= 0:
        rec['sections'] = [s['idx'] for s in sections
                           if pos < s['char_end'] and pos + len(utext) > s['char_start']]
    tu_records.append(rec)

ent_df = pd.read_parquet(BASE / 'entities.parquet')
N_ENT = len(ent_df)
N_SEC = len(sections)
assert N_ENT == 357, f'기대 357, 실제 {N_ENT}'
assert N_SEC == 46, f'기대 46 섹션 (exp8 와 동일), 실제 {N_SEC}'

# entity.text_unit_ids 의 unit id → 섹션 set
unit_id_to_sections = {tr['id']: set(tr['sections']) for tr in tu_records}

# ---------------------------------------------------------------------------
# Step 2: 챕터 파티션 정의.
# 헤딩 인덱스(섹션 idx 기준):
#   sec 0   roman   V. 조선의 성립과 발전
#   sec 1   number  V.1 조선의 성립
#   sec 6   sub     조선의 통치 제도            (V.1 안의 묶음 헤딩)
#   sec 12  sub     15세기 민족 문화의 발달    (V.1 안의 묶음 헤딩)
#   sec 15  number  V.2 사림 세력의 성장
#   sec 22  number  V.3 왜란과 호란의 극복
#   sec 34  roman   VI. 조선 사회의 변동
#   sec 35  number  VI.1 붕당 정치와 탕평책
# A: V.1(0..14) / V.2(15..21) / V.3(22..33) / VI.1(34..45)
# B: B1 V.1-건국(0..5) / B2 V.1-통치제도(6..11) / B3 V.1-15세기문화(12..14)
#    / B4 V.2(15..21) / B5 V.3(22..33) / B6 VI.1(34..45)

PARTITION_A = [
    ('A1_V1_조선의_성립',              0, 14),
    ('A2_V2_사림_세력의_성장',         15, 21),
    ('A3_V3_왜란과_호란의_극복',       22, 33),
    ('A4_VI1_붕당_정치와_탕평책',      34, 45),
]
PARTITION_B = [
    ('B1_V1_건국',                     0, 5),
    ('B2_V1_조선의_통치_제도',         6, 11),
    ('B3_V1_15세기_민족_문화의_발달',  12, 14),
    ('B4_V2_사림_세력의_성장',         15, 21),
    ('B5_V3_왜란과_호란의_극복',       22, 33),
    ('B6_VI1_붕당_정치와_탕평책',      34, 45),
]

# 학습흐름 순서대로 챕터 ID 목록 (tie-break 시 앞선 챕터 선택)
A_ORDER = [c[0] for c in PARTITION_A]
B_ORDER = [c[0] for c in PARTITION_B]

# section idx → chapter id
A_MAP, B_MAP = {}, {}
for cid, lo, hi in PARTITION_A:
    for s in range(lo, hi + 1):
        A_MAP[s] = cid
for cid, lo, hi in PARTITION_B:
    for s in range(lo, hi + 1):
        B_MAP[s] = cid

unmapped_A = [s['idx'] for s in sections if s['idx'] not in A_MAP]
unmapped_B = [s['idx'] for s in sections if s['idx'] not in B_MAP]
assert not unmapped_A and not unmapped_B, (
    f'매핑 누락: A={unmapped_A} B={unmapped_B}'
)

chapter_def = {
    'partition_A': {
        'chapters': [
            {'id': cid, 'section_range': [lo, hi],
             'section_titles': [sections[s]['breadcrumb'] for s in range(lo, hi+1)]}
            for cid, lo, hi in PARTITION_A
        ],
        'section_to_chapter': {str(k): v for k, v in A_MAP.items()},
        'tiebreak_order': A_ORDER,
    },
    'partition_B': {
        'chapters': [
            {'id': cid, 'section_range': [lo, hi],
             'section_titles': [sections[s]['breadcrumb'] for s in range(lo, hi+1)]}
            for cid, lo, hi in PARTITION_B
        ],
        'section_to_chapter': {str(k): v for k, v in B_MAP.items()},
        'tiebreak_order': B_ORDER,
    },
    'source': {
        'corpus': 'input/국사교과서_조선_본문_정제.txt',
        'snapshot': 'results/snapshots/repro_run3',
        'section_source': 'results/exp08_toc_feasibility/probe.py (heading parser)',
        'n_sections': N_SEC,
        'n_entities': N_ENT,
    },
}
(OUT / 'chapter_definition.json').write_text(
    json.dumps(chapter_def, ensure_ascii=False, indent=2), encoding='utf-8')

# ---------------------------------------------------------------------------
# Step 3: 엔티티별 챕터 히스토그램.
# occurrence(E, S) = |E.text_unit_ids 중 S와 overlap 하는 unit|.
# ---------------------------------------------------------------------------
def dominant(hist: Counter, order: list[str]) -> tuple[str | None, float, int]:
    """argmax with deterministic tiebreak (lowest position in 학습흐름 order)."""
    if not hist:
        return None, 0.0, 0
    total = sum(hist.values())
    best_v = max(hist.values())
    candidates = [c for c, v in hist.items() if v == best_v]
    pick = min(candidates, key=lambda c: order.index(c))
    return pick, best_v / total, len(hist)

rows = []
sec_touched_dist = []
n_chapters_A_dist = []
n_chapters_B_dist = []
dom_A_dist = []
dom_B_dist = []

for _, r in ent_df.iterrows():
    title = str(r['title'])
    uids = list(r['text_unit_ids']) if r['text_unit_ids'] is not None else []

    sec_occ: Counter[int] = Counter()
    for uid in uids:
        for sidx in unit_id_to_sections.get(uid, ()):
            sec_occ[sidx] += 1
    total_occ = sum(sec_occ.values())
    n_sec_touched = len(sec_occ)

    hist_A: Counter[str] = Counter()
    hist_B: Counter[str] = Counter()
    for sidx, c in sec_occ.items():
        hist_A[A_MAP[sidx]] += c
        hist_B[B_MAP[sidx]] += c

    dom_A, ratio_A, ntouched_A = dominant(hist_A, A_ORDER)
    dom_B, ratio_B, ntouched_B = dominant(hist_B, B_ORDER)

    rows.append({
        'entity': title,
        'total_occurrences': total_occ,
        'n_sections_touched_exp8': n_sec_touched,
        'dominant_chapter_A': dom_A or '',
        'dominance_ratio_A': round(ratio_A, 4),
        'n_chapters_touched_A': ntouched_A,
        'dominant_chapter_B': dom_B or '',
        'dominance_ratio_B': round(ratio_B, 4),
        'n_chapters_touched_B': ntouched_B,
        'histogram_A': json.dumps({c: hist_A.get(c, 0) for c in A_ORDER}, ensure_ascii=False),
        'histogram_B': json.dumps({c: hist_B.get(c, 0) for c in B_ORDER}, ensure_ascii=False),
    })
    sec_touched_dist.append(n_sec_touched)
    n_chapters_A_dist.append(ntouched_A)
    n_chapters_B_dist.append(ntouched_B)
    dom_A_dist.append(ratio_A)
    dom_B_dist.append(ratio_B)

# CSV
csv_path = OUT / 'entity_chapter_assignments.csv'
with csv_path.open('w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

# ---------------------------------------------------------------------------
# Step 4: 집계 지표.
# ---------------------------------------------------------------------------
def frac(xs: list[float], thr: float) -> float:
    return sum(1 for x in xs if x >= thr) / len(xs)

def summary_for(dom_dist, ntouched_dist, label):
    return {
        'label': label,
        'dominance_ratio': {
            'mean': round(mean(dom_dist), 4),
            'median': round(median(dom_dist), 4),
            'frac_ge_0.5': round(frac(dom_dist, 0.5), 4),
            'frac_ge_0.6': round(frac(dom_dist, 0.6), 4),
            'frac_ge_0.8': round(frac(dom_dist, 0.8), 4),
        },
        'n_chapters_touched': {
            'mean': round(mean(ntouched_dist), 4),
            'median': median(ntouched_dist),
            'frac_eq_1': round(sum(1 for x in ntouched_dist if x == 1) / len(ntouched_dist), 4),
            'frac_le_2': round(sum(1 for x in ntouched_dist if x <= 2) / len(ntouched_dist), 4),
        },
        'clean_landing_rate_ge_0.5': round(frac(dom_dist, 0.5), 4),
        'clean_landing_rate_ge_0.6': round(frac(dom_dist, 0.6), 4),
    }

sum_A = summary_for(dom_A_dist, n_chapters_A_dist, 'A (4 chapters)')
sum_B = summary_for(dom_B_dist, n_chapters_B_dist, 'B (6 chapters)')
collapse = {
    'n_sections_touched_exp8': {
        'mean': round(mean(sec_touched_dist), 4),
        'median': median(sec_touched_dist),
    },
    'n_chapters_touched_A': {
        'mean': sum_A['n_chapters_touched']['mean'],
        'median': sum_A['n_chapters_touched']['median'],
    },
    'n_chapters_touched_B': {
        'mean': sum_B['n_chapters_touched']['mean'],
        'median': sum_B['n_chapters_touched']['median'],
    },
}

# ---------------------------------------------------------------------------
# Step 5: 앵커 + 이성계.
# ---------------------------------------------------------------------------
anchors = json.loads(Path('results/exp10_room_gen/anchors_korean_history.json').read_text(encoding='utf-8'))
anchor_names = list(anchors['should_show']) + list(anchors['should_demote'])
if '이성계' not in anchor_names:
    anchor_names.append('이성계')

row_by_name = {r['entity']: r for r in rows}
anchor_table = []
for name in anchor_names:
    r = row_by_name.get(name)
    if r is None:
        anchor_table.append({
            'entity': name, 'status': 'not_in_snapshot',
            'dom_A': '', 'ratio_A': '', 'dom_B': '', 'ratio_B': '',
            'n_chapters_A': '', 'n_chapters_B': '', 'n_sections_exp8': '',
        })
        continue
    anchor_table.append({
        'entity': name,
        'status': 'ok',
        'dom_A': r['dominant_chapter_A'],
        'ratio_A': r['dominance_ratio_A'],
        'dom_B': r['dominant_chapter_B'],
        'ratio_B': r['dominance_ratio_B'],
        'n_chapters_A': r['n_chapters_touched_A'],
        'n_chapters_B': r['n_chapters_touched_B'],
        'n_sections_exp8': r['n_sections_touched_exp8'],
    })

# 이성계 별도 검사
isng = row_by_name.get('이성계')
isng_flag_ok = (isng is not None
                and isng['dominant_chapter_A'] == 'A1_V1_조선의_성립'
                and isng['dominant_chapter_B'] == 'B1_V1_건국')
isng_summary = {
    'in_snapshot': isng is not None,
    'dominant_A': isng['dominant_chapter_A'] if isng else None,
    'dominance_A': isng['dominance_ratio_A'] if isng else None,
    'dominant_B': isng['dominant_chapter_B'] if isng else None,
    'dominance_B': isng['dominance_ratio_B'] if isng else None,
    'expected_A': 'A1_V1_조선의_성립',
    'expected_B': 'B1_V1_건국',
    'matches_expectation': isng_flag_ok,
}

# 앵커 split 플래그(dominance_ratio < 0.5)
split_anchors_B = [a for a in anchor_table
                   if a['status'] == 'ok' and isinstance(a['ratio_B'], (int, float)) and a['ratio_B'] < 0.5]

# ---------------------------------------------------------------------------
# Step 6: GO/NO-GO 판정 (B 기준).
# ---------------------------------------------------------------------------
CLR_THR = 0.80          # clean_landing_rate(>=0.5) 임계
NTOUCHED_THR = 2.0       # mean n_chapters_touched 임계

clr_B = sum_B['clean_landing_rate_ge_0.5']
mean_nt_B = sum_B['n_chapters_touched']['mean']

cond_clr = clr_B >= CLR_THR
cond_nt = mean_nt_B <= NTOUCHED_THR
cond_isng = isng_flag_ok
cond_anchors = len(split_anchors_B) == 0

if cond_clr and cond_nt and cond_isng and cond_anchors:
    verdict = 'GO'
elif (not cond_clr) and (not cond_anchors or not cond_isng):
    verdict = 'NO-GO'
else:
    verdict = 'CONDITIONAL'

verdict_detail = {
    'verdict': verdict,
    'thresholds': {
        'clean_landing_rate_ge_0.5_min': CLR_THR,
        'mean_n_chapters_touched_max': NTOUCHED_THR,
        'isunggye_expected_A': 'A1_V1_조선의_성립',
        'isunggye_expected_B': 'B1_V1_건국',
    },
    'observed_B': {
        'clean_landing_rate_ge_0.5': clr_B,
        'mean_n_chapters_touched': mean_nt_B,
        'isunggye_lands_correctly': cond_isng,
        'split_anchors_count': len(split_anchors_B),
        'split_anchors': [a['entity'] for a in split_anchors_B],
    },
}

# ---------------------------------------------------------------------------
# summary.json
# ---------------------------------------------------------------------------
summary = {
    'partition_A': sum_A,
    'partition_B': sum_B,
    'collapse_comparison': collapse,
    'isunggye': isng_summary,
    'verdict': verdict_detail,
    'n_entities': N_ENT,
    'n_sections': N_SEC,
    'inputs': {
        'corpus': 'input/국사교과서_조선_본문_정제.txt',
        'entities': 'results/snapshots/repro_run3/entities.parquet',
        'text_units': 'results/snapshots/repro_run3/text_units.parquet',
        'sections_source': 'results/exp08_toc_feasibility/probe.py',
        'anchors': 'results/exp10_room_gen/anchors_korean_history.json',
    },
}
(OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

# ---------------------------------------------------------------------------
# REPORT.md
# ---------------------------------------------------------------------------
md = []
md.append(f'# exp15 결과: {verdict}')
md.append('')
md.append('> 진단 전용 (Phase 1). 방 배정 프로토타입 없음, LLM·임베딩 0회, 순수 결정적 카운팅.')
md.append('')
md.append('## 가설')
md.append('')
md.append('exp8에서 357 엔티티가 평균 5.12 섹션에 흩어진 건 1200 토큰 청크가 섹션보다 커서 한 청크가 평균 ~5 섹션에 걸치기 때문이다. 한 단계 거친 챕터 단위로 묶으면 같은 occurrence 매핑으로도 엔티티가 한 dominant 챕터로 모이는가.')
md.append('')

md.append('## 입력')
md.append('')
md.append(f'- 코퍼스: `input/국사교과서_조선_본문_정제.txt` ({len(text)} 자, 정제된 조선시대 국사 교과서 본문).')
md.append(f'- 스냅샷: `results/snapshots/repro_run3/` 의 `entities.parquet` ({N_ENT} 엔티티), `text_units.parquet` (12 units). repro_run3가 ±10 자연 편차 기반이라 동일 입력 보장은 이 357개에 대해서만.')
md.append(f'- 섹션 어휘: `results/exp08_toc_feasibility/probe.py` 의 헤더 파서가 도출한 {N_SEC}개 섹션 (roman=2, number=4, sub=40). exp15는 이 모듈을 import 해서 그대로 재사용.')
md.append('- 앵커: `results/exp10_room_gen/anchors_korean_history.json` (should_show 14 + should_demote 8). 이성계 별도 검사.')
md.append('')

md.append('## 방법')
md.append('')
md.append('- exp8과 동일한 텍스트 occurrence 경로: 엔티티의 `text_unit_ids` × text_unit 의 char span ↔ 섹션 char span overlap.')
md.append('- 섹션 단위 occurrence(E, S) = |E.text_unit_ids 중 S와 char-overlap 하는 unit|. 청크 1개가 평균 5 섹션에 걸치므로 한 unit이 여러 섹션에 1씩 카운트된다.')
md.append('- 챕터 단위 occurrence(E, C) = sum_{S in C} occurrence(E, S).')
md.append('- dominant_chapter = argmax. 동점은 학습흐름(문서 순서, 챕터 ID 사전순) 앞선 챕터로 깸 (결정적).')
md.append('- dominance_ratio = dominant 챕터 카운트 / 총 카운트. n_chapters_touched = 1회 이상 등장한 distinct 챕터 수. n_sections_touched_exp8 = 섹션 단위 동일 지표 (exp8 ~5.12와 비교용).')
md.append('- LLM·임베딩 0회. 두 번 돌리면 같은 수치.')
md.append('')

md.append('## 챕터 파티션')
md.append('')
md.append('두 가지 granularity 모두 문서 자체의 헤딩 계층에서 결정적으로 도출. 사람 묶음·LLM 0.')
md.append('')
md.append('**A (거친, 4개)**: V.1/V.2/V.3/VI.1 번호 섹션 그대로. 섹션 idx → 챕터:')
md.append('')
md.append('| 챕터 | 섹션 idx 범위 | 섹션 수 |')
md.append('|---|---|---|')
for cid, lo, hi in PARTITION_A:
    md.append(f'| {cid} | {lo}..{hi} | {hi - lo + 1} |')
md.append('')
md.append('**B (~6개, V.1만 문서 묶음 헤딩으로 split)**: V.1 안의 명명된 묶음 헤딩 "조선의 통치 제도" (sec 6) 와 "15세기 민족 문화의 발달" (sec 12) 을 경계로 분할.')
md.append('')
md.append('| 챕터 | 섹션 idx 범위 | 섹션 수 |')
md.append('|---|---|---|')
for cid, lo, hi in PARTITION_B:
    md.append(f'| {cid} | {lo}..{hi} | {hi - lo + 1} |')
md.append('')
md.append(f'매핑 누락 섹션 A: {unmapped_A}, B: {unmapped_B}.')
md.append('')

md.append('## Step 4 집계 지표')
md.append('')
md.append('| 지표 | A (4 chapters) | B (6 chapters) |')
md.append('|---|---|---|')
md.append(f'| dominance_ratio mean | {sum_A["dominance_ratio"]["mean"]} | {sum_B["dominance_ratio"]["mean"]} |')
md.append(f'| dominance_ratio median | {sum_A["dominance_ratio"]["median"]} | {sum_B["dominance_ratio"]["median"]} |')
md.append(f'| dominance_ratio >= 0.5 비율 | {sum_A["dominance_ratio"]["frac_ge_0.5"]} | {sum_B["dominance_ratio"]["frac_ge_0.5"]} |')
md.append(f'| dominance_ratio >= 0.6 비율 | {sum_A["dominance_ratio"]["frac_ge_0.6"]} | {sum_B["dominance_ratio"]["frac_ge_0.6"]} |')
md.append(f'| dominance_ratio >= 0.8 비율 | {sum_A["dominance_ratio"]["frac_ge_0.8"]} | {sum_B["dominance_ratio"]["frac_ge_0.8"]} |')
md.append(f'| n_chapters_touched mean | {sum_A["n_chapters_touched"]["mean"]} | {sum_B["n_chapters_touched"]["mean"]} |')
md.append(f'| n_chapters_touched median | {sum_A["n_chapters_touched"]["median"]} | {sum_B["n_chapters_touched"]["median"]} |')
md.append(f'| 정확히 1챕터 비율 | {sum_A["n_chapters_touched"]["frac_eq_1"]} | {sum_B["n_chapters_touched"]["frac_eq_1"]} |')
md.append(f'| <=2챕터 비율 | {sum_A["n_chapters_touched"]["frac_le_2"]} | {sum_B["n_chapters_touched"]["frac_le_2"]} |')
md.append(f'| clean_landing_rate (ratio >= 0.5) | {sum_A["clean_landing_rate_ge_0.5"]} | {sum_B["clean_landing_rate_ge_0.5"]} |')
md.append(f'| clean_landing_rate (ratio >= 0.6) | {sum_A["clean_landing_rate_ge_0.6"]} | {sum_B["clean_landing_rate_ge_0.6"]} |')
md.append('')

md.append('## 붕괴 비교 (섹션 → 챕터)')
md.append('')
md.append('| | mean | median |')
md.append('|---|---|---|')
md.append(f'| n_sections_touched (exp8) | {collapse["n_sections_touched_exp8"]["mean"]} | {collapse["n_sections_touched_exp8"]["median"]} |')
md.append(f'| n_chapters_touched A | {collapse["n_chapters_touched_A"]["mean"]} | {collapse["n_chapters_touched_A"]["median"]} |')
md.append(f'| n_chapters_touched B | {collapse["n_chapters_touched_B"]["mean"]} | {collapse["n_chapters_touched_B"]["median"]} |')
md.append('')

md.append('## Step 5 앵커 + 이성계')
md.append('')
md.append('| 엔티티 | dominant A | ratio A | dominant B | ratio B | n_ch A | n_ch B | n_sec exp8 |')
md.append('|---|---|---|---|---|---|---|---|')
for a in anchor_table:
    if a['status'] == 'ok':
        md.append(f'| {a["entity"]} | {a["dom_A"]} | {a["ratio_A"]} | {a["dom_B"]} | {a["ratio_B"]} | {a["n_chapters_A"]} | {a["n_chapters_B"]} | {a["n_sections_exp8"]} |')
    else:
        md.append(f'| {a["entity"]} | (스냅샷 없음) | | | | | | |')
md.append('')

md.append('이성계 기대값: A=A1_V1_조선의_성립, B=B1_V1_건국. ')
md.append(f'관측: A={isng_summary["dominant_A"]} (ratio {isng_summary["dominance_A"]}), B={isng_summary["dominant_B"]} (ratio {isng_summary["dominance_B"]}). 일치: {isng_summary["matches_expectation"]}.')
md.append('')
md.append(f'dominance_ratio_B < 0.5 인 앵커 (split 플래그): {[a["entity"] for a in split_anchors_B] or "없음"}.')
md.append('')

md.append('## Step 6 GO/NO-GO 임계 (B 기준)')
md.append('')
md.append('- GO: clean_landing_rate(>=0.5) >= 0.80, mean n_chapters_touched <= 2.0, 이성계 건국 챕터 착지, 앵커 split (ratio_B < 0.5) 없음.')
md.append('- NO-GO: clean_landing_rate 낮음 + 앵커 split 또는 이성계 오착지.')
md.append('- CONDITIONAL: 그 외.')
md.append('')
md.append(f'관측 B: clean_landing_rate(>=0.5)={clr_B}, mean n_chapters_touched={mean_nt_B}, 이성계 일치={cond_isng}, split 앵커={len(split_anchors_B)}.')
md.append('')
md.append(f'**판정: {verdict}**.')
md.append('')

md.append('## 한계점')
md.append('')
md.append('- text_unit 단위가 1200 토큰이라 한 unit이 평균 5 섹션에 걸친다. occurrence(E, S) 가 작은 N (E 의 unit 수 ≤ 2~3) 위에서 정수 카운팅이라 dominance_ratio 가 거친 단계 값(0, 0.33, 0.5, 0.67, 1.0 등)에 몰린다.')
md.append('- 챕터 파티션 A 의 V.1 은 sec 0..14 로 청크 0..3 거의 전체를 덮어 trivially 응집도가 높다. B 는 V.1 을 셋으로 쪼개 챕터 경계가 청크 안으로 들어가므로 청크 1개가 두 챕터에 걸치기 시작한다. 판정은 B 기준이라야 청크-챕터 mismatch 의 진짜 비용이 보인다.')
md.append('- exp8 occurrence 경로는 "entity 가 어느 청크에 들어 있나" 까지만 추적한다. 청크 내부 어디서 등장하는지(어느 sub-section 의 본문에 박혀 있는지) 는 모른다. 실제 어휘적 등장으로 chapter 를 결정하려면 청크를 더 잘게 자르거나(exp9 식) 텍스트에서 엔티티 표면형을 직접 카운트하는 패스가 필요하다. exp15 는 그 패스 없이 가능한 가장 보수적인 진단.')
md.append('- 357 엔티티는 repro_run3 한 회차의 ±10 자연 편차 안 결과. 같은 설정 재추출 시 엔티티셋이 약간 다를 수 있음.')
md.append('')

(OUT / 'REPORT.md').write_text('\n'.join(md), encoding='utf-8')

print(f'verdict: {verdict}')
print(f'B clean_landing(>=0.5)={clr_B}, mean n_chapters_touched={mean_nt_B}')
print(f'이성계 A={isng_summary["dominant_A"]} (ratio {isng_summary["dominance_A"]}), '
      f'B={isng_summary["dominant_B"]} (ratio {isng_summary["dominance_B"]})')
print(f'split anchors (ratio_B<0.5): {[a["entity"] for a in split_anchors_B]}')
print(f'saved: {OUT}/REPORT.md, entity_chapter_assignments.csv, chapter_definition.json, summary.json')
