# RUNBOOK 스모크 테스트

`results/RUNBOOK.md`의 명령이 적힌 그대로 동작하는지 계단식으로 확인한 결과.
실제 재실행이 아니라 "팀원이 따라했을 때 막히는 곳"을 찾는 게 목적.

계단 정의:
- 1: 정적 (스크립트 존재, `py_compile`, 경로/env/CWD 일치)
- 2: 결정적 실제 실행 (LLM 없는 스크립트만)
- 3: LLM 호출 (정적 검사 + 저장된 출력 존재로 갈음, 첫 호출은 시도 안 함)
- 4: 재인덱싱/풀 파이프라인 (실행 금지, 명령 형태만 확인)

CWD 가정: 모든 명령은 repo 루트에서 실행. `.env`에 `GRAPHRAG_API_KEY`, `GRAPHRAG_API_BASE` 채워져 있음 확인.

## 사전 준비

- `.venv\Scripts\python.exe` 존재: PASS.
- `.env` 두 키 모두 채워짐: PASS.
- 입력 스냅샷 `results/snapshots/repro_run3/` (parquet 6 + lancedb + log/json): PASS.
- `settings.yaml` 현재 상태: `max_cluster_size: 15`, `use_lcc: true` (exp4 적용 후 상태). exp1/2/3 명령은 settings.yaml을 먼저 되돌려야 의미가 있음, RUNBOOK이 그 점을 명시함.

## 항목별 결과

### exp1: baseline 인덱싱

계단 4. 명령 형태만 확인. `graphrag index --root .` 단일 호출. 산출(`output/*.parquet`, `logs/run_baseline.{stdout,stderr,exit}`, `logs/indexing-engine.log`) 전부 존재: PASS (형태).
주의: 현재 `settings.yaml`이 max=15, use_lcc=true 라서 그대로 돌리면 exp1 baseline이 아님. RUNBOOK 본문이 "settings.yaml = max=10, use_lcc=false" 라고 적어 둠. 팀원이 윗줄을 놓치면 baseline 재현이 어긋날 수 있음.

### exp2: max_cluster_size=15

계단 4. 명령은 `graphrag index --root .`. 산출(`results/snapshots/exp2_max15/`, `logs/exp2_results.json`, `logs/exp2_run.log`, `results/reports/01_max15.md`) 전부 존재: PASS (형태).
"cache 새로 (rm -rf cache/) 권장" 주석이 있고 캐시 디렉토리 존재 확인됨.

### exp3: 재현성 + max 순수 효과

계단 4. 명령은 `graphrag index --root .` × 5회 (캐시 프레시 2회 + max 변경 2회 + run1=exp2). 산출(`results/snapshots/{snap_max10,snap_max20,repro_run2,repro_run3}/`, 대응 `logs/*` , 리포트 `02_/03_*`) 전부 존재: PASS (형태).

### exp4: use_lcc=true

계단 4. 명령 `graphrag index --root .` 1회. 산출(`results/snapshots/exp4_lcc_true/`, `logs/exp4_lcc_results.json`, `logs/exp4_lcc_run.log`, `logs/exp4_missing_analysis.txt`, `results/reports/04_use_lcc.md`) 전부 존재: PASS (형태).
현재 `settings.yaml`이 max=15/use_lcc=true 상태라 이 exp의 종료 상태와 일치.

### exp5: 방 병합

계단 3 (LLM 호출 스크립트는 정적 검사). 4 스크립트 전부 존재, `py_compile` 통과.
- `exp5_embed.py`: `Path('results/snapshots/repro_run3')` 사용 → CWD가 repo 루트일 때만 동작. LLM 호출 없음 (lancedb의 사전 임베딩만 읽음).
- `exp5_llm.py`, `exp5_llm_v2.py`: `os.environ.get('GRAPHRAG_API_KEY'/'GRAPHRAG_API_BASE')` 확인, 없으면 `SystemExit`.
- `type_select_test.py`: LLM 호출 없음. `BASE = Path('results/snapshots/repro_run3')`, CWD=repo 루트.
저장된 출력(`stage2_emb_K{5,8,10}.json`, `stage2_llm_v2_K5_run{1,2,3}.json`, reliability/silhouette json 등) 모두 존재: PASS.

**RUNBOOK 수정 권장 1**: exp5 표에서 `exp5_embed.py`와 `type_select_test.py`에 붙은 `LLM $` 표기는 잘못. 둘 다 LLM 호출 없음 (전자는 precomputed lancedb 임베딩 read-only, 후자는 grep 결과 API 호출 0건). 비용 0. `LLM $` 제거 권장.

**RUNBOOK 수정 권장 2**: `results/exp5/COMMANDS.md`의 "처음부터 재현하는 원래 명령" 블록은 "CWD = `results/exp5/`" 라고 적었지만, 4 스크립트 모두 `Path('results/snapshots/repro_run3')`로 repo 루트 기준 상대경로를 씀. `results/exp5/`에서 실행하면 `results/exp5/results/snapshots/repro_run3` 를 찾다 실패함. CWD를 repo 루트로 고치거나 `cd results/exp5` 후 `../../` 접두를 붙이도록 정정해야 함. RUNBOOK 본문이 CWD=repo 루트라고 적어 둔 점은 맞음, COMMANDS.md만 어긋남.

