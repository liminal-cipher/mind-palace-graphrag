# exp10 룸 제너레이터 (end-to-end 파이프라인)

베이스: `repro_run3` (357 엔티티). 파이프라인을 한 줄로 잇는 게 목표였다: 클러스터링(exp6) → 큰 클러스터 분할 → K 병합 → LLM rubric/이름/keep 선별(exp7) → 방 명세 JSON. 모듈은 도메인 무관, 한국사 규칙은 eval 측에 분리(앵커는 외부 JSON).

## 파일 구성

- `room_gen.py`: importable 함수. `load_snapshot`, `base_cluster`, `split_oversized`, `merge_to_k` (embedding|llm), `derive_rubric`, `assign_rooms`, `generate_rooms`, `check_invariants`.
- `run_repro_run3.py`: 4 combo 진입점 (K=10/5 × embedding/llm). `--dry`로 LLM 없이 모양만 본다.
- `eval_rooms.py`: 도메인 무관 평가기. 앵커는 외부 JSON으로 주입.
- `anchors_korean_history.json`: 한국사 앵커 (should_show 14 / should_demote 8). 다른 도메인은 같은 스키마 파일을 새로 두면 됨.

## 불변식 (코드 가드)

- 전수보존: kept ∪ demoted == 입력 엔티티. 누락 0.
  - exp7 run3에서 이순신·임진왜란·거북선이 demote도 아니고 출력에서 통째로 사라진 사건의 재발 방지.
  - 구현: Stage B 출력은 `keep_titles`만. demote는 set-difference로 자동. 멤버 100+ 클러스터에서도 응답 토큰 한도에 안 걸리고 누락이 의미상 발생할 수 없음.
  - 회귀 테스트: 4 combo 모두 357/357, forced_demote=0.
- 방 수 ≤ K ≤ 10 (하드캡 10).
- 방당 kept ≤ node_budget(=20). 프롬프트 + 후처리 백스톱 이중.
- n_runs>1이면 keep 다수결, 동률은 첫 run의 LLM 순서로 자름. degree-sort 안 함(exp1~4: degree 상위는 일반어).

## node_budget 백스톱 설계 근거

exp1~4 결과로 "degree 상위가 외울 핵심과 안 맞는다"는 게 명확해서, budget 초과 시 자르는 키를 degree로 두면 측우기처럼 저-degree 구체물이 먼저 잘려나간다. 그래서 자르는 키는:
- 단일 run: LLM이 준 중요도 순서.
- 멀티 run: 다수결 표 수, 동률은 첫 run의 LLM 순서.

degree는 프롬프트에 힌트로만 노출하고 정렬 키로 안 씀.

## merge_to_k 두 전략

- **embedding**: 클러스터 centroid 위에 다시 ward linkage 후 K로 컷. 결정적, 변동 없음.
  - 초기 greedy nearest-centroid 구현은 K=5에서 `[285,23,20,18,11]`로 체이닝됐고, ward-on-centroids로 바꿔 `[116,106,106,18,11]`까지 회복.
- **llm**: 한 번 호출. 클러스터마다 대표 엔티티(degree-desc + type round-robin로 다양성 확보, type 키워드는 박지 않음) 보내서 K개 그룹 매핑만 받음. 누락 클러스터는 centroid로 fold, 형식 위반 시 embedding 폴백.

## 파이프라인 산출 모양 (repro_run3 happy path)

```
base k_base=12: [51, 48, 45, 39, 34, 31, 24, 23, 20, 18, 13, 11]
split max=55  : [51, 48, 45, 39, 34, 31, 24, 23, 20, 18, 13, 11]  (split 0회 — 의도)
```

`max_cluster_size=55`는 repro_run3의 자연 최대(51)보다 살짝 위로 둬서 happy path에선 분할이 안 타고, exp9 rechunk(135/243)에서만 타도록 한 설정. 분할 함수는 만들어졌으니 다음 단계에서 rechunk 스냅샷으로 스트레스 테스트.

## 4 combo 결과 (results/rooms/)

| combo | final sizes | coherent | should_show | should_demote | 비고 |
|---|---|---|---|---|---|
| K=10 embedding | [93,82,39,34,24,23,20,18,13,11] | 10/10 | 13/14 | 7/8 | exp7 회귀 X |
| K=10 llm | [93,82,39,34,24,23,20,18,13,11] | 10/10 | 13/14 | 7/8 | embedding과 사실상 동일 |
| K=5 embedding | [116,106,106,18,11] | 5/5 | 11/14 | 8/8 | 큰 덩어리 3개 |
| K=5 llm | [108,79,63,63,44] | 5/5 | 8/14 | 8/8 | 사이즈 균형 더 좋음 |

K=10에선 embedding/llm 두 전략이 거의 같은 결과(방 이름·구성). k_base 12에서 K 10으로 가는 merge가 트리비얼해서 그렇다. K=5에선 두 전략이 명확히 다르다:
- embedding이 측우기·자격루·앙부일구·혼천의를 한 방(`조선 제도·인물·문서·지명`)의 keep으로 살림.
- llm은 같은 4종을 `조선 의병과 지도자` 방에 묶고 keep으로 안 살림 — 의병 라벨 안에선 도구류가 어색하다고 본 듯. 라벨이 좁아지면 그 안의 도구류가 demote로 밀려난다.

## exp7과 비교 (회귀 확인)

- exp7에서 안정적이던 측우기·자격루·앙부일구·혼천의·정도전 → K=10에서 모두 keep 유지.
- exp7 run3에서 통째로 누락됐던 이순신·임진왜란·거북선·권율·김시민·곽재우 → 모두 keep으로 등장. 전수보존 가드 + keep-only 프롬프트로 누락 사례 0.
- 회귀: K=10에서 이성계가 demote로 분류됨 (exp7은 3런 모두 keep). 새 프롬프트가 "콕 집어 외울 대상" 기준을 좀 더 좁게 잡으면서 건국자 같은 큰 분류는 demote로 밀어 보낸 영향으로 추정. n_runs=3 안정성 측정은 다음 단계.

## 비용

4 combo + 캐시 rubric 1회. 총 호출은 33회 (rubric 1 + LLM-merge 2 + Stage B 4×K).
- K=10 embedding: 11 호출 (rubric 캐시 hit 후 stage B 10)
- K=10 llm: 12 호출
- K=5 embedding: 6 호출
- K=5 llm: 7 호출

실측 시간: 합 ~105초 (re-run, 캐시 rubric 기준).

## 다음 단계 (이번 작업 밖)

- exp9 rechunk 스냅샷(`semantic_run1`, `pagesplit_run1`)으로 split_oversized 스트레스 (semantic 슈퍼클러스터 243, pagesplit 135).
- n_runs=3으로 흔들리는 K=5 LLM 라벨링 안정성 측정.
- K=5 LLM이 좁은 라벨에 도구류를 demote로 밀어 넣는 현상에 대한 프롬프트 조정.
- room generator를 exp10 디렉토리에서 정식 모듈로 졸업.
