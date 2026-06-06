# RUNBOOK: 실험 재현 명령 한 장

팀원이 실험별로 무슨 명령을 돌리는지 찾는 한 페이지. 한 줄 = 한 명령 + 한 줄 설명. `LLM $` = Azure OpenAI 호출(비용 발생).

## 사전 준비 (한 번)

- `.venv` 활성화 (`.venv\Scripts\activate`). `requirements.txt` 설치.
- `.env`에 `GRAPHRAG_API_KEY`, `GRAPHRAG_API_BASE` 둘 다 채움.
- CWD는 항상 repo 루트(`C:/Users/AJourney/Desktop/graphrag/`). 모든 .py가 그 기준으로 경로 하드코딩.
- exp5~10 모두 입력은 `results/snapshots/repro_run3/` (357 entities, level 0 = 40방, `max=15`). 절대 건드리지 말 것.
- baseline(`output/`, max=10, 385 ent)과 repro_run3(snapshot, max=15)는 서로 다른 런이다.

재인덱싱(exp1~4, exp9 run_full)은 ±10 자연 편차가 있어 매번 동일 결과 보장 안 됨. 또한 graphrag 추출 워크플로가 CU(claims/units) 기반으로 바뀌면 `graphrag index --root .` 명령 자체가 달라질 수 있음.

## 실험별 명령

### exp1: baseline 인덱싱

```
graphrag index --root .                                           # LLM $ 재인덱싱: 16분, $1.02. settings.yaml = max=10, use_lcc=false.
```

산출: `output/*.parquet` + `output/lancedb/`, `logs/run_baseline.{stdout,stderr,exit}`, `logs/indexing-engine.log`. **스냅샷 안 만듦** (이 회차는 재현 불가).

### exp2: max_cluster_size=15

```
# 1) settings.yaml의 cluster_graph.max_cluster_size 10 → 15 편집
graphrag index --root .                                           # LLM $ 재인덱싱: 약 6.5분, $0.92. 캐시 새로(rm -rf cache/) 권장.
# 2) output/ 전체를 results/snapshots/exp2_max15/로 복사
```

산출: `results/snapshots/exp2_max15/` (parquet 7 + lancedb 3), `logs/exp2_results.json`, `logs/exp2_run.log`, 리포트 `results/reports/01_max15.md`.

### exp3: 재현성 + max 순수 효과

같은 `max=15` 설정으로 캐시-프레시 재인덱싱을 N=3 (`repro_run2`, `repro_run3`, 그리고 exp2 자체가 run1). 별도로 같은 추출에 캐시 유지한 채 max만 10/20으로 바꿔 `snap_max10`, `snap_max20`.

```
# A. 자연 편차 측정 (캐시 프레시, N=3)
rm -rf cache/ && graphrag index --root .                          # LLM $ 재인덱싱: repro_run2, ~5분, $0.88. ±10 흔들림.
rm -rf cache/ && graphrag index --root .                          # LLM $ 재인덱싱: repro_run3, ~6.5분, $0.93. ±10 흔들림.
# 각 run 후 output/ → results/snapshots/repro_run{2,3}/로 복사

# B. max 순수 효과 (추출 고정, 묶기만 재실행)
# settings.yaml: max_cluster_size 15 → 10, cache 유지
graphrag index --root .                                           # LLM $ 묶기 재실행: 약 1.7분, +$0.15. (snap_max10)
# settings.yaml: 10 → 20
graphrag index --root .                                           # LLM $ 묶기 재실행: 약 1.1분, +$0.05. (snap_max20)
```

산출: `results/snapshots/{snap_max10,snap_max20,repro_run2,repro_run3}/`, `logs/{snap_max10,snap_max20,repro_run2,repro_run3}_{results.json,run.log}`. 리포트 `results/reports/02_snap_max{10,20}.md`, `03_repro_step{1,2,3}_*.md`.

### exp4: use_lcc=true

```
# settings.yaml: use_lcc false → true (캐시 유지하면 repro_run3 추출 357 ent 위에서 비교)
graphrag index --root .                                           # LLM $ 묶기 재실행: 약 1.5분, +$0.10. 357 → 245 ent (112개 소실).
```

