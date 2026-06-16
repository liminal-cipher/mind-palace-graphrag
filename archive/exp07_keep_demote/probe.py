"""exp7 의미 방 위 LLM 레이어. exp6 직접 클러스터 K=10 위에 LLM이 (A) 도메인 받고
keep/demote rubric 스스로 도출, (B) 클러스터마다 rubric 적용해 방이름·분류·coherence.
A+B를 3번 독립 실행해 안정성 본다.

입력: repro_run3 (entities, communities, lancedb/entity_description).
출력: results/exp07_keep_demote/report.md, results/exp07_keep_demote/raw/run{n}/stage_a.txt, stage_b_cluster{i}.txt.
"""
from __future__ import annotations
import os, sys, io, json, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path
from collections import Counter, defaultdict
import numpy as np
import pandas as pd
import lancedb
from scipy.cluster.hierarchy import linkage, fcluster
from openai import AzureOpenAI

BASE = Path('results/snapshots/repro_run3')
OUT = Path('results/exp07_keep_demote')
RAW = OUT / 'raw'
OUT.mkdir(parents=True, exist_ok=True)
RAW.mkdir(parents=True, exist_ok=True)

API_VERSION = "2024-12-01-preview"
DEPLOYMENT = "gpt-4.1-mini"
N_RUNS = 3
DOMAIN = "한국사"
SAMPLE_SEED = 42
SAMPLE_SIZE = 60


# === 데이터 ===
ent = pd.read_parquet(BASE / 'entities.parquet').set_index('id')
com = pd.read_parquet(BASE / 'communities.parquet')
com_l0 = com[com['level'] == 0].copy().reset_index(drop=True)
cnum_to_eids = {int(c['community']): list(c['entity_ids']) for _, c in com_l0.iterrows()}

db = lancedb.connect(str(BASE / 'lancedb'))
vec_df = db.open_table('entity_description').to_pandas()
vec_by_id = {row['id']: np.array(row['vector'], dtype=np.float32) for _, row in vec_df.iterrows()}

in_eids = set()
for eids in cnum_to_eids.values():
    in_eids.update(eids)
orphan_eids = set(ent.index) - in_eids


# === exp6와 같은 직접 클러스터 (357 엔티티 ward K=10) ===
ent_ids = list(ent.index)
mat = np.stack([vec_by_id[e] for e in ent_ids]).astype(np.float32)
mat_n = mat / np.clip(np.linalg.norm(mat, axis=1, keepdims=True), 1e-12, None)
Z = linkage(mat_n, method='ward', metric='euclidean')
labels = fcluster(Z, t=10, criterion='maxclust')
clusters = defaultdict(list)
for eid, lab in zip(ent_ids, labels):
    clusters[int(lab) - 1].append(eid)
clusters = dict(clusters)


def member_payload(eids):
    rows = []
    for e in eids:
        r = ent.loc[e]
        rows.append({
            'title': str(r['title']),
            'type': str(r['type']),
            # 토큰 절약 위해 description 300자 컷
            'desc': str(r['description'])[:300],
        })
    return rows


# Stage A 샘플은 한 번만 뽑아 3런 공유 (A의 변동은 LLM 무작위성만 측정)
random.seed(SAMPLE_SEED)
sample_eids = random.sample(ent_ids, min(SAMPLE_SIZE, len(ent_ids)))
sample_lines = '\n'.join(
    f'- {str(ent.loc[e, "title"])} ({str(ent.loc[e, "type"])})'
    for e in sample_eids
)


# === LLM ===
api_key = os.environ.get('GRAPHRAG_API_KEY')
if not api_key:
    raise SystemExit('GRAPHRAG_API_KEY 환경 변수 없음')
azure_endpoint = os.environ.get('GRAPHRAG_API_BASE')
if not azure_endpoint:
    raise SystemExit('GRAPHRAG_API_BASE 환경 변수 없음')
client = AzureOpenAI(azure_endpoint=azure_endpoint, api_key=api_key, api_version=API_VERSION)


def call_json(sys_p, user_p):
    resp = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[{'role': 'system', 'content': sys_p},
                  {'role': 'user', 'content': user_p}],
        temperature=0,
        response_format={'type': 'json_object'},
    )
    raw = resp.choices[0].message.content
    usage = {'prompt_tokens': resp.usage.prompt_tokens,
             'completion_tokens': resp.usage.completion_tokens}
    return raw, usage


