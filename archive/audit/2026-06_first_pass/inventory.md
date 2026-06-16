# 회랑 실험 감사 1단계, 인벤토리

읽기 전용 인벤토리. 옳고 그름 판정은 다음 단계에서. 여기서는 "무엇이 실물로 있고 무엇이 문서에 주장만 있는지"만 적는다.

기준 디렉토리: `C:/Users/AJourney/Desktop/graphrag/`. 모든 경로는 그 아래 상대경로다.

## 1. 실험별 (exp1 ~ exp10) 코드, 결과, 스냅샷 매핑

EXPERIMENTS.md는 "exp1 ~ exp4"를 한 묶음 (분산 측정과 LCC 실험)으로 다룬다. 그래서 실험 번호와 디렉토리 이름이 1대1로 안 맞는 부분이 있다.

| 실험 | 코드 (실제 위치) | 저장된 결과 / 리포트 | 스냅샷 |
|---|---|---|---|
| exp1 (baseline 추출) | (전용 스크립트 없음. 루트 `analyze_baseline.py`, `extract_results.py`로 분석. graphrag 실행은 `graphrag.exe` 직접) | `archive/reports/00_baseline.md` (frontmatter: 385 ent, 392 rel, 91 com, level0=31, 963.9s, $1.02). `logs/run_baseline.{stdout,stderr,exit}`, `logs/indexing-engine.log` | **없음**. baseline 출력은 스냅샷으로 저장 안 됨. |
| exp2 (max_cluster_size 15) | (전용 스크립트 없음, settings.yaml 변경 후 graphrag.exe 재실행) | `archive/reports/01_max15.md`, `logs/exp2_results.json`, `logs/exp2_run.log` | `archive/snapshots/exp2_max15/` (parquet 7개 + lancedb 3개 + log + results.json) |
| exp3 (재현성/스냅샷 캐시 검증) | (전용 스크립트 없음) | `archive/reports/02_snap_max10.md`, `02_snap_max20.md`, `03_repro_step1_snapshot.md`, `03_repro_step2_variance.md`, `03_repro_step3_summary.md`. `logs/snap_max10_*`, `snap_max20_*`, `repro_run2_*`, `repro_run3_*`. | `archive/snapshots/snap_max10/`, `snap_max20/`, `repro_run2/`, `repro_run3/` |
| exp4 (use_lcc=true) | (전용 스크립트 없음, settings.yaml만 변경) | `archive/reports/04_use_lcc.md`, `logs/exp4_lcc_results.json`, `logs/exp4_lcc_run.log`, `logs/exp4_missing_analysis.txt`, `archive/snapshots/exp4_lcc_true/missing_analysis_full.txt` | `archive/snapshots/exp4_lcc_true/` |
| exp5 (방 병합, type 분류) | `archive/exp05_stage2_merge/exp5_lib.py`, `exp5_embed.py`, `exp5_llm.py`, `exp5_llm_v2.py`, `type_select_test.py` | `archive/exp05_stage2_merge/stage1_payloads.json`, `stage2_emb_K{5,8,10}.json`, `stage2_emb_K8_alt_average.json`, `stage2_llm_v2_K5_run{1,2,3}.json`, `embed_silhouette_summary.json`, `embed_reliability.json`, `llm_reliability.json`, `llm_v2_reliability.json`, `llm_v2_raw/run{1,2,3}.txt`, `entity_breakdown.html`, `entity_breakdown_v2.html`, `dedup_candidates.md`, `type_select_test.md`. 리포트: `archive/reports/05_exp5_data_contract.md` (spec, 결과 수치는 아님) | (스냅샷 안 만듦. `repro_run3` 입력 재사용.) |
| exp6 (임베딩 직접 클러스터 vs community 병합) | `archive/exp06_room_probe/probe.py` | `archive/exp06_room_probe/report.md` (직접 ward K=10 크기 분포, 클러스터별 멤버표, orphan 31개 매핑, community-merged 비교) | (스냅샷 안 만듦. `repro_run3` 입력) |
| exp7 (방 위 LLM 레이어, rubric, 3런 안정성) | `archive/exp07_keep_demote/probe.py` | `archive/exp07_keep_demote/report.md`, `archive/exp07_keep_demote/raw/run{1,2,3}/` (LLM 원응답) | (스냅샷 안 만듦. `repro_run3` 입력) |
| exp8 (목차/섹션 feasibility) | `archive/exp08_toc_feasibility/probe.py` | `archive/exp08_toc_feasibility/report.md` (46섹션, text_unit 매핑, 엔티티 다중섹션 분포) | (스냅샷 안 만듦. `repro_run3` 입력 + 원본 텍스트) |
| exp9 (semantic vs pagesplit rechunk) | `archive/exp09_rechunk/build_inputs.py`, `run_full.py`, `run_verify.py`, `eval_run.py` | `archive/exp09_rechunk/comparison.md`, `eval_semantic_run1.json`, `eval_pagesplit_run1.json`. `logs/exp9_*.log`, `logs/{pagesplit_run1,semantic_run1}/indexing-engine.log`. proj 설정: `proj_pagesplit/settings.yaml`, `proj_semantic/settings.yaml` | `archive/snapshots/semantic_run1/`, `archive/snapshots/pagesplit_run1/` |
| exp10 (end-to-end 룸 제너레이터) | `archive/exp10_room_gen/room_gen.py`, `run_repro_run3.py`, `eval_rooms.py`, `anchors_korean_history.json` | `archive/exp10_room_gen/report.md`. 산출물 `archive/rooms/repro_run3_K{5,10}_{embedding,llm}.{json,md,eval.json}` (12파일) + `dump_repro_run3_K10_embedding.txt`. rubric 캐시 `cache/exp10_room_gen/rubric_repro_run3.json` | (스냅샷 안 만듦. `repro_run3` 입력) |

