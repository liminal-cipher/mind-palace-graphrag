# exp17 generalization 보고

회랑 파이프라인이 한국사 교과서가 아닌 새 도메인(통계학 슬라이드 OCR)에서 그대로 작동하는지, 어디까지 자동으로 적응하고 어디서 수동 결정이 들어가는지 기록.

## 자료

| | 값 |
|---|---|
| 코퍼스 | `input/ai_gyoan/AI_교안_정제.txt` |
| 글자 수 | 9604 |
| 정제 | BOM 제거, CRLF 정규화, 빈 줄 1개로 압축. 글자 수 변화 +1자. 노이즈 0개 발견 |
| 도메인 문구 (prompt-tune, rubric에 동일하게 전달) | `통계학 기초 강의 자료 (모집단·표본·확률 분포·가설 검정·상관분석)` |
| entity_types (settings.yaml) | `[개념, 기법, 분포, 지표, 사례, 인물]` |
| max_gleanings | 1 (graphrag 기본; baseline은 2였으나 작은 코퍼스에 영향 적음) |
| max_cluster_size | 15, use_lcc=false |
| 워크플로 제외 | `create_community_reports`, `extract_covariates` (doctrine) |

prompts: `archive/exp17_generalization/prompts/`에 prompt-tune 산출물 격리. baseline `<REPO>/prompts/`와 충돌 없음. 생성된 example 본문은 통계 용어 그대로, 라벨만 6개 entity_type 토큰으로 정규화(`개념`/`지표`)했다.

## 1. 인덱싱 결과 (Phase B step 1-3)

| | 값 |
|---|---|
| 엔티티 | 119 |
| 관계 | 86 |
| text_units | 5 (size=1200 토큰, overlap=100) |
| 시간 | 72.3s (extract_graph 54.2s가 75%) |
| 토큰 | chat 64,554 in / 13,938 out / 임베딩 7,819 in |
| 비용 | $0.048 (gpt-4.1-mini $0.40/$1.60 per M, text-embedding-3-small $0.02/M) |
| 단일 청크 엔티티 비율 | 119/119 = 1.00 |
| pos_first_fine 매칭률 | 32/119 = 0.27 |

### 1-1. 청크가 5개, 섹션이 6개

5개 text_unit의 char span:

| unit | span | 길이 | 자료 내 위치 |
|---|---|---|---|
| #0 | [0, 2068) | 2068 | 표지·통계학 개요·표본추출·일부 평균 |
| #1 | [1865, 4106) | 2241 | 중심경향·산포도 |
| #2 | [3915, 6135) | 2220 | 산포도·시각화·확률 변수·확률 분포 |
| #3 | [5967, 8098) | 2131 | 추론·가설검정·1·2종 오류 |
| #4 | [7914, 9604) | 1690 | t/카이제곱/ANOVA·상관분석 |

청크 1개가 2000자대. 모든 엔티티가 정확히 1개 청크에만 속한다. baseline(한국사 교과서, 12 청크)과 비교해 청크 수가 5배 적다.

### 1-2. entity_type 컬럼이 6개에 머물지 않음

settings.yaml `entity_types`는 6개를 선언하지만 extract_graph 프롬프트의 Steps 섹션이 그 목록을 강제하지 않는다. 결과: 119 엔티티에 63종 라벨이 나타난다. 빈도 분포:

```
지표 9, 개념 9, 확률 분포 6, 통계 지표 5, 조사 방법 5, 목적 4,
특성 4, 지표/통계 수치 4, 통계 기법/가설 검정 3, ...
```

이 컬럼은 클러스터링·배정·정렬에 사용되지 않으므로(doctrine) 실험 결과에 영향 없다. 다만 baseline에서도 동일 현상이 있었다면 prompt-tune의 자동 라벨링은 type 컬럼의 통제 수단이 못 됨.

### 1-3. pos_first_fine 매칭률 0.27

baseline(한국사) 동일 지표는 회차 1에 별도 측정하지 않았으나 surface form이 한자·고유명사 위주라 직관적으로 더 높을 것. 통계학 자료는 같은 개념이 슬라이드마다 한글·영문·괄호 변형으로 등장한다.

| 원본 슬라이드 표기 | 추출된 엔티티 title 후보 |
|---|---|
| 중심경향성(Central Tendency) | `중심경향성`, `중심경향성(CENTRAL TENDENCY)`, `중심경향성 (CENTRAL TENDENCY)` |
| 평균(Mean) | `평균`, `평균(MEAN)`, `평균 (MEAN)` |
| 유의수준 (Significance Level) | `유의수준`, `유의수준(SIGNIFICANCE LEVEL)`, `유의수준<SIGNIFICANCE LEVEL>` |

