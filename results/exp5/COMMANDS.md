# exp5 명령 모음

규칙: 한 줄 = 한 명령 + 한 줄 설명. `LLM $` = Azure OpenAI 호출(비용 발생).

## 이번 들여다보기에서 실제로 돌린 명령 (읽기 전용)

```
ls results/exp5/                                                  # 디렉토리 내용 확인
cat results/exp5/exp5_llm.py                                      # v1 partition 코드
cat results/exp5/exp5_llm_v2.py                                   # v2 assignment 코드
cat results/exp5/llm_reliability.json                             # v1 16회 실패 기록
cat results/exp5/llm_v2_reliability.json                          # v2 3런 파싱·유효성 기록
cat results/exp5/stage2_llm_v2_K5_run1.json                       # v2 run1 결과 (라벨→커뮤니티)
cat results/exp5/stage2_llm_v2_K5_run2.json                       # v2 run2 결과
cat results/exp5/stage2_llm_v2_K5_run3.json                       # v2 run3 결과
head -100 results/exp5/stage1_payloads.json                       # 입력 페이로드 구조 확인
python -c "...stage1 title 추출..."                                # community 0~39의 title 한 줄 요약 추출
```

## 처음부터 재현하는 원래 명령

`.env`에 `GRAPHRAG_API_KEY`, `GRAPHRAG_API_BASE` 필요. 입력은 `results/snapshots/repro_run3/`. CWD = repo 루트 (`C:/Users/AJourney/Desktop/graphrag/`). 4 스크립트가 `Path('results/snapshots/repro_run3')` 식 repo 루트 기준 상대경로를 쓰므로 `results/exp5/`에서 돌리면 실패함.

```
python results/exp5/exp5_embed.py                                 # LLM 없음, $0. 임베딩 ward 병합 stage2 (K=5/8/10) 생성. 비교 baseline
python results/exp5/exp5_llm.py                                   # LLM $ — v1 partition (K=5/8 × run_a/run_b × 4시도, 전부 실패함)
python results/exp5/exp5_llm_v2.py                                # LLM $ — v2 assignment (K=5 × 3런, valid 통과)
python results/exp5/type_select_test.py                           # LLM 없음, $0. entity type 분류 점검 (entity_breakdown_v2.html 생성)
```

산출 위치: `stage2_emb_K{5,8,10}.json`, `stage2_llm_K{5,8}_run_{a,b}.json` (v1은 검증 통과만 저장, 실제로는 0개), `stage2_llm_v2_K5_run{1,2,3}.json`, `llm_reliability.json`, `llm_v2_reliability.json`, `embed_reliability.json`, `embed_silhouette_summary.json`, `entity_breakdown_v2.html`.