코드 외 노트:
- exp1 ~ exp4는 별도 .py 없음. graphrag.exe 호출 + settings.yaml 변경 + 분석 스크립트(`analyze_baseline.py`, `extract_results.py`)로 굴린 흔적. 진짜 "코드"는 graphrag 라이브러리 + settings.yaml.
- exp5의 stage1 payload는 repro_run3에서 만들어진 형태(`stage1_payloads.json`)로 보존되어 있어, parquet 없이도 입력 페이로드 단계는 재현 가능.

## 2. 스냅샷 임베딩 확인 (lancedb `entity_description`)

모든 스냅샷 디렉토리에 `lancedb/entity_description.lance/`가 존재한다. 차원/벡터 개수는 디스크 존재만 확인하고 실제 로드는 안 했다(읽기 전용 인벤토리 단계).

| 스냅샷 | entity_description.lance | community_full_content.lance | text_unit_text.lance | 임베딩 있음? | room-gen 재현 가능? |
|---|---|---|---|---|---|
| `snapshots/repro_run3` | O | O | O | **있음** | 가능 |
| `snapshots/repro_run2` | O | O | O | **있음** | 가능 |
| `snapshots/exp2_max15` | O | O | O | **있음** | 가능 |
| `snapshots/exp4_lcc_true` | O | O | O | **있음** | 가능 |
| `snapshots/snap_max10` | O | O | O | **있음** | 가능 |
| `snapshots/snap_max20` | O | O | O | **있음** | 가능 |
| `snapshots/semantic_run1` | O | (없음) | (없음) | **있음** (entity만) | 가능 (room-gen은 entity_description만 필요) |
| `snapshots/pagesplit_run1` | O | (없음) | (없음) | **있음** (entity만) | 가능 |

- baseline은 스냅샷이 저장되지 않아 그 회차 임베딩 자체가 없다. 다른 7개 회차 (exp2/exp4/snap_max10/snap_max20/repro_run2/repro_run3와 semantic/pagesplit run1)는 entity_description.lance가 있어 room-gen 재실행 가능.
- semantic_run1과 pagesplit_run1은 `create_community_reports`를 빼고 돌려서 `community_full_content`, `text_unit_text` 두 테이블이 없다. room-gen은 entity_description만 쓰니 영향 없음.
- 모든 스냅샷에 `entities.parquet`, `relationships.parquet`, `communities.parquet`, `documents.parquet`, `text_units.parquet`, `stats.json`, `context.json`이 존재. `community_reports.parquet`는 semantic/pagesplit 두 곳을 제외하면 다 있음.

## 3. 주장과 실물 매핑

