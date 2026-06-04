# exp9 rechunk: semantic vs pagesplit 비교

목적: 같은 한국사 자료를 (1) 시언 의미 청크 105개와 (2) 경민 페이지 청크 50쪽으로 각각 인덱싱한 결과를, 같은 모델 설정(gpt-4.1-mini + text-embedding-3-small)으로 비교한다. `create_community_reports` 제외, 그 외 모든 워크플로 통과.

입력 스냅샷: `results/snapshots/semantic_run1`, `results/snapshots/pagesplit_run1`. 평가 산출: `eval_semantic_run1.json`, `eval_pagesplit_run1.json`. ward K=10은 lancedb의 `entity_description` 벡터(1536-dim, L2 정규화)에 scipy ward linkage 적용.

## 1. 머리맞대기

| 지표 | semantic_run1 | pagesplit_run1 |
| --- | --- | --- |
| 입력 단위 | 105 청크 (의미 분할, avg 350자) | 50 쪽 (페이지 단위, avg 825자) |
| 엔티티 수 | 1038 | 755 |
| orphan (degree=0) | 109개, 10.5% | 129개, 17.1% |
| ward K=10 크기 | [82, 114, 82, 35, 243, 85, 106, 193, 65, 33] | [36, 16, 85, 135, 130, 66, 56, 127, 20, 84] |
| 크기 std / mean | 66.7 / 103.8 | 44.7 / 75.5 |
| 최대 클러스터 | 243 (cluster 5) | 135 (cluster 4) |
| 최소 클러스터 | 33 | 16 |
| 앵커 should-show | 8/8 (100%) | 8/8 (100%) |
| 앵커 should-demote | 3/4 (75%, `붕당정치` 누락) | 3/4 (75%, `붕당정치` 누락) |
| 인덱싱 runtime | 428초 | 1113초 |

### 엔티티 수·연결성

semantic 쪽이 +38% (1038 vs 755). 청크가 더 잘게 쪼개져 있어서 같은 사실도 청크별로 다른 표면형으로 추출되고, summarize_descriptions 이후에도 더 많이 살아남은 것으로 보임. 반대로 pagesplit은 페이지 한 장 안에 맥락이 다 들어 있어 더 응집된 entity 집합을 뽑음.

orphan율은 semantic 10.5% < pagesplit 17.1%. 의미 청크 105개로 자르면 chunk끼리 같은 entity를 자주 공유하고 그래서 relationship이 많이 붙음. pagesplit 페이지는 더 띄엄띄엄해서 고립 entity 비율이 더 높음.

### 클러스터 균형

pagesplit이 더 고르다 (std 44.7 vs 66.7). semantic의 cluster 5는 243개 (`조선`·`붕당`·`영조`·`정조`·`사림`·`광해군` 등 정치 슈퍼 클러스터)로 전체의 23%를 차지. pagesplit의 cluster 5는 같은 주제지만 130개로 17%선. 큰 덩어리 문제(repro_run3의 "194 덩어리"와 같은 결)는 두 run 모두에 남아 있지만, pagesplit이 덜 심하다.

### 앵커 배치

should-show 8개는 두 run 모두 다 추출됨. should-demote는 `붕당정치` 한 개만 누락(둘 다, 자료에 띄어쓰기 `붕당 정치`로 들어와서 정확 일치에 안 잡힘). `붕당 정치`는 추출돼 있고, 두 run 모두 정치 슈퍼 클러스터에 들어가 있음.

핵심 차이: **임진왜란 트리오 묶임**
- semantic: 곽재우 cluster 3 (`임진왜란`·`의병`·`일본`), 이순신·거북선 cluster 5 (`조선`·`붕당`). 곽재우와 이순신이 갈라짐.
- pagesplit: 곽재우·이순신·거북선 모두 cluster 6 (`임진왜란`·`이순신`·`왜군`·`조선군`·`곽재우`·`권율`). 깔끔하게 하나로.

**과학 도구 4종**(측우기·자격루·앙부일구·혼천의)은 두 run 모두 같은 클러스터에 모임:
- semantic cluster 8 (n=193, with `과거 제도`·`토지`·`세종`·`농업`)
- pagesplit cluster 4 (n=135, with `농업`·`백성`·`측우기`·`김종직`)

도구끼리는 잘 묶지만 농업·세종 관련 잡다한 entity가 같이 들어가 있어, 도구 4종만 따로 "방"으로 떼려면 후처리(또는 cluster를 더 잘게)가 필요. K=10 자체로는 양쪽 다 완벽한 분리는 안 됨.

훈민정음은 양쪽 다 교육·유학 클러스터에 들어감 (semantic c6: `세종 대왕`·`유교`·`교육 기관`, pagesplit c3: `사림`·`실학`·`교육 기관`). 자료 결대로의 자연스러운 배치.

## 2. repro_run3 대비 (느슨한 참고)

repro_run3 베이스: 357 엔티티, 단일 document 입력, level 0 = 40 커뮤니티. exp9의 두 run은 입력 단위 자체가 다르고(`create_community_reports`도 안 돎) level 0 묶음 비교가 직접 안 되므로, 엔티티 추출 양·앵커 보존만 본다.

- 엔티티 수: repro_run3 357 → semantic 1038 (+191%), pagesplit 755 (+112%). 청크가 잘게 쪼개진 만큼 표면형 entity가 많아짐. 의미 변별이 아닌 양 자체로는 두 rechunk가 모두 풍성하다.
- 조선 hub: degree 41 (repro_run3) → 82 (semantic) → 76 (pagesplit). 엔티티가 많아지면서 `조선` hub의 degree도 비례해서 늘어남. 슈퍼 노드 문제는 그대로 또는 더 심해짐.
- 훈민정음: repro_run3에는 exact 일치 entity 없었음. 두 rechunk run 모두 명시적으로 추출됨. 청크가 잘게 쪼개지면 더 작은 단위 개념까지 entity로 살아남는 효과 확인.
- 앵커 보존: should-show 8/8을 두 run 모두 통과. 청크 전략이 핵심 개념 누락은 일으키지 않음.

## 3. 한 줄 결론

semantic은 엔티티 수·연결성에서 앞서지만 정치 슈퍼 클러스터(243)가 더 비대하고 임진왜란 트리오를 둘로 가르며, pagesplit은 엔티티가 적지만 클러스터 균형과 임진왜란 묶임이 더 깔끔하니, 방 병합(exp5) 후속 단계에 넣을 베이스로는 pagesplit이 더 다루기 쉬워 보인다.
