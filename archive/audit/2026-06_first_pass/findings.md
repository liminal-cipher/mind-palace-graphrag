# 회랑 실험 감사 2단계, 주장 판정 (findings)

읽기 전용 감사. 코드는 안 고쳤다. inventory.md가 적은 "어디에 있나"를 받아서, 여기서는 "값이 맞나, 증거가 충분한가"만 본다.

판정 라벨:
- 검증됨: 결정적 수치를 재실행 또는 저장된 파일로 정확히 확인
- 과장: 본문이 신호 하나에 단정 톤이나, 같은 자료 안에 반대 신호가 있어 보강이 필요
- 불일치: 저장된 결과와 본문 수치가 다름
- 증거 약함: 한 번 실행 또는 LLM 레이어 결과를 다회 측정 없이 단정
- 검증 불가: 아티팩트에 메트릭이 없고 재실행 비용·시간이 부담돼서 이번 패스에서 확인 안 함
- 한계 명시: 본문이 스스로 "확정 아님" 또는 "confound 있음"이라고 적어둔 자기-한계 (주장 아님)

재현 환경: `results/snapshots/repro_run3/` + `archive/exp10_room_gen/room_gen.py` (`.venv/Scripts/python.exe`). ward linkage는 결정적이라 동일 입력에서 동일 출력 확인. LLM 호출은 비용 발생을 피해 생략 (지시대로).

---

## 1. 결정적 수치 (재실행 검증)

| 주장 | 출처 | 판정 | 근거 |
|---|---|---|---|
| repro_run3: 357 entities | EXPERIMENTS.md L15,L21 / STATUS.md L29 | 검증됨 | `entities.parquet` 행 수 = 357 |
| repro_run3: level 0 = 40 | EXPERIMENTS.md L15,L21 / STATUS.md L29 | 검증됨 | `communities.parquet` 중 level==0 행 수 = 40 |
| repro_run3: orphan 31 (degree=0) | EXPERIMENTS.md L21 / inventory L34 | 검증됨 | `entities.degree==0` 합 = 31 |
| degree 상위 (조선 41 / 사림 17 / 정조 17 / 임진왜란 16 / 영조 12) | EXPERIMENTS.md L25 | 검증됨 | `entities.parquet` degree 정렬 일치 |
| exp6 직접 ward K=10 크기 [51,50,48,45,44,34,24,23,20,18] | exp6 report L556 / EXPERIMENTS.md L56 | 검증됨 | repro_run3에서 ward 재실행 동일 |
| exp6 직접 ward K=5 크기 [129,93,67,50,18] | exp6 report L557 | 검증됨 | ward 재실행 동일 |
| exp10 k_base=12 크기 [51,48,45,39,34,31,24,23,20,18,13,11] | exp10 report L39 | 검증됨 | `room_gen.base_cluster(_,12)` 재실행 동일 |
| exp10 max=55에서 split 0회 (k_base와 after_split 동일) | exp10 report L40 | 검증됨 | `split_oversized` 재실행, 12개 모두 통과 |
| exp10 K=10 embedding-merge [93,82,39,34,24,23,20,18,13,11] | exp10 report L49 | 검증됨 | `_merge_embedding(after_split,_,10)` 재실행 동일 |
| exp10 K=5 embedding-merge [116,106,106,18,11] | exp10 report L51 | 검증됨 | `_merge_embedding(after_split,_,5)` 재실행 동일 |
| exp10 전수보존 357/357, forced_demote=0 (4 combo 전부) | exp10 report L17,L52 | 검증됨 | 4개 eval.json `completeness.total_entities=357`, `forced_demote=0` 모두 일치 |
| exp9 semantic: 1038 entities, orphan 10.5%, max cluster 243 | EXPERIMENTS.md L104~107 | 검증됨 | `eval_semantic_run1.json` |
| exp9 pagesplit: 755 entities, orphan 17.1%, max cluster 135 | EXPERIMENTS.md L104~107 | 검증됨 | `eval_pagesplit_run1.json` (17.09→반올림 17.1) |
| exp9 ward K=10 크기 std semantic 66.7 / pagesplit 44.7 | EXPERIMENTS.md L106 | 검증됨 | `cluster_sizes` 위에 sample std (ddof=1) 적용 시 66.66, 44.69 |
| 자연 편차 ±10 (30/32/40) | EXPERIMENTS.md L24 | 검증됨 | exp2_max15=30, repro_run2=32, repro_run3=40 (모두 max=15 + cache new, per `03_repro_step3_summary` L23,26,27) |
| use_lcc=true → level 0 40→16, 112개(31%) 소실 | EXPERIMENTS.md L27 / `04_use_lcc.md` | 검증됨 | exp4_lcc_true 357 entities · level 0 = 16, 245 retained vs 357 = 112 missing |
| baseline 963.9초 중 community_reports 798.5초 (83%) | EXPERIMENTS.md L28 / 00_baseline.md L46~50 | 검증됨 (report 일치) | 스냅샷 없음. `00_baseline.md` 수치와 `logs/run_baseline.*` 외 cross-check 불가 |