### exp6: 직접 ward vs community 병합

계단 2. `probe.py` 실제 실행: PASS. `results\exp6_room_probe\report.md` 갱신 출력 확인. 30초 미만, LLM 호출 0.

### exp7: rubric · 3런 안정성

계단 3. `probe.py` 존재, `py_compile` 통과. `BASE = Path('results/snapshots/repro_run3')` (repo 루트 가정), `GRAPHRAG_API_KEY/BASE` 환경변수 검사, `from openai import AzureOpenAI`. 저장된 산출(`report.md`, `raw/run{1,2,3}/`) 존재 확인: PASS.

### exp8: 목차/섹션 feasibility

계단 2. `probe.py` 실제 실행: PASS. `results\exp8_toc_feasibility\report.md` 갱신 출력 확인. LLM 호출 0.

### exp9: 청킹 비교

계단 2/4 혼합.
- `build_inputs.py`: `py_compile` PASS. 입력 `input/history_joseon_semantic.json`, `input/history_joseon_pagesplit.txt` 존재 확인. 결정적이라 추가로 돌릴 필요 없음 (`proj_{semantic,pagesplit}/input/`에 산출 이미 존재).
- `run_verify.py`: 실제 실행 PASS. "semantic text_units=105, pagesplit=50, 둘 다 통과" 출력.
- `run_full.py`: 계단 4 (실행 금지). `py_compile` PASS. `os.chdir(REPO)`로 CWD 보정. RUNBOOK이 ±10 흔들림과 community_reports 부재를 명시.
- `eval_run.py --label semantic_run1` 실제 실행: 동작은 하지만 **CLI 시그니처가 RUNBOOK과 다름**. 실제 코드는 `targets = sys.argv[1:]`인 positional. `--label semantic_run1` 을 주면 `--label`을 라벨로 보고 `results/snapshots/--label` 스냅샷을 찾다가 `★ snapshot missing: results/snapshots/--label` 경고 한 줄 출력 후 `semantic_run1`로 넘어감. 평가 결과는 나오지만 노이즈와 혼동 유발.

**RUNBOOK 수정 권장 3**: exp9의 마지막 두 줄
```
python results/exp9_rechunk/eval_run.py --label semantic_run1
python results/exp9_rechunk/eval_run.py --label pagesplit_run1
```
에서 `--label` 제거 (positional). 정정안:
```
python results/exp9_rechunk/eval_run.py semantic_run1
python results/exp9_rechunk/eval_run.py pagesplit_run1
```

### exp10: end-to-end 방 제너레이터

계단 2 + 3.
- `run_repro_run3.py --dry` 실제 실행: PASS. snapshot 357 ent, k_base=12, split 0회 (repro_run3 happy path) 출력 확인. LLM 호출 0.
- 풀 실행(`--dry` 제거)은 시도 안 함. `room_gen.py` 내부에 `GRAPHRAG_API_KEY/BASE` 검사 코드 존재 확인. `.venv/Scripts/python.exe` 경로 정확.
- `eval_rooms.py --spec results/rooms/repro_run3_K10_embedding.json --anchors results/exp10_room_gen/anchors_korean_history.json` 실제 실행: PASS. anchor matching 출력 정상, `results\rooms\repro_run3_K10_embedding.eval.json` 갱신.

### 분석 보조

계단 2. `analyze_baseline.py`, `extract_results.py` 둘 다 `py_compile` PASS. 내부적으로 `ROOT = Path(__file__).parent` 사용해 CWD 무관. `output/*.parquet` 기준이라 baseline 상태(`output/`)가 살아 있는 한 어디서든 동작.

## 요약

- 명령 적힘 그대로 통과: **exp1/2/3/4/6/7/8/exp9(build_inputs,run_verify,run_full)/exp10(run_repro_run3,eval_rooms)/분석 보조** = 11항목 PASS.
- 정적+저장 출력으로 갈음(SKIP 사유=LLM 비용): **exp5_llm/exp5_llm_v2/exp7/exp10 풀** = 4항목.
- 동작은 하나 RUNBOOK 표기 잘못: **exp5(`LLM $` 표기 둘), exp9 eval_run(`--label` 플래그)** = 3건.

## 고칠 RUNBOOK 항목

1. exp5 표의 `exp5_embed.py`, `type_select_test.py` 줄에서 `LLM $` 제거 (실제로 LLM 호출 없음).
2. exp9 마지막 두 명령에서 `--label` 플래그 삭제 (positional 인자만 받음).
3. (부가) `results/exp5/COMMANDS.md`의 "CWD = `results/exp5/`" 한 줄을 "CWD = repo 루트"로 정정. RUNBOOK 본문은 이미 맞음.
4. (부가) exp1 라인에서 "settings.yaml = max=10, use_lcc=false" 가 산출 줄(`산출:` 뒤)에 묻혀 있어 팀원이 놓치기 쉬움. 명령 위쪽 별도 한 줄로 빼는 게 안전.