서로 다른 슬라이드에서 형태가 미세하게 달라지면 extract_graph가 별도 엔티티로 추출한다(community resolution 워크플로 제외). 표면 검색으로 잡히는 건 공백·괄호가 정확히 일치하는 경우뿐이라 매칭률이 떨어진다.

## 2. LLM 목차 (Phase B step 4)

gpt-4.1-mini, temp=0. corpus 전체를 보내고 5~6개 ordered 섹션 + 각 섹션의 verbatim `start_marker` 받음. 오프셋은 `text.find` 으로 후처리(직전 섹션 이후 첫 발견 강제). 결과는 monotonic·distinct.

| # | 이름 | start | end | 길이 | marker | corpus 등장 횟수 |
|---|---|---|---|---|---|---|
| 1 | 통계학 개요와 표본추출 | 0 | 760 | 760 | (forced 0) | (n/a) |
| 2 | 중심경향과 산포도 측정 | 760 | 3993 | 3233 | `중심경향 측정` | 5 |
| 3 | 확률과 확률분포 | 3993 | 6189 | 2196 | `확률 변수와 확률 분포` | 2 |
| 4 | 추정과 가설검정 | 6189 | 7709 | 1520 | `추론` | 4 |
| 5 | 가설검정 방법과 오류 | 7709 | 8363 | 654 | `가설 검정 - 오류` | 1 |
| 6 | 상관분석 기법 | 8363 | 9604 | 1241 | `상관분석 - 개요` | 1 |

비용: prompt 5686, completion 194 토큰. 약 $0.003.

baseline(한국사)은 regex 헤더 파서(exp08 `probe.py`)가 V/V.1/sub 계층을 그대로 잡았다. 이 슬라이드 자료는 헤더 계층이 평면적이라 regex로는 슬라이드 헤더 반복("중심경향 측정", "산포도 측정" 등)만 잡힌다. LLM 경로가 자료 묶음을 만든다.

## 3. TOC arm 배정 (Phase B step 5)

occurrence 가중치를 exp15의 unit 카운트(0/1 indicator)에서 **char-overlap chars**로 바꿈. 이유: 청크가 5개뿐이라 unit 카운트만 보면 각 청크가 dominant 섹션 하나로만 흘러가 6개 방 중 4개만 채워진다. char-overlap 가중도 본질은 같은 한계를 풀지 못한다(아래).

방 크기:

| 방 | 섹션 | 크기 | 비고 |
|---|---|---|---|
| toc_1 | 통계학 개요와 표본추출 | **0** | sec1 길이 760, unit#0 길이 2068이 sec2를 더 크게 덮음 |
| toc_2 | 중심경향과 산포도 측정 | **50** | unit#0+#1 합산 |
| toc_3 | 확률과 확률분포 | 18 | unit#2 dominant |
| toc_4 | 추정과 가설검정 | 28 | unit#3 dominant |
| toc_5 | 가설검정 방법과 오류 | **0** | sec5 길이 654, unit#3·#4 모두 다른 섹션을 더 크게 덮음 |
| toc_6 | 상관분석 기법 | 23 | unit#4 dominant |

작은 섹션(sec1=760, sec5=654)은 청크 어느 한 개로도 가장 큰 overlap을 가지지 못해 비어버린다. unit#0이 sec1과 760자 overlap이지만 sec2와 1308자 overlap이라 unit#0의 entities는 모두 sec2로 갔다.

방 0개가 되는 건 결정적이지만 의도와 어긋남: TOC 묶음은 자료의 학습 흐름을 보존하는 게 목적인데, 자료에 분명 등장하는 두 섹션(개요+표본추출, 검정 방법론)이 0 entity로 남았다. 청크 크기를 줄이면(예: 300~500 토큰) 회피 가능. 이번 회차는 그대로 두고 관찰만.

## 4. GRAPH arm 클러스터 (Phase B step 6)

`archive/exp10_room_gen/room_gen.py`의 `base_cluster(K=6)` 그대로 사용. ward linkage, L2-normalized euclidean. 두 번 돌려 동일 클러스터(`two_runs_identical=True`).

방 크기(pos 기준 재정렬 후):

| 방 | 크기 | LLM 이름 | 일관성 플래그 |
|---|---|---|---|
| graph_1 | 49 | 기초통계 핵심용어 | coherent |
| graph_2 | 22 | 표본추출과 추정 | coherent |
| graph_3 | 8 | 통계학 기초 개념 | type-pile |
| graph_4 | 18 | 상관분석 핵심지표 | coherent |
| graph_5 | 12 | 확률과 확률변수 | coherent |
| graph_6 | 10 | 가설검정 핵심용어 | coherent |