def make_stage_a(domain, sample_lines):
    sys_p = (
        "당신은 학습 자료 분석가다. 주어진 도메인의 한 학생이 자료를 외운다고 할 때, "
        "엔티티들 중 어떤 부류가 '콕 집어 이름까지 외울 대상'이 되고 어떤 부류가 "
        "'배경/맥락'으로 흐를지 가르는 기준(rubric)을 스스로 도출하라. "
        "외부에서 미리 정한 축에 끼워 맞추지 말고 도메인 학습 맥락에서 자연스럽게 도출하라."
    )
    user = (
        f"도메인: {domain}\n\n"
        f"이 도메인 자료에서 추출된 엔티티 샘플 {len(sample_eids)}개:\n{sample_lines}\n\n"
        "지시:\n"
        "- keep(콕 집어 외울 대상) vs demote(배경) 두 카테고리를 가르는 기준 3~5개를 적어라.\n"
        "- 각 기준에 도메인 예시 2~3개씩 (keep, demote 양쪽) 붙여라.\n"
        "- 출력 JSON 단 하나:\n"
        '{\n'
        '  "rubric": [\n'
        '    {"id": "R1", "rule": "...", "examples_keep": ["..."], "examples_demote": ["..."]},\n'
        '    ...\n'
        '  ],\n'
        '  "notes": "..."\n'
        '}'
    )
    return sys_p, user


def make_stage_b(domain, rubric_obj, cid, members):
    sys_p = (
        "당신은 학습 자료 분석가다. 주어진 rubric에 따라 한 클러스터의 멤버를 keep/demote로 "
        "분류하고, 클러스터에 짧은 주제 이름을 붙이고, 응집도를 판정하라. 본인의 다른 기준을 "
        "끼워 넣지 말고 rubric만 적용하라."
    )
    rubric_text = json.dumps(rubric_obj, ensure_ascii=False, indent=2)
    member_text = '\n'.join(
        f'{i+1}. {m["title"]} ({m["type"]}) - {m["desc"]}'
        for i, m in enumerate(members)
    )
    user = (
        f"도메인: {domain}\n\n"
        f"[rubric]\n{rubric_text}\n\n"
        f"[클러스터 {cid} 멤버 {len(members)}개]\n{member_text}\n\n"
        "지시:\n"
        "- room_name: 묶음 주제 한 줄 (15자 이내). 한 주제로 안 모이면 묶음 성격 그대로(예: 잡동사니, 문헌 더미).\n"
        "- 멤버 각각 keep 또는 demote로 분류 (rubric 적용).\n"
        "- coherence: 'coherent' (한 주제로 모임) / 'grab-bag' (관련 없는 게 섞임) / 'type-pile' (한 타입만 모여 의미는 흩어짐) 중 하나.\n"
        "- coherence_reason: 한 줄.\n"
        "- members 출력의 title은 입력 title과 정확히 일치해야 한다. 누락·중복 금지.\n\n"
        "출력 JSON:\n"
        '{\n'
        '  "room_name": "...",\n'
        '  "coherence": "coherent|grab-bag|type-pile",\n'
        '  "coherence_reason": "...",\n'
        '  "members": [{"title": "...", "classification": "keep|demote"}, ...]\n'
        '}'
    )
    return sys_p, user


# === 3런 실행 ===
all_runs = []
for run_n in range(1, N_RUNS + 1):
    print(f'\n=== run {run_n} ===')
    run_dir = RAW / f'run{run_n}'
    run_dir.mkdir(parents=True, exist_ok=True)

    sys_a, user_a = make_stage_a(DOMAIN, sample_lines)
    raw_a, usage_a = call_json(sys_a, user_a)
    (run_dir / 'stage_a.txt').write_text(raw_a, encoding='utf-8')
    try:
        rubric_obj = json.loads(raw_a)
    except Exception as e:
        print(f'  stage A parse 실패: {e}')
        rubric_obj = {'rubric': [], 'notes': f'parse failed: {e}'}
    print(f'  stage A: prompt={usage_a["prompt_tokens"]} comp={usage_a["completion_tokens"]}')

    cluster_results = {}
    for cid in sorted(clusters.keys()):
        members = member_payload(clusters[cid])
        sys_b, user_b = make_stage_b(DOMAIN, rubric_obj, cid, members)
        raw_b, usage_b = call_json(sys_b, user_b)
        (run_dir / f'stage_b_cluster{cid}.txt').write_text(raw_b, encoding='utf-8')
        try:
            cobj = json.loads(raw_b)
        except Exception as e:
            print(f'  cluster {cid} parse 실패: {e}')
            cobj = None
        cluster_results[cid] = {'obj': cobj, 'usage': usage_b, 'input': members}
        if cobj:
            n_keep = sum(1 for m in cobj.get('members', []) if m.get('classification') == 'keep')
            n_demote = sum(1 for m in cobj.get('members', []) if m.get('classification') == 'demote')
            print(f'  cluster {cid}: {cobj.get("room_name", "?"):<22} {cobj.get("coherence", "?"):<10} keep={n_keep:>2} demote={n_demote:>2}')

    all_runs.append({'run': run_n, 'rubric': rubric_obj, 'rubric_usage': usage_a,
                     'clusters': cluster_results})