핵심 수치/주장을 한 줄씩 뽑고, 그 근거가 저장된 결과 파일까지 추적 가능한지만 본다. 값이 맞는지는 다음 단계.

### 3.1 EXPERIMENTS.md의 핵심 주장

| 주장 | 실물 위치 | 상태 |
|---|---|---|
| baseline 385 entities / 31 level 0 / 16분 / $1.02 | `archive/reports/00_baseline.md` frontmatter + 본문 | 실물 있음 (리포트). 원본 산출 stats.json은 없음(스냅샷 미저장). |
| 자연 편차 ±10 (30/32/40) | `archive/reports/03_repro_step3_summary.md` 표. 원시 `logs/{exp2,repro_run2,repro_run3}_results.json` + 각 snapshots의 stats.json. | 실물 있음 |
| repro_run3 357 entities / level 0 = 40 / orphan 31 | `results/snapshots/repro_run3/{entities,communities,stats.json}` | 실물 있음 |
| degree 상위 (조선 41 / 사림 17 / 정조 17 / 임진왜란 16 / 영조 12) | `results/snapshots/repro_run3/entities.parquet` 그리고 `archive/exp06_room_probe/report.md`의 cluster 내 degree 표 | 실물 있음 (parquet 컬럼으로 재계산 가능) |
| orphan 31개에 측우기·자격루·앙부일구·혼천의·인지의·금속활자 등이 들어 있음 | `archive/exp06_room_probe/report.md` 의 orphan 매핑 표 | 실물 있음 |
| use_lcc=true → level 0 40→16, 112개(31%) 소실 | `archive/reports/04_use_lcc.md` + `archive/snapshots/exp4_lcc_true/{communities.parquet, missing_analysis_full.txt}` + `logs/exp4_missing_analysis.txt` | 실물 있음 |
| community report가 baseline 963초 중 798초 (83%) | `archive/reports/00_baseline.md`. (실시간 로그는 `logs/indexing-engine.log` 또는 `logs/run_baseline.stdout`로 확인 가능) | 실물 있음 |
| exp5 type-keep 142 / type-demote 104 / unknown 111 (전체의 31%) | `archive/exp05_stage2_merge/` 안 (`exp5_lib.py`, `type_select_test.{py,md}`, `entity_breakdown_v2.html`) | 실물 있음 (HTML 분류 결과). 정확한 수치 매칭은 다음 단계. |
| exp6 직접 클러스터 [51,50,48,45,44,34,24,23,20,18] vs community-merged [160,45,35,34,18,10,8,7,5,4] | `archive/exp06_room_probe/report.md` 표 + `archive/exp05_stage2_merge/stage2_emb_K10.json` | 실물 있음 |
| exp6 임진왜란 7/8 동일 클러스터, 세종 과학 4/9 모드 클러스터 | `archive/exp06_room_probe/report.md` 앵커 표 | 실물 있음 |
| exp7 클러스터 2 jaccard 0.98, 클러스터 3 0.17, 클러스터 9 0.00 | `archive/exp07_keep_demote/report.md` 3런 안정성 표. raw `archive/exp07_keep_demote/raw/run{1,2,3}/` | 실물 있음 |
| exp7 클러스터 6만 grab-bag, 나머지 9개 coherent | `archive/exp07_keep_demote/report.md` coherence 표 | 실물 있음 |
| exp7 run3에서 이순신·임진왜란·거북선·권율·김시민·곽재우 missing | `archive/exp07_keep_demote/report.md` SHOULD-SHOW O/X 표. raw `archive/exp07_keep_demote/raw/run3/` | 실물 있음 |
| exp8 357개 엔티티 100%가 2+ 섹션 걸침, 평균 5.12 | `archive/exp08_toc_feasibility/report.md` | 실물 있음 |
| exp8 측우기 [13,14,15,16], 이순신 [21,22,23,24,25] 등 | `archive/exp08_toc_feasibility/report.md` 스팟체크 표 | 실물 있음 |
| exp9 semantic 1038 / pagesplit 755 entities | `archive/exp09_rechunk/eval_{semantic,pagesplit}_run1.json` + `archive/snapshots/{semantic,pagesplit}_run1/entities.parquet` | 실물 있음 |
| exp9 orphan 10.5% / 17.1%, max cluster 243 / 135 | `archive/exp09_rechunk/eval_{semantic,pagesplit}_run1.json` + `comparison.md` | 실물 있음 |
| exp9 anchor should-show 8/8, should-demote 3/4 (`붕당정치` 누락) | `eval_{semantic,pagesplit}_run1.json` | 실물 있음 |
| exp9 임진왜란 트리오: semantic split, pagesplit merge | `eval_{semantic,pagesplit}_run1.json` 의 클러스터 멤버 | 실물 있음 |