graph_1이 49개로 한쪽 쏠림. 자료 안에서 검정·분산·평균·표준편차·이항·정규·푸아송·t·카이제곱·분산분석이 모두 비슷한 description 어휘로 embedding 공간에 몰린 결과로 보인다. baseline에서는 max_cluster_size=10(또는 exp10 55)이 절대 크기 제한을 했지만 exp17은 15로 두었고 49는 이 제한 위. 이는 base_cluster가 K=6 ward 직접 컷이기 때문(split 단계 미통과). exp10 generate_rooms 전체 파이프라인을 쓰면 split이 49 클러스터를 더 쪼개지만, 본 보고는 base_cluster까지만 비교해 두 arm의 가공 없는 차이를 본다.

## 5. 순서 (Phase B step 7)

방 내부: pos_first_fine ascending. fine_matched 32개는 corpus 내 표면형 위치, 나머지 87개는 entity가 속한 text_unit의 char_start 폴백(`pos_source = "unit"`). 두 점수 모두 결정적.

방 순서:
- TOC arm: 섹션 인덱스 그대로(1→6).
- GRAPH arm: 방 안 첫 entity의 pos 기준 오름차순 재배열.

`rooms_ordered.md` 참조.

## 6. keep/demote 루브릭 (Phase B step 8)

Stage A (도메인-일반 rubric 도출, gpt-4.1-mini temp=0, 1회 호출). sample 60개 entity titles (sorted, deterministic). 결과: 4개 규칙.

```
R1 핵심 통계 개념/방법론 vs 배경 설명용 용어
R2 구체적 수치·지표·통계량 vs 그 특성/상태 설명
R3 공식 명칭·영어 약어 vs 일반 개념/사례/비전문어
R4 검정 절차 핵심 vs 주변 맥락
```

도메인 문구만 통계학으로 바꿨을 뿐, "구체적·이름 붙는 개념 keep, 일반어·사례·배경 demote"라는 도메인-일반 축이 한국사에서와 동일하게 도출됐다. 예시도 통계 용어로 자동 채움(귀무가설/유의수준/Pearson/Spearman keep, 동전/교통량/상여금 demote).

Stage B (방별 keep 선택, NODE_BUDGET=10). 

| arm | kept 총합 | demoted 총합 | 빈 방 |
|---|---|---|---|
| TOC | 33 | 86 | 2 |
| GRAPH | 38 | 81 | 0 |

예 (GRAPH arm):
- graph_5 (확률과 확률변수, 12개) keep 10: 곱셈 법칙(MULTIPLICATION RULE), 덧셈 법칙(ADDITION RULE), 확률 변수(RANDOM VARIABLE), 확률 함수(PROBABILITY FUNCTION), 확률(PROBABILITY), 연속형/이산형 확률변수, PDF, PMF, 확률밀도함수(PDF). demote: `확률 변수 (RANDOM VARIABLE)`(공백 변형 중복), `곱셈 법칙`(영문 없음 중복) 2개. 즉 OCR 중복으로 인한 entity 분할을 demote가 자연스럽게 흡수.
- graph_6 (가설검정 핵심용어, 10개) keep 5: 1·2종 오류, 가설 검정, 귀무가설, 대립가설. demote 5: 일반어 "가설", surface 변형 중복, "가설 검정 결과", "오류 (FALSE NEGATIVE)".
- graph_3 (통계학 기초 개념, 8개) kept=0, coherence=`type-pile`. demoted 8개 전부: 통계, 통계학, 의사결정, 데이터 이해, 시각화, 의사 소통, 의사결정 지원, 패턴 파악. 도메인-일반 루브릭이 일반 우산어를 한 방에 다 내림. 의도된 동작.

### (b) 도메인-일반 루브릭 평가

루브릭은 한국사용 코드 한 줄 수정 없이 그대로 작동한다. 새 도메인의 구체적 명칭(t-검정·카이제곱·Pearson 등)을 keep으로, 흔한 비계어·사례·일반 우산어를 demote로 가른다. graph_3 같은 일반어 방 통째로 0 keep도 자연스러운 반응이다.

다만 OCR 중복으로 발생한 entity 분할(예: `확률 변수 (RANDOM VARIABLE)` vs `확률 변수(RANDOM VARIABLE)` vs `확률변수`)은 demote로 빠지긴 하지만 정보 손실 위험이 있다. extract_graph 단계에서 alias 통합 또는 community resolution이 필요한 자리. 본 보고에서는 산출 그대로 두고 명시.

## 7. 비교 산출 (Phase B step 9)

`blind_compare.json` (중립 set1/set2), `blind_key.json` (set1=toc, set2=graph) 형식은 exp16 그대로.

| 지표 | TOC | GRAPH |
|---|---|---|
| 방 크기 분포 | [0, 50, 18, 28, 0, 23] | [49, 22, 8, 18, 12, 10] |
| 평균 방 크기 | 19.83 | 19.83 |
| 최대 방 | 50 | 49 |
| 최소 방 | 0 | 8 |
| 빈 방 수 | 2 | 0 |
| 전 엔티티 배정 | 119/119 OK | 119/119 OK |
| 재현성 | 결정적 (동점 = 섹션 idx) | 두 번 동일 |