# === 평가 ===
SHOULD_SHOW = ['측우기', '자격루', '혼천의', '앙부일구', '인지의',
               '이순신', '권율', '곽재우', '김시민', '정도전', '이성계',
               '임진왜란', '훈민정음', '거북선']
SHOULD_DEMOTE = ['조선', '백성', '백성들', '성리학', '붕당정치',
                 '경상도', '전라도', '함경도']
ALIASES = {'붕당정치': '붕당 정치'}

title_to_id = {}
for eid, r in ent.iterrows():
    title_to_id.setdefault(str(r['title']), eid)

eid_to_cluster = {e: cid for cid, eids in clusters.items() for e in eids}


def find_class(run, name):
    actual = ALIASES.get(name, name)
    eid = title_to_id.get(actual)
    if eid is None:
        return 'not-found', None, '-'
    cid = eid_to_cluster[eid]
    cobj = run['clusters'][cid].get('obj')
    if cobj is None:
        return 'parse-err', cid, '-'
    for m in cobj.get('members', []):
        if m.get('title') == actual:
            return m.get('classification', '?'), cid, cobj.get('room_name', '-')
    return 'missing', cid, cobj.get('room_name', '-')


# === report.md ===
md = []
md.append('# exp7 — 의미 방 위 LLM 레이어')
md.append('')
md.append(f'베이스: `repro_run3`. 입력 클러스터: exp6 직접 ward K=10 (357 엔티티). LLM: Azure {DEPLOYMENT}, temp=0. 도메인: "{DOMAIN}". 3런 독립 실행. raw 응답은 `results/exp07_keep_demote/raw/run{{n}}/`.')
md.append('')
md.append('2단계: **A** = LLM이 도메인 받고 샘플 보고 keep/demote rubric 스스로 도출. **B** = 클러스터마다 rubric 적용해 방이름·분류·coherence.')
md.append('')

# A 단계
md.append('## A — 도출된 rubric (3런)')
md.append('')
for run in all_runs:
    md.append(f'### run {run["run"]}')
    md.append('')
    rules = run['rubric'].get('rubric', []) if run['rubric'] else []
    if not rules:
        md.append('_(parse 실패 또는 빈 rubric)_')
        md.append('')
        continue
    for r in rules:
        rid = r.get('id', '?')
        rule = r.get('rule', '?')
        ek = ', '.join(r.get('examples_keep', []))
        ed = ', '.join(r.get('examples_demote', []))
        md.append(f'- **{rid}** — {rule}')
        md.append(f'  - keep 예: {ek}')
        md.append(f'  - demote 예: {ed}')
    notes = run['rubric'].get('notes')
    if notes:
        md.append('')
        md.append(f'_notes_: {notes}')
    md.append('')

# B 단계 — 클러스터별
md.append('## B — 클러스터별 결과 (3런)')
md.append('')
for cid in sorted(clusters.keys()):
    md.append(f'### 클러스터 {cid} (멤버 {len(clusters[cid])}개)')
    md.append('')
    md.append('| run | room_name | coherence | keep | demote | reason |')
    md.append('|---|---|---|---|---|---|')
    for run in all_runs:
        cobj = run['clusters'][cid].get('obj')
        if not cobj:
            md.append(f'| {run["run"]} | parse-err | - | - | - | - |')
            continue
        members = cobj.get('members', [])
        n_keep = sum(1 for m in members if m.get('classification') == 'keep')
        n_demote = sum(1 for m in members if m.get('classification') == 'demote')
        md.append(f'| {run["run"]} | {cobj.get("room_name", "?")} | {cobj.get("coherence", "?")} | {n_keep} | {n_demote} | {cobj.get("coherence_reason", "?")} |')
    md.append('')
    cobj1 = all_runs[0]['clusters'][cid].get('obj') if all_runs else None
    if cobj1:
        keep_titles = [m['title'] for m in cobj1.get('members', []) if m.get('classification') == 'keep']
        demote_titles = [m['title'] for m in cobj1.get('members', []) if m.get('classification') == 'demote']
        md.append(f'**run 1 keep ({len(keep_titles)}개)**: ' + (', '.join(keep_titles) if keep_titles else '(없음)'))
        md.append('')
        md.append(f'**run 1 demote ({len(demote_titles)}개)**: ' + (', '.join(demote_titles) if demote_titles else '(없음)'))
        md.append('')