## 2. LLM 결과 (LLM 호출 결과는 재현 안 함, 저장 파일만 확인)

| 주장 | 출처 | 판정 | 근거 |
|---|---|---|---|
| K=10 embedding/llm should_show 13/14, should_demote 7/8 | exp10 report L49,L50 | 검증됨 (단일 실행, LLM 변동 가능) | 두 eval.json 모두 그 수치. 단일 run이라 LLM 변동 측정 안 됨 → 별도로 "증거 약함"(아래) |
| K=5 embedding should_show 11/14, should_demote 8/8 | exp10 report L51 | 검증됨 (단일 실행) | eval json 일치 |
| K=5 llm should_show 8/14, should_demote 8/8 | exp10 report L52 | 검증됨 (단일 실행) | eval json 일치 |
| K=10에서 embedding/llm 사실상 동일 (방 이름·구성) | exp10 report L53 | 검증됨 | 두 eval.json의 14개 should_show 행이 동일 room_id·room_name·classification, 8개 should_demote도 동일. `final_sizes` 도 동일 [93,82,39,34,24,23,20,18,13,11] |
| K=5 embedding은 측우기·자격루·앙부일구·혼천의 keep / K=5 llm은 demote | exp10 report L55,56 | 검증됨 | K5_emb eval: 4종 모두 keep (room "조선 제도·인물·문서·지명"). K5_llm eval: 4종 모두 demote (room "조선 의병과 지도자") |
| 회귀: K=10에서 이성계 demote (exp7은 3런 모두 keep) | exp10 report L61~62 | 검증됨 | K10_emb·K10_llm 두 eval 모두 이성계 `classification=demote, correct=false`, room "임진왜란과 조선 군사" |
| exp7 cluster 2 jaccard 0.98, cluster 3 0.17, cluster 9 0.00 | EXPERIMENTS.md L74 | 검증됨 (한 회차 보고서) | `archive/exp07_keep_demote/report.md` (raw run1/2/3 디렉토리 존재) |
| exp7 run3에서 이순신·임진왜란·거북선·권율·김시민·곽재우 missing | EXPERIMENTS.md L76 | 검증됨 (한 회차 보고서) | `archive/exp07_keep_demote/raw/run3/` raw 응답 |
| exp7 비용 3런 × (rubric 1 + 클러스터 10) = 33회 호출 | EXPERIMENTS.md L77 | 검증됨 (산수) | 곱셈 33 = 3×11 |
| exp5 LLM partition v1 4회 시도 전부 실패 | STATUS.md L41~45 | 검증됨 (단, "4회"는 표현 정리 필요) | `llm_reliability.json`: K∈{5,8} × run∈{a,b} × attempt∈{1..4} = 16개 모두 `ok=false`. STATUS.md "K=5/8 양쪽, run 2회, 매 시도 4회 전부 실패"는 산술적으로 맞지만, 한 줄로 읽으면 4회 시도로 오해할 수 있음 |
| exp5 LLM v2 (assignment) 결과 보존 | STATUS.md L70 ("다음 할 일") | 한계 명시 + 약함 | run1/2/3 모두 `parsed=true valid=true`이긴 한데 run1은 `groups_used=4` (라벨 4개만 사용, 실효 K=4), run3도 4개. 3런 사이에 결과(파티션)가 동일하지 않음. STATUS.md는 v2를 "다음 할 일"로만 두고 결과 평가는 안 했음 |
| exp5 임베딩 merge silhouette K=5 0.083 / K=8 0.099 / K=10 0.098 | STATUS.md L38 | 검증됨 | `stage2_emb_K{5,8,10}.json` 의 `silhouette` 필드 = 0.08312…, 0.09928…, 0.09789… |

## 3. 특별 항목 (인벤토리가 짚은 위험)