사용자 doctrine 따라 새 앵커 정의 없으므로 앵커 동거 지표는 생략(자리: 본 보고 7절 마지막에 "새 자료는 아직 anchors 미정의" 명시).

## 8. 명시 평가

### (a) 이 자료에서 TOC가 성립하나, 아니면 그래프가 필수 폴백인가?

TOC 단독은 6개 방 중 2개 비움. 자료 자체 흐름은 LLM 목차가 자연스럽게 잡았지만(이름·marker·길이 모두 합리적), 5개짜리 text_unit 위에서는 작은 섹션이 큰 청크에 흡수돼 entity가 할당될 길이 없다. 청크 크기를 줄이면 회피 가능하나 본 회차 settings 유지.

GRAPH arm은 빈 방 0개, 모두 8~49 entity. 단 한 방이 49개로 쏠림(전체 41%). max_cluster_size·split을 적용하면 깨질 클러스터.

결론: 이 자료 크기에서 어느 한 arm도 단독으로 잘 작동하지 않는다. TOC가 학습 흐름 척추를 잡되 GRAPH가 빈 자리를 메우는 hybrid가 필요해 보인다. 본 회차는 두 arm의 raw 출력을 그대로 비교만 한다.

### (b) 도메인-일반 루브릭이 새 도메인에서 특수 개념을 남기고 일반어를 내리나?

작동. 6절·rubric.json 참조. R1~R4 규칙 자체가 도메인-중립이고 예시만 통계 용어로 자동 채움. 결과는 keep에 구체적 검정·지표·공식 명칭, demote에 일반 우산어·사례·OCR 중복 변형. graph_3이 통째로 0 keep된 게 의도와 일치.

## 9. 한계·관찰

- **자료 크기**: 9604 chars / 5 text_units. 규모 스트레스 테스트가 아닌 일반화 가능성 점검.
- **OCR 중복 변형**: 같은 개념이 공백·괄호·영문 표기 차이로 2~3개 entity로 분할. extract_graph 단계의 alias 통합 또는 community resolution 보완 자리.
- **entity_type 통제 부재**: settings 6개와 무관하게 63종 라벨이 나옴. 본 보고에서는 사용 안 함, 다만 type 컬럼을 외부 가공에 쓰려면 prompt 수정 필요.
- **TOC arm 빈 방**: 청크 크기 vs 섹션 크기 미스매치의 직접적 결과. chunking.size를 줄이면 해결 가능. doctrine상 "하드코딩 앵커 금지"라 청크 크기 조정도 본 회차에서는 안 함.
- **GRAPH arm 한 방 쏠림**: 49개. base_cluster까지만 비교. exp10 generate_rooms의 split+merge 파이프라인을 통과시키면 균형 잡힐 듯하지만 두 arm을 공평하게 base만 비교했다.
- **결정성**: 두 arm 모두 결정적. keep/demote는 temp=0이지만 Azure 응답은 호출마다 미세 변동 가능(섹션 이름 등). marker·offset 그라운딩과 ward 클러스터링은 비트 단위 동일.
- **앵커 미정의**: 한국사용 `should_show`/`should_demote` 앵커 리스트는 도메인 의존이라 통계학 자료에 사용 불가. 새 앵커 도출은 본 회차 범위 외.

## 산출물

```
archive/exp17_generalization/
  PHASE_A_CHECKPOINT.md          # Phase A 종료 체크포인트
  clean_corpus.py                # OCR 정리 스크립트
  cleanup_report.json
  settings.yaml                  # exp17 설정 (워크플로 제외, entity_types 6개)
  prompts/                       # prompt-tune 산출 (격리)
  snapshot.py                    # output → snapshot 동결
  snapshot/                      # entities/relationships/text_units 등 + lancedb
  index_metrics.py               # corpus/count/time/cost/pos_first_fine
  toc_gen.py                     # LLM 목차 생성 + char-offset 그라운딩
  toc_llm.json                   # 6개 섹션 spec
  build.py                       # TOC+GRAPH 빌드 + LLM rubric + keep/demote
  rubric.json                    # Stage A 산출 (재사용 캐시)
  toc_rooms.json                 # TOC arm 방
  graph_rooms.json               # GRAPH arm 방
  keep_demote.json               # 두 arm keep/demote 압축 뷰
  blind_compare.json             # 중립 set1/set2 비교 자료
  blind_key.json                 # set 라벨 공개 (평가 후 사용)
  metrics.json                   # 인덱싱 + 방 메트릭 통합
  rooms_ordered.md               # 사람 가독 출력
  REPORT.md                      # 이 문서
```