### 3.2 exp10 report.md의 핵심 주장

| 주장 | 실물 위치 | 상태 |
|---|---|---|
| repro_run3 k_base=12 크기 [51,48,45,39,34,31,24,23,20,18,13,11] | `archive/rooms/repro_run3_K10_embedding.md` 의 pipeline 섹션, K10_llm/K5 둘 다 동일. (코드 재실행으로도 결정적) | 실물 있음 |
| max_cluster_size=55에서 split 0회 (happy path) | 위 같은 pipeline 표 (k_base 와 after-split 사이즈 동일) | 실물 있음 |
| 4 combo 최종 사이즈 | `archive/rooms/repro_run3_K10_embedding.md` `[93,82,39,34,24,23,20,18,13,11]`, K10_llm md 동일, K5_embedding `[116,106,106,18,11]`, K5_llm `[108,79,63,63,44]` | 실물 있음 |
| 4 combo coherent 10/10 또는 5/5 | 각 `*.eval.json`의 `coherence_flags` | 실물 있음 |
| should_show: K10 13/14 (둘 다), K5_emb 11/14, K5_llm 8/14 | `repro_run3_K{10,5}_{embedding,llm}.eval.json` 의 `should_show.hits/total` | 실물 있음 |
| should_demote: K10 7/8, K5 둘 다 8/8 | 위 같은 eval json의 `should_demote.hits/total` | 실물 있음 |
| 전수보존 357/357, forced_demote=0 (4 combo 전부) | 위 같은 eval json의 `completeness` 블록 | 실물 있음 |
| K=10에서 embedding과 llm 두 전략 사실상 동일 | `repro_run3_K10_embedding.md` vs `K10_llm.md` 직접 비교 가능 (방 이름, 멤버 둘 다 저장됨) | 실물 있음 |
| K=5 embedding은 측우기 등 4종을 keep, K=5 llm은 같은 4종을 의병 방에 demote | `repro_run3_K5_embedding.md` ("조선 제도·인물·문서·지명" 방의 kept에 측우기·혼천의·앙부일구·자격루) vs `K5_llm.md` (의병 방 7명만 keep, 도구 4종은 demote 쪽) | 실물 있음 |
| 회귀: 이성계가 K=10에서 demote | `repro_run3_K10_embedding.eval.json` `should_show` 의 이성계 row (correct=false, classification=demote, room_name="임진왜란과 조선 군사") | 실물 있음 |
| 비용 33회 호출, 실측 ~105초 | (해당 메트릭은 보존된 spec에 없음. `meta.ts` 만 보존됨.) | **실물 없음** (문서에만, 토큰/시간은 런타임 stdout이라 어디에도 저장 안 됨) |

### 3.3 STATUS.md (날짜 2026-06-03 기준)의 주장

EXPERIMENTS.md 작성 시점(이후)과 어긋날 수 있어 따로 본다.

| 주장 | 실물 위치 | 상태 |
|---|---|---|
| 임베딩 병합 결정적, ward가 average보다 좋음 (silhouette K=5 0.083 / K=8 0.099 / K=10 0.098) | `archive/exp05_stage2_merge/embed_silhouette_summary.json`, `embed_reliability.json`, `stage2_emb_K{5,8,10}.json`, 비교용 `stage2_emb_K8_alt_average.json` | 실물 있음 |
| LLM partition 병합 v1 4회 시도 전부 실패 (누락/중복) | `archive/exp05_stage2_merge/llm_reliability.json` | 실물 있음 |
| LLM partition v1 stage2 JSON은 생성 안 됨 (성공 0회) | `archive/exp05_stage2_merge/` 에 v1 stage2 파일이 없음 (v2 K5 run1/2/3만 있음). 부재가 곧 증거 | 실물 있음 (부재로 확인) |
| 194 덩어리 (community {4,5,9,10,13,17,23,24,27,29,30,33,34} 한 덩어리 size 194) | `archive/exp05_stage2_merge/stage2_emb_K10.json` 의 멤버 리스트 + `results/snapshots/repro_run3/communities.parquet` 의 community size 합산 | 실물 있음 (parquet으로 재계산 가능, JSON에 직접 size=194는 적혀있지 않음) |
| LLM v2 (assignment 방식)을 다음 할 일로 적시 (실제 실행됐는지 별개) | `archive/exp05_stage2_merge/stage2_llm_v2_K5_run{1,2,3}.json` + `llm_v2_reliability.json` + `exp5_llm_v2.py` + `llm_v2_raw/` 가 모두 존재 → 실행됨 | 실물 있음 (계획이 실행으로 옮겨졌고 결과까지 저장됨) |