# SHOULD-SHOW
md.append('## SHOULD-SHOW O/X (런별 분류)')
md.append('')
md.append('| name | 클러스터 | run1 분류 | run2 분류 | run3 분류 | run1 방 | run2 방 | run3 방 |')
md.append('|---|---|---|---|---|---|---|---|')
for name in SHOULD_SHOW:
    cells = [find_class(run, name) for run in all_runs]
    cid_str = str(cells[0][1]) if cells[0][1] is not None else '-'
    md.append(f'| {name} | {cid_str} | {cells[0][0]} | {cells[1][0]} | {cells[2][0]} | {cells[0][2]} | {cells[1][2]} | {cells[2][2]} |')
md.append('')

# SHOULD-DEMOTE
md.append('## SHOULD-DEMOTE O/X (런별 분류)')
md.append('')
md.append('| name | 클러스터 | run1 분류 | run2 분류 | run3 분류 | run1 방 | run2 방 | run3 방 |')
md.append('|---|---|---|---|---|---|---|---|')
for name in SHOULD_DEMOTE:
    cells = [find_class(run, name) for run in all_runs]
    cid_str = str(cells[0][1]) if cells[0][1] is not None else '-'
    md.append(f'| {name} | {cid_str} | {cells[0][0]} | {cells[1][0]} | {cells[2][0]} | {cells[0][2]} | {cells[1][2]} | {cells[2][2]} |')
md.append('')

# stability: room_name 일치 / keep jaccard
md.append('## 3런 안정성')
md.append('')
md.append('| 클러스터 | room_name 3런 | keep 크기 3런 | keep 평균 jaccard |')
md.append('|---|---|---|---|')
for cid in sorted(clusters.keys()):
    names = []
    keeps = []
    for run in all_runs:
        cobj = run['clusters'][cid].get('obj')
        names.append(cobj.get('room_name', '?') if cobj else 'parse-err')
        keeps.append(frozenset(m['title'] for m in (cobj or {}).get('members', []) if m.get('classification') == 'keep'))
    keep_sizes = [len(k) for k in keeps]
    jac = []
    for i in range(len(keeps)):
        for j in range(i + 1, len(keeps)):
            u = keeps[i] | keeps[j]
            if u:
                jac.append(len(keeps[i] & keeps[j]) / len(u))
    avg_j = sum(jac) / len(jac) if jac else 0.0
    md.append(f'| {cid} | {" / ".join(names)} | {keep_sizes} | {avg_j:.2f} |')
md.append('')

# coherence 플래그
md.append('## coherence 플래그 (런별)')
md.append('')
md.append('| 클러스터 | run1 | run2 | run3 |')
md.append('|---|---|---|---|')
for cid in sorted(clusters.keys()):
    cohs = []
    for run in all_runs:
        cobj = run['clusters'][cid].get('obj')
        cohs.append(cobj.get('coherence', '?') if cobj else 'parse-err')
    md.append(f'| {cid} | {cohs[0]} | {cohs[1]} | {cohs[2]} |')
md.append('')

# 비용
total_prompt = (sum(run['rubric_usage']['prompt_tokens'] for run in all_runs)
                + sum(r['usage']['prompt_tokens'] for run in all_runs for r in run['clusters'].values()))
total_comp = (sum(run['rubric_usage']['completion_tokens'] for run in all_runs)
              + sum(r['usage']['completion_tokens'] for run in all_runs for r in run['clusters'].values()))
md.append('## 비용')
md.append('')
md.append(f'총 토큰: prompt={total_prompt} / completion={total_comp} (3런 × (A 1번 + B 10번) = 33 호출).')
md.append('')

target = OUT / 'report.md'
target.write_text('\n'.join(md), encoding='utf-8')
print(f'\nsaved: {target}')
print(f'총 토큰: prompt={total_prompt} completion={total_comp}')