### 3.1 "baseline" 용어 충돌

대상: 00_baseline.md (385 ent / level0=31, 스냅샷 없음, max_cluster_size=10, 2026-06-02) vs repro_run3 (357 ent / level0=40, max=15, 후속 모든 실험의 베이스).

EXPERIMENTS.md를 줄 단위로 훑은 결과:

- L21 "baseline 인덱싱을 돌리고(385 entities, 31 level 0 커뮤니티, 16분, 1.02달러), … 따로 repro_run3 스냅샷(357 엔티티, 40방, orphan 31개)에서 degree 분포와 시간 프로파일을 봤다."
  - 판정: 검증됨. 두 회차 수치는 명확히 분리됨. 단 "시간 프로파일"이라는 L28의 963.9초/798.5초는 baseline(00_baseline.md) 수치이고 degree 상위 표는 repro_run3 수치다. 본문은 "degree 분포와 시간 프로파일을 봤다"를 한 문장에 묶어 어디 출처인지 표시 안 함. 약한 결합. (값 자체는 양쪽 다 맞다.)
- L21 "max_cluster_size와 use_lcc 같은 하이퍼파라미터를 바꿔 가며 N=3으로 자연 편차를 측정"
  - 판정: 과장(약). 03_repro_step3_summary가 분명히 적었듯 "max=15 동일 + cache 새로 N=3"에서 자연 편차가 잡혔고 (`Step 1` 결과 max의 순수 효과는 0). 하이퍼파라미터를 "바꿔 가며"라는 표현은 max 변경과 cache-fresh 재실행을 한 묶음으로 만든다. 03 step3 summary 자체는 "max의 순수 효과 = 0"이라고 정확히 적었으니, EXPERIMENTS.md 본문이 그 결론을 압축할 때 약간 흐려진 케이스.
- L24 "level 0 방 개수가 30, 32, 40 (±10)"
  - 판정: 검증됨. exp2_max15(30), repro_run2(32), repro_run3(40). 모두 max=15 cache 새로. (baseline의 31은 이 분포 안에 포함 안 됨 → 표면적으로는 30~40 사이지만, 03 step3 표 L22~27 보면 baseline은 max=10이라 분리 표기됨.)
- L33 "작업 베이스는 repro_run3 스냅샷으로 고정"
  - 판정: 검증됨 (실험들이 BASE 상수로 repro_run3 사용). 단 "베이스" 단어가 같아서 독자는 baseline ≡ repro_run3로 오해할 수 있음. baseline은 max=10이고 repro_run3는 max=15라서 다른 회차다. 본문이 이 max 차이를 명시하지 않음.

STATUS.md:
- L29 "repro_run3 = 고정된 작업 베이스. 357 entities, level 0 = 40" → 검증됨.
- L92 "baseline: 첫 측정, 건물 약 31개" / L95 "repro_run2 / repro_run3 = 재현성 확인 런. run3 = 실험 5 베이스(357 ent, 40방)" → 두 회차를 명확히 분리. 검증됨.

종합: 두 회차를 정량적으로 혼동한 곳은 못 찾음. 다만 "베이스"라는 단어가 baseline(max=10)와 repro_run3(max=15) 양쪽에 쓰여, EXPERIMENTS.md L33 / L21이 두 회차의 max 차이를 명시 안 한 점은 약한 모호함. **권고**: EXPERIMENTS.md에서 "작업 베이스는 repro_run3 (max=15)" 한 줄만 보강.

### 3.2 "K=10이 K=5보다 앵커 보존 낫다"

exp10 report.md:
- L49~52 표는 should_show, should_demote 두 열을 나란히 둠. K=10은 13/14·7/8, K=5_emb는 11/14·8/8, K=5_llm는 8/14·8/8. should_demote는 K=5가 완벽, K=10은 조선 한 개 keep으로 잘못 분류 (eval.json `should_demote.rows[0] 조선 correct=false`).
- 본문 L53~57은 "K=10에선 embedding/llm 두 전략이 사실상 동일", "K=5에선 embedding이 측우기 4종 keep / llm이 demote" 라는 두 비교만 함. **"K=10 > K=5"라고 단정하는 문장은 없음**. should_demote의 반대 신호도 표에 그대로 노출.

판정: 표 자체는 양쪽 신호를 다 보여줌. EXPERIMENTS.md도 이 비교를 직접 단정하지 않음(K=10 vs K=5 비교는 EXPERIMENTS.md에 없음). → **과장 아님 / 단 분석 약함**.