### 3.4 EXPERIMENTS.md의 "지금까지의 결정"

문장으로만 적혀 있고 실물 결과로 검증 가능한 항목.

| 결정 | 근거 실물 | 상태 |
|---|---|---|
| "방은 GraphRAG 커뮤니티 병합이 아니라 엔티티 임베딩 직접 클러스터" | exp6 report.md (size 분포 비교), exp10 산출 (실제 임베딩 ward로 만들어짐) | 실물 있음 |
| "방 이름·keep/demote는 LLM 한 겹 얹기" | exp7 report.md + exp10 산출 (rubric.json + stage B 코드 + room json) | 실물 있음 |
| "type 기준이 1차 안전망, 최종은 LLM" | exp5 type_select_test, entity_breakdown_v2.html + exp10 rubric/stage B 코드 | 실물 있음 |
| "community report 워크플로 빼면 5배 이상" | exp9 rechunk 두 run의 indexing-engine.log + comparison.md (428s, 1113s) vs baseline 963s. exp5 STATUS.md "묶기 재실행 1~2분"도 같은 결의 근거. | 실물 있음 |
| "작업 베이스는 repro_run3 스냅샷에 고정" | `results/snapshots/repro_run3/` 가 모든 후속 실험의 입력으로 명시됨 (exp5_lib.py, exp6 probe.py, exp7 probe.py, exp8 probe.py, exp10 run_repro_run3.py 의 BASE 상수) | 실물 있음 |
| "청킹은 pagesplit이 약간 유리" | exp9 comparison.md + eval_*.json | 실물 있음 |
| "exp9 baseline은 다른 자료라 청킹 변수만 격리되었지 자료 품질은 confound" | (문장만, 정량 분리 안 함) | **실물 없음** (자기-한계 명시) |

## 4. 핵심 결론별 근거 위치

### (a) 방은 임베딩 ward 클러스터 (커뮤니티 병합보다 균형 잡히고 빌드 가능)
- **근거 코드**: `archive/exp06_room_probe/probe.py` (직접 ward) + `archive/exp05_stage2_merge/exp5_embed.py` (community 병합 baseline)
- **근거 결과**: `archive/exp06_room_probe/report.md` 의 "2. 크기 분포 비교" 표 (`[51,50,48,45,44,34,24,23,20,18]` vs `[160,45,35,34,18,10,8,7,5,4]`). `archive/exp05_stage2_merge/stage2_emb_K10.json` 이 community 병합 원본.
- **참고**: STATUS.md의 "194 덩어리" 문제도 같은 결론을 받쳐줌 (community 병합이 큰 덩어리 만들고 안 깨짐).
- **상태**: 근거 위치 명확

### (b) K=10이 K=5보다 앵커 보존 더 나음
- **근거 결과** (should_show 기준):
  - `archive/rooms/repro_run3_K10_embedding.eval.json` → 13/14
  - `archive/rooms/repro_run3_K10_llm.eval.json` → 13/14
  - `archive/rooms/repro_run3_K5_embedding.eval.json` → 11/14
  - `archive/rooms/repro_run3_K5_llm.eval.json` → 8/14
- **단, should_demote는 반대**: K=10 둘 다 7/8 (`조선`이 keep으로 잘못), K=5 둘 다 8/8. 즉 "앵커 보존 더 나음"은 should_show 기준에서만 참이고, should_demote에선 K=5가 더 깔끔.
- **상태**: 근거 위치 명확. 단, "더 나음"의 정의가 should_show 한정인지 확인 필요 (다음 단계 판정 사항).