산출: `results/snapshots/exp4_lcc_true/` (`missing_analysis_full.txt` 포함), `logs/exp4_lcc_results.json`, `logs/exp4_lcc_run.log`, `logs/exp4_missing_analysis.txt`. 리포트 `results/reports/04_use_lcc.md`.

### exp5: 방 병합(type · 임베딩 · LLM)

상세는 `results/exp5/COMMANDS.md`. 요약:

```
python results/exp5/exp5_embed.py                                 # LLM $ 임베딩 ward 병합 stage2(K=5/8/10). 결정적.
python results/exp5/exp5_llm.py                                   # LLM $ v1 partition (16/16 전부 실패 기록용).
python results/exp5/exp5_llm_v2.py                                # LLM $ v2 assignment (K=5 × 3런, valid 통과).
python results/exp5/type_select_test.py                           # LLM $ entity type keep/demote 분류 점검.
```

산출: `results/exp5/stage2_emb_K{5,8,10}.json`, `stage2_llm_v2_K5_run{1,2,3}.json`, `llm_reliability.json`, `llm_v2_reliability.json`, `embed_silhouette_summary.json`, `embed_reliability.json`, `entity_breakdown_v2.html`, `llm_v2_raw/run{1,2,3}.txt`, `llm_merge_probe.md`.

### exp6: 직접 ward vs community 병합

```
python results/exp6_room_probe/probe.py                           # 결정적, LLM 없음. 약 30초.
```

산출: `results/exp6_room_probe/report.md`.

### exp7: 방 위 LLM 레이어(rubric · 3런 안정성)

```
python results/exp7/probe.py                                      # LLM $ 3런 × (rubric 1 + 클러스터 10) = 33회 호출.
```

산출: `results/exp7/report.md`, `results/exp7/raw/run{1,2,3}/{stage_a.txt, stage_b_cluster{0..9}.txt}`.

### exp8: 목차/섹션 feasibility

```
python results/exp8_toc_feasibility/probe.py                      # 결정적, LLM 없음. 텍스트 정규식 + parquet 매핑.
```

산출: `results/exp8_toc_feasibility/report.md`.

### exp9: 청킹 비교(semantic vs pagesplit)

```
python results/exp9_rechunk/build_inputs.py                       # LLM 없음. input/ → proj_{semantic,pagesplit}/input/*_docs.json.
python results/exp9_rechunk/run_verify.py                         # LLM 없음. text_units 행 수 사전검증.
python results/exp9_rechunk/run_full.py                           # LLM $ 재인덱싱 (community_reports 빠진 풀 파이프라인). semantic ~7분, pagesplit ~18분. ±10 흔들림.
python results/exp9_rechunk/eval_run.py --label semantic_run1     # LLM 없음. eval_semantic_run1.json 생성.
python results/exp9_rechunk/eval_run.py --label pagesplit_run1    # LLM 없음. eval_pagesplit_run1.json 생성.
```

산출: `results/snapshots/{semantic,pagesplit}_run1/` (entity_description.lance 포함, community_reports/text_unit_text 테이블 없음), `results/exp9_rechunk/eval_{semantic,pagesplit}_run1.json`, `comparison.md`, `logs/exp9_*.log`, `logs/{semantic_run1,pagesplit_run1}/indexing-engine.log`.

### exp10: end-to-end 방 제너레이터

```
.venv/Scripts/python.exe results/exp10_room_gen/run_repro_run3.py --dry   # LLM 없음. 파이프라인 모양만 출력.
.venv/Scripts/python.exe results/exp10_room_gen/run_repro_run3.py         # LLM $ 4 combo(K=10/5 × embedding/llm) = 33회 호출, ~105초.
python results/exp10_room_gen/eval_rooms.py --spec results/rooms/<run_id>.json --anchors results/exp10_room_gen/anchors_korean_history.json   # LLM 없음. 단일 spec 재평가.
```

산출: `results/rooms/repro_run3_K{5,10}_{embedding,llm}.{json,md,eval.json}` (4 combo × 3 파일), rubric 캐시 `cache/exp10_room_gen/rubric_repro_run3.json` (한 번만 도출), `results/rooms/dump_repro_run3_K10_embedding.txt` (사람 읽기용 덤프).

## 분석 보조(루트)

```
python analyze_baseline.py                                        # LLM 없음. output/ parquet 요약.
python extract_results.py                                         # LLM 없음. 결과 추출.
```