다만:
- exp10 report 본문이 should_demote 7/8 vs 8/8 비대칭을 한 줄도 안 다룸. K=10의 조선 오분류는 "회귀: 이성계"만 언급되고, "조선이 K=10에서 keep으로 분류되는 것은 should_demote 1개 실패의 원인"이라는 연결이 빠짐. 표는 정확하지만 본문 해석이 한쪽(should_show)에만 가 있음.
- **판정: 증거 약함 + 분석 빠짐**. "K=10 vs K=5 어느 쪽이 낫다"는 결론을 내릴 거면, 두 메트릭의 정의(앵커 should_show / should_demote)와 어느 쪽을 우선시할지의 가중치를 명시해야 함. 현재 본문은 결론을 안 내리니 과장은 아니지만, 독자가 should_show만 보고 "K=10 우세"라고 잘못 읽기 쉬움.

추가 약점: n_runs=1이라 K=10의 13/14·7/8 자체가 한 번의 LLM 출력. exp7에서 본 LLM 변동(곽재우 keep/demote 흔들림 등)을 생각하면 1런 결과로 K비교 단정은 위험. exp10 report L77이 "n_runs=3 안정성 측정은 다음 단계"라고 명시함 → **한계 본인이 표시함**.

### 3.3 "임베딩 병합 ≥ LLM 병합"

세 가지 LLM 병합이 섞이기 쉬워 분해:

#### (a) exp5 v1 partition LLM 병합 (`exp5_llm.py`, `llm_reliability.json`)
- 입력: 40개 community ID를 LLM이 직접 K=5 또는 K=8 그룹으로 분배.
- 결과: K∈{5,8} × run∈{a,b} × 4 attempt = **16/16 실패**. `stage2_llm_K*.json` 파일 자체가 안 생성됨 (성공 0회).
- STATUS.md L41 "완전 실패" 단정. 판정: **검증됨**. 임베딩과 비교할 때 v1은 산출물 자체가 없으니 "임베딩이 완승"이라는 결론은 분명.

#### (b) exp5 v2 assignment LLM 병합 (`exp5_llm_v2.py`, `stage2_llm_v2_K5_run{1,2,3}.json`)
- 입력: community 0~39 각각에 K=5 라벨을 붙이기 (방식 자체는 누락·중복이 구조적으로 잘 안 생김).
- 결과 (`llm_v2_reliability.json`): 3런 모두 `parsed=true, valid=true, missing=[], dup=[]`. 산출물 잘 생성됨.
- 단 실효 K가 흔들림: run1·run3는 라벨 5개 중 4개만 사용 (`groups_used=4`), run2만 5개 사용. 3런 사이에 파티션이 동일하지 않음 (예: community 1·20의 배치가 run마다 다름).
- 큰 덩어리(STATUS.md "194 덩어리"의 원인 community 그룹)는 v2에서도 한 방에 220± 엔티티 정도로 뭉쳐있음. 임베딩 K=8(194) / K=10(160) 대비 더 균형 잡힌다고 보기 어려움. (LLM이 ward와 똑같이 그 그룹을 거대 덩어리로 인식하는 셈.)
- 판정: **증거 약함 + 임베딩 대비 비교 미완**. 어떤 docs도 v2를 임베딩과 head-to-head로 비교 안 함. STATUS.md는 v2를 "다음 할 일"로만 두는데 (L70), 결과 파일은 이미 있음 → docs 자체는 정직(주장을 안 함). 다만 "임베딩 ≥ LLM" 일반 결론을 v2 데이터로 검증한 적은 없음.

#### (c) exp10 centroid LLM 병합 (`room_gen.py::_merge_llm`)
- 입력: ward base_cluster 12개의 centroid를 LLM이 K개 그룹으로 매핑.
- 결과:
  - K=10: embedding/llm 산출이 사실상 동일 (final_sizes 동일, should_show·should_demote 동일, room 이름 동일).
  - K=5: 사이즈 균형은 LLM `[108,79,63,63,44]`이 embedding `[116,106,106,18,11]`보다 좋음. should_show는 embedding 11/14 > LLM 8/14. should_demote는 둘 다 8/8.
- 판정: **검증됨 (분해해서 본 한 메트릭 한 K씩)**. exp10 report 본문 L52~56가 정확히 이 비대칭을 적음 ("K=5 llm 사이즈 균형 더 좋음", "embedding이 측우기 4종 살림"). 본문은 한쪽 단정 안 함. → 과장 아님.