### (c) 임베딩 병합 ≥ LLM 병합
- **두 가지 다른 LLM 병합이 있어 헷갈리기 쉬워서 분리**:
  - exp5 v1 "partition" LLM 병합 (40방을 K개 그룹으로 LLM이 분배): `archive/exp05_stage2_merge/llm_reliability.json` 에서 4회 전부 실패 기록. stage2 JSON 미생성. → "임베딩이 압도적으로 나음"의 강한 근거.
  - exp5 v2 "assignment" LLM 병합 (각 community에 라벨 붙이기): `stage2_llm_v2_K5_run{1,2,3}.json` + `llm_v2_reliability.json`. 결과 보존됨 (성공 여부와 임베딩 대비 비교는 다음 단계).
  - exp10의 LLM merge (cluster centroid를 LLM이 K그룹으로): K=10에선 embedding과 사실상 동일, K=5에선 사이즈 균형은 LLM이 더 좋고 앵커 보존(should_show)은 embedding이 더 좋음. 근거: `archive/rooms/repro_run3_K{10,5}_{embedding,llm}.{md,eval.json}` 4쌍.
- **근거 코드**: `archive/exp05_stage2_merge/exp5_llm.py`, `exp5_llm_v2.py`, `archive/exp10_room_gen/room_gen.py` 의 `_merge_llm` 함수.
- **상태**: 근거 위치 명확. "≥" 라는 부등호 자체는 어느 K에서, 어느 메트릭에서 참이고 어느 곳에선 모호한지 다음 단계에서 정리 필요.

## 한눈에 요약

### 재현 가능한 실험 (스냅샷 임베딩 있음 → room-gen 재실행 가능)
- exp2 (`snapshots/exp2_max15`)
- exp3 (`snapshots/snap_max10`, `snap_max20`, `repro_run2`, `repro_run3`)
- exp4 (`snapshots/exp4_lcc_true`)
- exp9 (`snapshots/semantic_run1`, `snapshots/pagesplit_run1`)
- exp5/6/7/10 은 모두 repro_run3 위에서 돌므로 재현 가능.

### 코드 검토만 가능한 실험 (임베딩 없음)
- exp1 baseline: 스냅샷 미저장. `00_baseline.md`의 수치(385/31/91/16분/$1.02)는 리포트와 `logs/run_baseline.*`로만 검증 가능하고 그 위에서 다시 room-gen은 불가.

### 실물 결과 파일 없이 문서에만 있는 주장
- exp10 비용 33회 호출 / 실측 약 105초 → spec.json에는 호출 수, 토큰 수, 실행 시간이 저장되지 않음. 다음 단계에서 코드 재실행 또는 stdout 로그 확인 필요.
- exp9 "자료 품질 confound" 경고는 정량 분리 없이 문장으로만 명시 (자기-한계 표시).

### 근거 위치 못 찾은 결론
- 없음. 위 3개 핵심 결론은 모두 코드와 결과 파일 위치를 찾았다. 단,
  - (b) "K=10이 K=5보다 나음" 은 should_show 만 기준일 때 참, should_demote에선 K=5가 더 깔끔하다는 반대 신호가 같은 eval 파일에 있음 → 판정 단계에서 정의를 분명히 해야 함.
  - (c) "임베딩 ≥ LLM" 은 어떤 종류의 LLM 병합(v1 partition / v2 assignment / exp10 centroid)인지에 따라 메트릭이 갈림 → 판정 단계에서 분해 필요.

### exp10 spec.json에 메타가 부족한 부분
- final spec에 추출 시점(ts)은 들어있으나, LLM 호출 횟수·토큰·시간이 없음. 회귀 추적용으로 약함. 다음 단계에서 (a) 코드 재실행해 로그 확보 또는 (b) `room_gen.py` 에 메트릭 저장 추가 등의 선택이 있음.

## 노트
- 이번 패스는 존재 여부와 위치만 확인. 수치 검증, 코드 정확성 판정, 결론 입증 강도는 모두 다음 단계.
- baseline 스냅샷 부재는 구조적이라서 exp1 항목은 영원히 "코드 검토만 가능" 범주. 다른 실험에서 repro_run2/3 등으로 대체 가능하므로 치명적이지 않음.