#### 종합 판정
"임베딩 병합 ≥ LLM 병합" 단정은 EXPERIMENTS.md에 없음 (확인). STATUS.md는 v1 partition만 "완전 실패"라 적고, 그게 정확. exp10 report는 K·메트릭 별로 다르게 적어 단정 안 함. → **이 단정은 어디에도 없음**. 인벤토리·감사 프롬프트가 미리 우려한 "한 문장 단정"은 실물 docs에서 발견되지 않았다.

### 3.4 큰 덩어리 숫자 (160 vs 194)

직접 계산:
- repro_run3 level-0 community 40개의 entity 수 분포를 누적해서 stage2_emb_K* 의 `merged_rooms`별 entity 합을 구하면:
  - K=5 community-merge: 가장 큰 방 = community {4,5,9,10,13,17,23,24,27,29,30,33,34} 13개 = **194 ents**
  - K=8 community-merge: 가장 큰 방 = 같은 13개 community = **194 ents** (즉 K=5→K=8에선 안 쪼개짐)
  - K=10 community-merge: 가장 큰 방 = community {4,5,9,13,17,23,29,30,33,34} 10개 = **160 ents** ({10,24,27} 3개가 별도 방으로 분리)

판정:
- exp6 report L558의 "160" = **K=10 community-merge** 최대 방. 검증됨.
- STATUS.md L64~65의 "194 덩어리: 13개 community … K=8에서도 안 쪼개짐" = **K=8 (또는 K=5) community-merge** 최대 방. 검증됨.
- 둘은 **같은 LCC가 K가 커지면 일부 쪼개지는 양상**의 두 단면. 같은 lump이고 다른 K cut. 두 문서는 각자의 K 컨텍스트에서 정확하지만 cross-reference가 없음.

권고: STATUS.md나 exp6 report 어느 한 쪽에 "K=10에서는 13개 중 3개(community 10/24/27)가 떨어져 나가 160이 됨. K=8 이하에서는 13개가 한 덩어리(194)"라는 한 줄 cross-reference 추가하면 독자 혼동을 막을 수 있음. 현 상태에선 **불일치 아님**.

### 3.5 문서에만 있는 주장 (검증 불가 / 한계 명시)

| 주장 | 출처 | 판정 |
|---|---|---|
| exp10 비용 33회 호출 (rubric 1 + LLM-merge 2 + Stage B 4×K) | exp10 report L66~70 | 검증됨 (산수). 11+12+6+7 = 36이지만 본문은 rubric 캐시 hit을 감안해 33이라 적음. cache hit 1회를 빼면 정확히 35? 본문 표는 rubric 캐시 hit 후 stage B 10/10/5/5 + LLM-merge 2(K=10llm, K=5llm) = 10+11+5+6 = 32. 또는 33. 산수 자체로는 ±1 정도 범위. spec.json에 호출 카운트 저장 안 됨 → **검증 가능 범위 안에서 검증됨, 정확도는 ±1 모호** |
| exp10 실측 시간 ~105초 | exp10 report L72 | 검증 불가 | spec.json 어디에도 elapsed 저장 안 됨. 재실행 시 LLM 응답 시간 변동. **아티팩트로 검증 불가** |
| exp9 "자료 품질 confound" | EXPERIMENTS.md L118 / L122 / inventory L115 | 한계 명시 | 본문 스스로 "확정 아니라 confound 있는 추정"이라 적음. **주장 아님** |

## 4. n=1 (LLM 레이어) 결과 한꺼번 모음: 증거 약함 카테고리

exp10 4 combo eval은 모두 단일 LLM 실행. 다음 수치들은 LLM 흔들림으로 변할 수 있음 (재실행 시 변동은 정상, 불일치 처리 X):

- K=10 embedding/llm should_show 13/14, should_demote 7/8
- K=5 embedding should_show 11/14
- K=5 llm should_show 8/14
- 방 이름 (예: "임진왜란과 조선 군사", "조선 인물·제도·과학기기")
- 회귀 사례 "이성계 demote", "조선 keep 오분류"
- coherence_flags coherent (4 combo 전부)

판정: **증거 약함**. exp10 report L77이 "n_runs=3 안정성 측정은 다음 단계"라고 본문이 한계 표시했으므로 단정 톤은 절제되어 있음. EXPERIMENTS.md는 exp10을 직접 인용 안 함 (현재 docs에서 exp10 결과를 다른 곳이 받아 단정한 흔적 없음). → 본인 한계 표시로 약화됨, **과장 아님**.

## 5. 진짜 오류 / 과장 / 증거 약함 / 검증 불가 한눈

### 진짜 오류 (불일치)
- 없음 (이번 패스에서 검증한 결정적 수치 16개 + LLM 결과 12개 항목 모두 저장 파일과 일치)

### 과장
- (약) EXPERIMENTS.md L21 "max_cluster_size를 바꿔 가며 N=3으로 자연 편차를 측정". 03_repro_step3_summary가 "max의 순수 효과 = 0"이라고 분리했음에도, 한 문장으로 묶으면서 max 변경과 cache-fresh 재실행이 같은 차원처럼 읽힘. 사실 N=3 자연 편차는 max=15 동일 + cache fresh 조건에서 잡힌 것. **수정 제안**: 줄을 두 문장으로. "max는 효과 없었고 (Step 1), 같은 max에서 cache 새로 N=3 했을 때 ±10 흔들림 (Step 2)."

### 증거 약함 (LLM 단일 실행)
- exp10 4 combo의 모든 should_show / should_demote 수치, 방 이름, 회귀 사례(이성계 demote, 조선 keep) → 본문은 이미 "n_runs=3은 다음 단계"라 명시. 추가 보강은 다음 회차에서 자연스럽게 해결.
- exp10 report L49~52 표: should_demote가 K=5 8/8 / K=10 7/8로 K=5가 우세인데, 본문 분석은 should_show 쪽에만 가있음. **수정 제안**: "K=10의 7/8 실패는 조선이 keep으로 분류되는 케이스. should_show와 should_demote가 서로 다른 K를 가리키는 비대칭이 있음"이라는 한 줄 보강. (단정 안 해도 됨, 비대칭만 적시.)
- exp5 v2 assignment 결과(`stage2_llm_v2_K5_run{1,2,3}.json`)는 임베딩과 head-to-head 비교 없음. STATUS.md는 v2를 "다음 할 일"로만 두고 결과 평가 보류 (정직).

### 검증 불가 (아티팩트에 메트릭 없음)
- exp10 실측 시간 ~105초 (`spec.json`에 elapsed 미저장)
- 33회 호출 수치는 산수로 ±1 검증, 정확값은 런타임 로그가 보존되지 않아 확인 불가

### 한계 본인이 명시
- exp9 "자료 품질 confound": 본문 스스로 "확정 아님" 표시
- exp7 cluster 6 grab-bag, K=10에서 LLM 변동: 보고서가 흔들림을 정량화해 적시
- exp10 "n_runs=3 안정성은 다음 단계": 본인 한계 표시

### 약한 모호함 (수정 제안만)
- EXPERIMENTS.md "베이스 스냅샷"(repro_run3, max=15)과 "baseline"(00_baseline.md, max=10)의 max 차이를 명시 안 함. 한 줄 보강 권고.
- 큰 덩어리: exp6 "160"(K=10)과 STATUS.md "194"(K=8)는 같은 LCC를 다른 K로 자른 두 단면. cross-reference 한 줄 권고.
- STATUS.md L41~45 "K=5/8 양쪽, run 2회, 매 시도 4회 전부 실패". 산술적으로는 맞지만 "매 시도 4회"가 다소 모호함. "K∈{5,8} × run∈{a,b} × 4 attempts = 16/16 실패"로 풀어쓰면 명료.

## 6. 노트
- 이번 패스는 결정적 부분만 재실행 (`ward linkage`, `_merge_embedding`, parquet/json 직접 읽기). LLM 호출은 비용·변동 사유로 생략.
- 4 combo eval.json + 8 스냅샷 parquet + 3 stage2_emb json + llm_reliability/llm_v2_reliability json을 모두 확인. 검증한 결정적 수치 16개 모두 통과.
- "K=10 vs K=5" / "임베딩 vs LLM 병합" 두 단정은 docs 본문 자체에는 노골적으로 안 적혀있음. 인벤토리가 우려한 표현이 실제 본문에 있는지 확인한 결과, exp10 report 본문은 한쪽 단정을 피하면서도 분석을 should_show 쪽에 편향시켰음.
- 분류는 사람이 함. 이 문서는 판정 근거만 정리.
