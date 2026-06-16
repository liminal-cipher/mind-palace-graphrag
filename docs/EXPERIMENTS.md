# 실험 누적 노트

한국사 자료를 1인칭 3D "기억의 궁전"으로 만들 때, 자료 속 개념들을 어떻게 묶어서 "방"으로 보여줄지를 정하기 위한 실험들이다. 같은 자료를 여러 방식으로 인덱싱하고, 어떤 묶음 방법이 외울 만한 개념을 잘 살리는지 비교해왔다.

용어 (처음 한 번):
- 엔티티(entity): 자료에서 뽑은 인물·사건·사물·장소 같은 개념 단위. GraphRAG가 LLM으로 추출함.
- 관계(relationship): 두 엔티티가 같은 문맥에 등장하면 잇는 선.
- degree: 한 엔티티가 다른 엔티티와 연결된 수. 크면 자료 전반에 자주 나오는 개념.
- orphan: 다른 엔티티와 연결이 하나도 없는(degree=0) 고립 엔티티.
- 커뮤니티(community): GraphRAG가 관계 그래프 위에서 자동으로 묶은 덩어리. level 0 커뮤니티가 가장 큰 묶음이라 "건물(방의 묶음)" 후보로 검토했으나 exp6에서 폐기됨(거대 덩어리 문제). 정본 palace는 LLM TOC 섹션을 방으로 쓴다.
- 임베딩(embedding): 개념의 의미를 1536차원 숫자 벡터로 나타낸 "지문". 비슷한 개념끼리 값이 가깝다.
- 클러스터(cluster): 그 지문들을 가까운 것끼리 자동으로 묶은 덩어리. 방 후보로 본다.
- 청크(chunk): 자료를 인덱싱 전에 자르는 한 조각. 너무 크면 한 조각이 여러 주제에 걸치고, 너무 잘게 자르면 같은 개념이 조각마다 따로 뽑힐 수 있음.

베이스 스냅샷: `snapshots/repro_run3/` (357 엔티티, level 0 = 40방). 이후 실험은 매번 새로 추출하지 않고 이 스냅샷을 입력으로 쓴다 (LLM 비결정성으로 ±10 흔들림이 있어 재추출하면 비교가 안 됨).

## exp1 ~ exp4: 무엇이 "중요한 개념"인가, 그리고 인덱싱 시간은 어디로 가나

**질문**: 자료에서 뽑힌 엔티티 중 외울 핵심(예: 측우기, 이순신)은 어떻게 골라내나? GraphRAG가 주는 신호(degree, 커뮤니티 등) 중 뭐가 "중요도"에 맞는가?

**한 일**: 같은 한국사 자료(20,921자, 교과서 정제본)에 baseline 인덱싱(`max_cluster_size=10` 기본값, 385 entities, 31 level 0 커뮤니티, 16분, 1.02달러)을 돌리고, 같은 입력 위에서 `max_cluster_size`와 `use_lcc`(고립된 그래프 섬을 버릴지) 같은 하이퍼파라미터를 바꿨다. `max_cluster_size` 변경은 추출 결과를 고정해 두고 보면 level 0 방 수에 순효과가 0이다. 방 수 ±10 흔들림은 별개로 같은 `max=15`에서 캐시-프레시 재인덱싱을 N=3 돌렸을 때 나온 LLM 재추출 분산이다(30/32/40). 따로 repro_run3 스냅샷(357 엔티티, 40방, `max=15`, orphan 31개)에서 degree 분포와 시간 프로파일을 봤다. baseline(max=10, 385 ent, level0=31)과 repro_run3(max=15, 357 ent, level0=40)은 서로 다른 런이다.

**결과**
- 자연 편차: 같은 설정으로 새로 추출하면 level 0 방 개수가 30, 32, 40 (±10). LLM 비결정성 때문. → 매번 새로 추출하면 비교가 안 되니 스냅샷 기반 작업으로 전환.
- degree 상위가 외울 핵심과 안 맞음: degree 1위 `조선`(41), 2위 `사림`(17), 3위 `정조`(17), 4위 `임진왜란`(16), 5위 `영조`(12). 일반어·집단명이 상위를 차지하고 외울 만한 구체적 사물은 더 아래에 깔림.
- orphan 31개(8.7%): 자료엔 등장하지만 관계가 안 잡혀 고립된 엔티티. 그중에 측우기·자격루·앙부일구·혼천의·인지의·금속활자 같은 과학기기, 조선왕조실록·고려사·고려사절요·동국통감·국조오례의·동문선·삼강행실도·팔도지리지 등 주요 사료·문헌 8종이 다 들어 있어 외울 핵심이 다수. (참고: `use_lcc=true`를 켜면 의병 인물 7명, 사화·환국·예송 등 다른 핵심까지 같이 사라진다.)
- `use_lcc=true` 옵션은 비연결 섬을 버려 level 0을 40 → 16으로 줄였지만 357개 중 112개(31%)가 같이 사라짐. 그 안에 위 과학기기·의병이 그대로 들어 있어서 탈락.
- 시간 분포: 전체 인덱싱 963.9초 중 community report 생성이 798.5초(83%)를 잡아먹음. 추출 자체는 138.4초.

**그래서**
- degree만으론 "외울 만한 것"을 못 고른다. 다른 신호가 필요하다 → exp5에서 entity type으로 시도.
- 자연 편차가 ±10이라 매번 인덱싱은 비교 불가능. 작업 베이스는 repro_run3 스냅샷으로 고정.
- 인덱싱 시간 대부분이 community report라 그 결과를 안 쓰는 실험은 community report 워크플로를 빼면 5배 이상 빨라진다 (exp9에서 활용).

## exp5: 엔티티 종류(type)로 중요한 것 가르기

**질문**: GraphRAG는 엔티티마다 type(예: "인물", "발명품", "지역")을 같이 뽑아준다. 그 type으로 keep/demote(살릴지 가라앉힐지)를 나누면 degree보다 잘 나눠지나?

**한 일**: repro_run3 스냅샷에서 type 문자열을 정규화해 keep 버킷(인물·문헌·사건·발명품·문화재 = 142개)과 demote 버킷(지역·집단·국가·시대·일반개념 = 104개)으로 분류. orphan 31개는 가장 가까운 건물(엔티티 임베딩 코사인)로 배정.

**결과**
- type 기준으로는 `조선`·`백성`·`성리학` 같은 일반어가 깔끔하게 demote 쪽으로 빠짐. degree 기준보다 외울 핵심을 위로 더 잘 올림.
- orphan 31개 중 과학기기 4종(측우기·자격루·앙부일구·혼천의)이 keep으로 살아남고, 사료·문헌 8종(조선왕조실록·고려사·고려사절요·동국통감·국조오례의·동문선·삼강행실도·팔도지리지)도 keep 쪽에 들어옴.
- 단점: 어떤 entity는 LLM이 type 안 뽑아 "unknown"이 111개 (전체의 31%). 이건 후속 보정이 필요.

**그래서**: type은 degree보다 나은 신호다. unknown 처리만 보완하면 keep/demote rubric의 1차 안전망으로 쓸 수 있다.

## exp6: 방을 만드는 두 방법 비교 (임베딩 클러스터 vs GraphRAG 커뮤니티 병합)

**질문**: 방을 GraphRAG 커뮤니티로 묶는 대신, 엔티티 임베딩(개념의 지문)을 직접 클러스터해서 묶으면 (1) orphan이 알아서 흡수되나, (2) 거대 덩어리가 갈라지나, (3) 묶음이 주제별이냐(좋음) type별이냐(나쁨).

**한 일**: repro_run3 357개 엔티티 임베딩(1536차원, L2 정규화)을 scipy ward linkage로 직접 K=10 클러스터링 → 결과를 같은 자료에서 만든 community 병합 결과(exp5의 stage2_emb_K10)와 같이 놓고 비교.

**결과**
- 크기 분포 (방 10개 크기, 내림차순):
  - 직접 임베딩 클러스터: [51, 50, 48, 45, 44, 34, 24, 23, 20, 18] (균등)
  - GraphRAG community 병합: [160, 45, 35, 34, 18, 10, 8, 7, 5, 4] (거대 덩어리 1개 + 자투리)
- orphan 31개 모두 임베딩 클러스터에 자연스럽게 흡수됨. 예: 측우기·자격루·앙부일구·혼천의가 클러스터 6(`정도전`·`평안도`·`충청도` 등이 있는 곳)에 같이 들어감. 자료상 그 지역에 같이 나와서.
- 주제 응집 앵커 체크:
  - 임진왜란 그룹(임진왜란·이순신·권율·김시민·거북선·정유재란): 7/8이 같은 클러스터로 모임. 곽재우만 다른 곳.
  - 세종 과학 그룹(세종·도구 4종·훈민정음·집현전·장영실·김종서·최윤덕): 모드 클러스터 6에 4/9(과학기기 4종). 세종은 cluster 4, 훈민정음은 cluster 2로 따로 떨어짐. 도구끼리는 잘 모이지만 세종/훈민정음과는 같은 방이 안 됨.

**그래서**: 방은 임베딩 직접 클러스터로 만든다. 커뮤니티 병합은 결정적 알고리즘이지만 거대 덩어리(size 160)가 생겨 3D 인테리어 제작이 안 됨 (건물 하나가 사실상 통째).

## exp7: 방 위에 LLM 올려서 방 이름 짓고 핵심 개념 선별

**질문**: exp6 임베딩 클러스터로 방은 잘 만들어졌다. 그 위에 LLM을 얹어 (1) 방마다 이름 붙이고 (2) 안의 엔티티 중 외울 핵심만 골라내는 게 실제로 일관되게 되나? 클러스터가 좀 지저분해도 선별은 흔들리지 않는가?

**한 일**: 도메인 "한국사"와 클러스터 샘플을 LLM(gpt-4.1-mini, temp=0)에 주고, 먼저 keep/demote rubric을 LLM이 직접 도출하게 한 뒤(stage A), 그 rubric으로 클러스터 10개 각각에 방 이름과 keep/demote 분류를 시킴(stage B). 같은 입력으로 3회 독립 실행해 안정성 측정.

**결과**
- LLM이 도출한 rubric은 3런 모두 "구체적 명칭과 역할이 있는 인물·사건·제도·문서·장소는 keep, 추상 개념·일반 지명·집단명·시대는 demote"라는 같은 원칙으로 수렴. 사람이 짠 type 규칙과 거의 같음.
- 방 이름 안정성: 10개 중 4개는 3런 완전 동일(`조선 초기 군주와 군사`, `조선 법전과 문헌`, `조선 정치와 의병`, `조선-일본 교역과 외교`). 나머지 6개는 의미는 같지만 단어 추가·교체 변형이 있고, 그중 1개(클러스터 3: `조선 교육과 사림 붕당` / `조선 교육과 붕당 정치` / `조선 교육과 사림 세력`)는 3런이 다 다름.
- keep 선별 안정성(3런 jaccard 평균): 클러스터 2(법전·문헌) 0.98, 1(군주·군사) 0.87, 8(행정) 0.83, 6(인물·지리·제도) 0.77 → 일관성 높음. 클러스터 3(교육·사림 붕당) 0.17, 9(북방 군사) 0.00으로 흔들리는 곳도 있음.
- coherence 플래그: 10개 중 9개는 3런 모두 `coherent`로 평가. 클러스터 6 한 곳만 `grab-bag`(잡동사니)으로 매번 같게 평가 → LLM이 클러스터 품질도 일관되게 본다.
- should-show 앵커(외울 핵심) 14개 중 측우기·자격루·앙부일구·혼천의·정도전·이성계 6개는 3런 모두 keep. 이순신·임진왜란·거북선·권율·김시민·곽재우·인지의는 run1·2는 keep, run3는 missing(run3 출력 자체에 누락) 패턴. 훈민정음은 run2 demote, run1·3 keep. should-demote 앵커 8개 중 3런 모두 demote는 백성들 하나뿐, 함경도는 3런 모두 keep(잘못 분류), 조선·백성·성리학은 run1·2 demote / run3 missing, 경상도·전라도는 run2에서 keep으로 흔들림.
- 비용: 3런 × (rubric 1번 + 클러스터 10번) = 33회 호출, prompt 88k + completion 23k 토큰.

**그래서**: LLM 선별기는 클러스터가 좀 지저분해도(grab-bag) 안의 keep/demote 판단이 대체로 일관됨. 단 경계가 모호한 항목(지명·세력 이름 등)은 런마다 갈릴 수 있음. 방 이름은 같은 의미 다른 단어 정도로만 흔들림. 임베딩 클러스터 + LLM 선별 조합을 후속 방 병합 파이프라인의 기본 단위로 채택할 수 있다.

## exp8: 책의 목차(섹션)로 방을 나눌 수 있나

**질문**: 자료가 교과서면 목차(섹션)가 이미 사람이 만든 묶음이다. 그걸로 방을 나누면 LLM 묶기 없이도 의미 있는 건물이 만들어지나?

**한 일**: 교과서 본문(20,921자)에서 헤더를 정규식으로 추출 → 46개 섹션(roman 2 + number 4 + sub 40). repro_run3의 text_unit(1200토큰 청크) 12개와 357개 엔티티가 각각 어느 섹션에 속하는지 매핑.

**결과**
- text_unit이 너무 큼: 청크 한 개가 평균 5.12개 섹션에 걸침. 12개 청크의 섹션 수는 2~8개 분포(최소 2, 최대 8)이고 절반은 5~6개 섹션을 한꺼번에 덮음.
- 그 결과 357개 엔티티 100%가 2개 이상 섹션에 걸치게 됨. 단일 섹션 매핑 0개. 어떤 엔티티는 18개 섹션에 걸침(`조선`·`백성` 같은 일반어).
- 스팟체크: 측우기·자격루·앙부일구·혼천의가 [13, 14, 15, 16] 네 섹션에 다 걸쳐 있음. 이순신·임진왜란·권율·김시민·거북선이 [21, 22, 23, 24, 25] 다섯 섹션에 다 걸침. 청크 경계 탓에 진짜 소속 섹션을 못 가린다.

**그래서**: 목차 자체가 문제는 아니고, 현재 자료의 청크 단위가 섹션보다 크다 보니 개념과 섹션을 잇는 사슬이 다 뭉개진다. 청크를 섹션 단위로 다시 잘라야 의미 있는 비교가 됨 → exp9의 동기.

## exp9: 자료 잘게 다시 잘라보기 (semantic 청크 vs pagesplit 청크)

**질문**: 한 청크가 한 의미 단위/페이지 안에 들어가게 자르면 (1) 엔티티 추출이 풍성해지나, (2) 같이 다닐 개념끼리 더 잘 묶이나, (3) 자르는 방식 자체가 결과에 큰 영향을 주나?

**한 일**: 같은 한국사 자료를 두 방식으로 다시 자름. semantic = 의미 청크 105개(평균 350자), pagesplit = 페이지 청크 50쪽(평균 825자). 둘 다 같은 모델 설정으로 community report만 빼고 풀 파이프라인 인덱싱. ward K=10 클러스터링과 앵커 8+4개 체크리스트로 결과 비교.

**결과**
| 지표 | semantic_run1 | pagesplit_run1 | 참고: repro_run3 |
| --- | --- | --- | --- |
| 입력 단위 | 105 청크 | 50 쪽 | 1 doc |
| 엔티티 수 | 1038 | 755 | 357 |
| orphan 비율 | 10.5% (109개) | 17.1% (129개) | 8.7% (31개) |
| ward K=10 크기 std | 66.7 | 44.7 | (해당 없음) |
| 최대 클러스터 | 243 | 135 | (해당 없음) |
| 앵커 should-show | 8/8 | 8/8 | 7/8 (훈민정음 누락) |
| 앵커 should-demote | 3/4 | 3/4 | 3/4 |

- 엔티티 양은 두 rechunk 모두 repro_run3 대비 2~3배. 잘게 자르면 같은 자료라도 표면형 entity가 많이 살아남는다.
- semantic이 pagesplit보다 38% 더 많은 엔티티를 뽑고 orphan율도 낮음(연결성 좋음). 의미 청크끼리 같은 entity를 공유해 관계가 잘 붙은 결과.
- 클러스터 균형은 pagesplit이 더 고움. semantic의 cluster 5(`조선`·`붕당`·`정조`·`영조`)는 243개로 전체의 23%를 차지하는 거대 덩어리. pagesplit의 같은 주제 클러스터는 130개로 17%선.
- 임진왜란 트리오(곽재우·이순신·거북선): semantic은 곽재우(cluster 3)와 이순신·거북선(cluster 5)으로 갈라짐. pagesplit은 cluster 6에 모두 모임. pagesplit이 깔끔.
- 과학 도구 4종(측우기·자격루·앙부일구·혼천의)은 두 run 모두 같은 클러스터에 깔끔하게 모임. 다만 농업·세종 잡엔티티와 같이 들어가 있어서 도구 4종만 따로 떼려면 추가 후처리가 필요.
- 두 run 다 repro_run3보다 orphan율이 높음. 자르는 단위 자체가 응집을 떨어뜨릴 수 있음.

**그래서**: 어떻게 자르냐(semantic vs pagesplit)는 영향이 있지만, 더 큰 레버는 입력 자료 품질로 보인다. 두 run 모두 정치 주제 거대 덩어리는 그대로 갖고 있다. (단 exp9는 같은 자료·다른 청킹 비교라 청킹 변수만 격리되어 있고, baseline(repro_run3)은 다른 자료(정제 교과서)라 "자료 품질" 변수가 분리되지 않는다. 따라서 확정이 아니라 confound 있는 추정.) 후속 방 병합 베이스로는 임진왜란 묶임이 깔끔하고 균형도 더 좋은 pagesplit이 다루기 쉬워 보인다.

## exp10: end-to-end 룸 제너레이터 (모듈화 + 4 combo 비교)

**질문**: exp6(임베딩 클러스터)·exp7(LLM rubric·이름·keep 선별) 결과를 한 줄 파이프라인으로 묶으면 (1) 4 combo(K=10/5 × embedding/llm merge)에서 결과 모양이 어떻게 달라지나, (2) exp7 run3에서 이순신·임진왜란·거북선이 통째로 사라진 누락 사고를 코드 가드로 막을 수 있나, (3) 도메인 무관 모듈로 짤 수 있나.

**한 일**: repro_run3 357 엔티티에 `load_snapshot → base_cluster(k_base=12) → split_oversized(max=55) → merge_to_k(embedding|llm, K) → derive_rubric(stage A) → assign_rooms(stage B) → check_invariants`로 잇는 importable 모듈(`room_gen.py`)을 짜고, 4 combo로 진입점(`run_repro_run3.py`) + 도메인 무관 평가기(`eval_rooms.py`) + 외부 앵커 JSON(`anchors_korean_history.json`, should_show 14/should_demote 8)을 분리. 불변식 가드: kept ∪ demoted == 입력(누락 0), 방 수 ≤ K ≤ 10, 방당 kept ≤ node_budget(=20). Stage B 출력은 keep_titles만 받고 demote는 set-difference로 자동 도출(누락 사고의 구조적 봉쇄).

**결과**
| combo | final sizes | coherent | should_show | should_demote |
| --- | --- | --- | --- | --- |
| K=10 embedding | [93,82,39,34,24,23,20,18,13,11] | 10/10 | 13/14 | 7/8 |
| K=10 llm | [93,82,39,34,24,23,20,18,13,11] | 10/10 | 13/14 | 7/8 |
| K=5 embedding | [116,106,106,18,11] | 5/5 | 11/14 | 8/8 |
| K=5 llm | [108,79,63,63,44] | 5/5 | 8/14 | 8/8 |

- 전수보존: 4 combo 모두 357/357, forced_demote=0. exp7 run3의 통째 누락(이순신·임진왜란·거북선) 재발 없음.
- 두 메트릭이 비대칭. should_demote는 K=5가 8/8로 깔끔(K=10은 `조선`을 잘못 keep으로 분류해 7/8), should_show는 K=10이 13/14로 우세. K=10이 더 낫다고 단정하기 어려움.
- K=10에선 embedding과 llm 두 merge 전략이 거의 같은 결과(방 이름·구성). k_base 12에서 K 10으로 가는 merge가 트리비얼해서 그렇다.
- K=5에선 두 전략이 명확히 다르다: embedding은 측우기·자격루·앙부일구·혼천의를 한 방(`조선 제도·인물·문서·지명`)의 keep으로 살리고, llm은 같은 4종을 `조선 의병과 지도자`로 묶고 keep으로 안 살림. 라벨이 좁아지면 그 안의 도구류가 demote로 밀려난다.
- merge_to_k의 embedding 전략은 클러스터 centroid 위 ward linkage. 초기 greedy nearest-centroid는 K=5에서 [285,23,20,18,11]로 체이닝됐고, ward-on-centroids로 바꿔 [116,106,106,18,11]까지 회복.
- 회귀 1건: K=10에서 이성계가 demote로 분류됨(exp7은 3런 모두 keep). 새 프롬프트가 "콕 집어 외울 대상" 기준을 더 좁게 잡으면서 건국자 같은 큰 분류가 demote로 밀린 영향으로 추정 → 안정성은 exp12에서 추적.
- 비용: 4 combo + 캐시 rubric 1회 = 총 33회 호출(rubric 1 + LLM-merge 2 + Stage B 4×K), 실측 시간 합 ~105초.

**그래서**: 결정적 파이프라인 + LLM 선별기를 한 줄로 잇는 도메인 무관 모듈이 동작. 누락 사고는 keep-only 프롬프트 + set-difference로 구조적으로 봉쇄. 4 combo 중 K=10이 should_show에서, K=5가 should_demote에서 우세해 한쪽으로 확정 못함. 이성계 demote 회귀는 단일 패스 흔들림인지 패스 간 일관 결과인지 측정 필요 → exp12. 자세한 표·산출은 `archive/exp10_room_gen/report.md`, `archive/rooms/`.

## exp11: K(방 수) 자동 결정 신호 찾기

**질문**: K(방 수)는 사람이 정해야 하는 값이었다. 실루엣·엘보 같은 일반 지표 대신 3D 인테리어 제작 제약(방 ≤10, 방 크기 균형)에 맞춰 자동으로 고를 신호가 있나? 그러려면 K가 결과 모양을 어떻게 바꾸는지부터 본다.

**한 일**: repro_run3 357개 엔티티에 같은 결정적 파이프라인(`base_cluster(k_base=12) → split_oversized(max=55) → merge_to_k(K, embedding)`)을 K=2..10 sweep. LLM 0회. 동일 입력 2회 호출로 결정성 확인(K=5에서 IDENTICAL).

**결과**
- 방 크기 분포(desc) + max/min 비:
  - K=5..9: 116짜리 거대 blob 1개가 살아남아 max/min ~10.55로 정체.
  - K=10: 그 blob이 [93, 82]로 쪼개지면서 비가 8.45로 떨어짐. 상한 10 안에서 가장 균형.
  - K=2..4: 222짜리 슈퍼블롭 잔존, 비가 더 나쁨(12.33 ~ 20.18).
- 결정성: 같은 K에서 두 번 돌려 멤버 구성 완전 동일. ward-on-centroids는 결정적이라 K만 정하면 결과 고정.

**그래서**: 데모·확정값 = K=10. 제품 auto-K 신호는 실루엣·엘보가 아니라 도메인 제약 기반 (방 수 상한 10, 방 크기 상한 ~100, 두 조건 통과 K 중 max/min 비 최소). repro_run3에선 size 100 상한을 두면 K=9까지는 116짜리에 막혀 다 탈락, K=10만 통과. 자세한 표·산출은 `archive/exp11_k_sweep/report.md`.

## exp12: Stage B n=3 안정성 (LLM 다수결)

**질문**: exp7에서 Stage B 1회로 본 결과가 다음 패스에서 같은가? (1) 앵커 recall은 n=1과 n=3에서 다른가, (2) 다수결(>= 2/3)이 단일 패스 대비 어떤 엔티티를 뒤집는가, (3) K=10과 K=5에서 안정성이 비슷한가.

**한 일**: 결정적 클러스터링은 K=10/K=5 각각 1회, Stage B만 클러스터당 3패스 반복(gpt-4.1-mini, temp=0). rubric은 캐시 hit으로 Stage A LLM 0회. 한국사 앵커(should_show 14 / should_demote 8)와 다수결 규칙(votes > n/2)으로 채점.

**결과**
- K=10 앵커 안정: should_show 13/14, should_demote 7/8가 3패스 모두 동일. 다수결도 동일. 앵커 단위 flip rate 0/22. n=3은 앵커 recall엔 no-op.
- K=5 앵커 흔들림: should_demote 8/6/7로 패스 간 다름(flip 37.5%). 클러스터가 거칠어 경계 라벨이 흔들림. 안정성 평가 fail.
- 전체 357 엔티티 단위 flip: K=10 32/357 (9.0%), K=5 27/357 (7.6%). 앵커가 아닌 비-앵커 ~7%가 패스 간 결정이 다르며 다수결이 그 결정을 정리.
- 이성계 회귀: K=10/K=5 모두 3패스 demote, 임진왜란 방 배치. n=3로는 안 풀림(→ exp13).
- 방 이름 일관성: K=10 10방 중 5방 3패스 동일, 5방은 어순·단어 변형(의미 동일 수준).

전체 keep-set 단위의 정밀 일치도(per-room jaccard, 다수결이 정리한 split 엔티티 수)는 confirmed-pipeline runner가 측정한다(`archive/pipeline/report.md`): per-room mean pair-jaccard 0.906, min 0.6154(room 4 [8, 13, 13]이 가장 흔들림), split entities 26/357(7.3%), 만장일치 방 5/10, 방 이름 unanim 9/10.

**그래서**: 앵커 recall만 본다면 K=10·n=1로 충분. 전체 keep-set의 재현성·일관성을 원하면 n=3 (경계 ~7% 엔티티를 매번 같은 결정으로 수렴). K=5는 평가에서 제외. 확정·평가 런 = n=3, 제품은 7% churn 감수 시 n=1도 후보. 자세한 표는 `archive/exp12_n3_stability/report.md`.

## exp13: 도메인 무관 generic 사전 제거 (degree pre-cut)

**질문**: exp12에서 이성계가 임진왜란 방에 끌려가 demote로 분류됐다. 가설: 고차수 일반어(`조선`·`사림`·`정조` 등)가 그래프 허브로 작용해 주변 엔티티를 끌어모아 의미 응집을 흐린다. 그렇다면 그 허브들을 클러스터링 전에 떼면 이성계가 본래 자리로 돌아가나? 도메인 무관 degree 사전 컷이 처방이 되는지 본다.

**한 일**: degree desc 상위 N개(N ∈ {0, 10, 20, 30})를 제거하고 나머지로 같은 결정적 파이프라인 돌림. LLM 0회.

**결과**
- 제거 목록에 일반어와 외울 핵심이 섞임: N=10에서 `조선`·`성리학` 같이 `임진왜란`이 쓸려나가고, N=20에 `이순신`, N=30에 `이성계` 자체가 제거됨. 진단 대상이 제거되어 평가가 깨짐.
- 방 크기 균형: N=10/30은 베이스라인보다 더 불균형(max/min 12.50, 17.00), N=20만 5.91로 좋아짐. 단조 응답 아님.
- 이성계: N=10에선 이순신·권율과 떨어져 `세조`·`세종`·`태조` 같은 조선 군주 방으로 갔으나 `정도전`은 다른 방. N=20에선 이순신이 제거된 채 다시 다른 방. 안정 회복 아님.

**그래서**: 미채택. degree 사전 컷은 너무 뭉툭함. 이성계 오배치는 단순 degree 문제가 아니라 hub-mediated(`임진왜란` 허브를 통해 이순신·권율과 결속, 허브 제거 시 풀리지만 처방 정확도 낮음)이라 진단·처방이 잘못 매핑됨. 진짜 처방은 추출·청크·임베딩 품질(description·CU 품질)에 있고, 후처리로 풀려면 degree가 아니라 그래프 토폴로지나 LLM 단계의 keep/demote 판단에 위임하는 쪽이 맞아 보임. 자세한 표는 `archive/exp13_generic_filter/report.md`.

## exp14: overlap200 step-3 LLM-only 방 설계 재현성 (n=3)

**질문**: 팀원의 overlap200 아이디어 step-3(LLM에 GraphRAG 커뮤니티 + 엔티티를 통째로 주고 학습 흐름 중심 "방"을 한 번에 설계시키는 단계)을 충실 재구현했을 때, 같은 입력에 temp=0으로 n=3 돌리면 (1) 방 구조(개수·이름·학습 흐름)는 재현되나, (2) 엔티티 단위 배정·visibility는 재현되나, (3) 357 전수보존이 보장되나. 팀원 최종 코드와 동일 동작은 보장하지 않음, 측정 대상은 접근 방식의 재현성.

**한 일**: repro_run3의 level-0 커뮤니티 40개 + community report 40개 + 엔티티 357개를 frozen 입력으로 고정(`frozen_input.json`), gpt-4.1-mini · temp=0 · JSON mode로 한 번 호출 = 한 런. visibility 4단계(core / supporting / search_only / background) + "핵심을 강하게 지지하지 않는 보조성은 search_only로 내려라" 게이트 + "모든 엔티티 정확히 한 방, 누락·중복 금지" 명시. n=3, 결정성 평가는 LLM 없이 자카드 greedy 매칭 + 앵커 stability로.

**결과**
| 페어 | 평균 매칭 자카드 | 최소 자카드 | 미매칭 방 | 방 이동 엔티티 | visibility 이동 |
| --- | ---: | ---: | ---: | ---: | ---: |
| run1-run2 | 0.7902 | 0.5000 | 0 | 25 | 40 |
| run1-run3 | 0.5291 | 0.1558 | 0 | 90 | 66 |
| run2-run3 | 0.5148 | 0.1579 | 0 | 100 | 42 |
| 평균 | **0.6114** | min=**0.1558** | 0 | 71.7 | 49.3 |

- **안정**: 방 수 7/7/7 (가이드 6 대비 +1), 미매칭 방 0(런 간 방 매핑 항상 7→7), 매크로 학습 흐름 척추(고려 말 → 조선 건국 → 임진왜란 → 조선 중기 → 조선 후기 실학·사회변화 → 후기 사상) 3런 모두 등장, should_show 앵커 14/14가 3런 모두 non-background로 노출, 이성계 3런 모두 "조선 건국" 방·`core` visibility.
- **흔들림**: 매칭 자카드 평균 0.61(최소 0.16), 페어당 평균 ~72개(~21%) 엔티티가 방 이동, ~49개의 visibility 변경. run1-run3·run2-run3은 마지막 "사회/사상" 방 한 곳이 자카드 0.16 부근(run3에서 size 60으로 부풀음).
- **커버리지 가변**: 할당된 엔티티가 런마다 320/337/354 (357 중). 누락 37/20/3은 주로 주변부 엔티티에 몰리고 핵심 앵커는 안 빠짐. 환각·invalid는 3런 모두 0.

**그래서**: LLM-only 설계는 **구조(방 수·이름·학습 흐름 척추)엔 믿을 만하지만 엔티티 단위 배정·노출은 temp=0에도 평균 ~21% 출렁여 못 믿음** — 온도로 못 고친다. 또 357 전수보존이 구조적으로 보장되지 않음(exp10 `check_invariants`의 keep ∪ demoted == 357과 대비). 결론: 방-만들기는 구조 재현은 LLM에 맡길 수 있어도 엔티티 배정·노출은 결정적 단계로 끊어야 한다. 자세한 표·런별 방 이름은 `archive/exp14_overlap200_stability/report.md`.

## exp15: 목차 챕터 단위 결정적 occurrence (진단)

**가설**: exp8에서 357 엔티티가 평균 5.12 섹션에 흩어진 건 1200 토큰 청크가 섹션보다 커서다. 한 단계 거친 챕터 단위로 묶으면 같은 occurrence 매핑으로도 엔티티가 한 dominant 챕터로 모인다. **방법**: exp8과 같은 텍스트 occurrence 경로(엔티티 `text_unit_ids` × text_unit 의 char span ↔ 섹션 overlap)를 그대로 쓰고, 챕터 = 섹션의 결정적 rollup. LLM·임베딩 0회. 챕터 파티션은 문서 헤딩 계층에서 결정적으로 도출한 두 granularity (A=V.1/V.2/V.3/VI.1 4개, B=V.1만 문서 묶음 헤딩 "조선의 통치 제도"·"15세기 민족 문화의 발달" 경계로 3분할한 ~6개). dominant_chapter = argmax 카운트, 동점은 학습흐름 앞선 챕터로 깸. **판정 (B 기준)**: clean_landing_rate(dominance_ratio>=0.5) 0.9944 (357/357 거의 전수, 임계 0.80), mean n_chapters_touched 1.6078 (임계 2.0, exp8 섹션 평균 5.12에서 ~3배 붕괴), 이성계 B1_V1_건국 ratio 1.0 착지, dominance_ratio_B<0.5 인 앵커 0개 → **GO**. 자세한 표·앵커별 dominant·붕괴 비교는 `archive/exp15_toc_chapters/REPORT.md`.

## exp16: 방-만들기 head-to-head (TOC vs 그래프 ward)

**질문**: 같은 코퍼스(repro_run3, 357 엔티티)에서 결정적 두 방식(TOC = exp15 B 파티션 재사용, 그래프 = exp10 ward) 으로 6개 방씩 뽑아 같은 형식으로 떨구면, "같이 있어야 할" 앵커 그룹이 어느 쪽에서 한 방에 모이고 어느 쪽에서 갈리나. 사람 블라인드 비교용 데이터까지 이번에 같이 만든다. LLM 호출 0. **한 일**: 357 전수배정으로 TOC 6방(exp15 `dominant_chapter_B`)과 그래프 ward K=6 (`room_gen.base_cluster`, 같은 임베딩 재사용) 산출. 그래프는 두 번 돌려 클러스터 멤버 완전 동일 확인. 앵커 동거 그룹 = 건국(이성계·정도전), 전쟁(이순신·권율·곽재우·김시민·임진왜란·거북선), 15세기 과학(측우기·자격루·앙부일구·혼천의·인지의). **결과**: 방 크기 TOC [94, 89, 83, 34, 34, 23] / 그래프 [95, 93, 67, 50, 34, 18]. 둘 다 357 전수, should_show 14/14·should_demote 8/8 모두 배정됨. 앵커 동거 3그룹 모두 TOC=한 방, 그래프=두 방으로 갈림 (그래프에서 정도전이 건국 그룹과 떨어지고, 곽재우가 다른 의병들과 떨어지고, 인지의가 다른 과학기기 4종과 떨어짐). 둘 다 결정적 (TOC 재사용, ward 두 번 돌려 동일). **그래서**: 방-만들기에서 "그룹이 한 방에 모이나" 라는 단순 척도로는 TOC가 그래프 raw ward를 이긴다 (이번 앵커 표본 한정). 학습 흐름·방 응집도 같은 사람 블라인드 평가용 데이터(`blind_compare.json` + `blind_key.json`)는 같이 떨궜고, 뷰어·판정은 별도 단계로 남긴다. 자세한 표·앵커별 방 배정·블라인드 운영 절차는 `archive/exp16_room_compare/REPORT.md`.

## 확정 파이프라인 러너 참조

위 결정들(K=10, n=3, embedding merge, repro_run3)을 한 줄로 잇는 confirmed-pipeline 러너는 `archive/pipeline/`에 있다. 단계별 wall·LLM 호출·토큰·다수결 효과·per-room jaccard 등 실측치는 `archive/pipeline/report.md`(자동 생성)에 있어 여기서 중복 기재하지 않는다.

## 지금까지의 결정

방은 GraphRAG 커뮤니티 병합이 아니라 엔티티 임베딩 직접 클러스터로 만든다(exp6). 방 이름과 핵심 개념 keep/demote는 그 위에 LLM 한 겹 얹어서 처리(exp7). 외울 핵심을 1차로 가르는 가벼운 안전망은 type 기준(exp5), 최종 판단은 LLM 선별기에 위임. 인덱싱은 community report 워크플로를 빼서 비용·시간을 5배 이상 줄이고(exp1~4 분석), 작업 베이스는 매번 새로 추출하지 않고 repro_run3 스냅샷에 고정(±10 자연 편차 회피). 자료 청킹은 의미 단위와 페이지 단위 중 pagesplit이 묶음 균형과 임진왜란 응집에서 약간 유리(exp9). 단, 입력 자료 품질이 청킹 방식보다 더 큰 레버일 가능성은 잊지 않는다. (exp9 데이터만으로는 청킹 변수만 격리되어 있고 baseline은 다른 자료라 자료 품질 변수가 분리되지 않으므로, 이건 confound 있는 추정이지 확정 아님.)

**방향 갱신 (exp14 이후)**: 방-만들기 = **재현되는 구조 + 결정적 엔티티 배정 + 결정적/잠금 노출**의 3층 분리로 본다. 구조 소스 후보는 (a) overlap200 척추(exp14에서 3런 모두 같은 학습 흐름 재현됨)와 (b) 자료 TOC(exp8 feasibility 확인했으나 청크 단위가 섹션보다 커서 추가 작업 필요) 둘. 결정적 엔티티 배정 후보는 (a) TOC-occurrence 매핑(exp15 예정)과 (b) exp10 임베딩 clustering(357/357 전수보존 가드 있음). LLM은 구조 라벨링 + 노출(visibility) 1차 판단에만 쓰고, "어느 방에 들어가나"는 결정적 단계로 끊는다(exp14에서 LLM-only 배정이 temp=0에도 ~21% 출렁이고 357 전수보존이 보장 안 됨을 확인). 다음 갈래: **exp15(TOC feasibility)** 진행 후 같은 코퍼스에서 구조 소스 × 결정적 배정을 head-to-head(학습 흐름 응집 · should_show 앵커 eval · 재현성 · 커버리지)로 비교해 방-만들기 파이프라인을 확정.

## palace: 정본 TOC arm 파이프라인 (2026-06-10)

exp16에서 TOC vs GRAPH 헤드투헤드, exp17에서 end-to-end TOC arm + repro_run3 K=6 데모까지 통과해 방-만들기 파이프라인을 TOC arm 단일로 확정. exp 디렉토리에 흩어진 코드를 한 패키지로 모은 게 `palace/` (루트). GRAPH arm(`archive/pipeline/`의 K=10 embedding canonical, exp10의 base_cluster→split_oversized→merge_to_k)은 정본 자리에서 빠지고 exp 디렉토리에 grandfather로 동결.

레이아웃: `palace/{run.py, toc_gen.py, build_rooms.py, room_gen.py, node_metrics.py, export_palace.py, configs/, tests/}`. 두 phase 진입(`--phase toc`로 LLM TOC 검토용 멈춤, `--phase rooms`로 끝까지). 도메인 설정은 `palace/configs/<run_id>.json` 한 장(run_id, corpus, snapshot, K, node_budget, model, domain, cache 경로). Stage A 캐시 + Stage B 해시 캐시(`cache/palace/<run_id>/`)는 입력 내용 해시 키라 경로 무관 byte-identical 재현.

검증: repro_run3 한국사 K=6 골든(`palace/tests/golden/` = 기존 `archive/rooms/repro_run3_K6_toc.{json, palace.json, toc_llm.json}` 복사본). 캐시 hit 재현은 골든과 byte-identical 일치(toc_llm + rooms + palace 전 필드, ts/generated_at 제외). 캐시 miss 라이브 재현은 4대 천문기상기(측우기·자격루·앙부일구·혼천의) 골든과 같은 방(0, demoted) 보존, room_id·sections·대부분의 방 크기 안정, kept_total 101→103(+2, room 4 +2), 6방 모두 경계 churn 평균 jaccard 0.72(noise floor 범위 내).

### exp → palace 1:1 매핑

| 출처 | 출처 심볼 | palace 파일 | 비고 |
| --- | --- | --- | --- |
| `archive/exp17_generalization/toc_gen.py` | `SYS_PROMPT`, `build_user_prompt`, `resolve_offsets`, `generate_toc` | `palace/toc_gen.py` | 모듈 상수 `CORPUS/MODEL/OUT` 제거, `corpus_rel` 인자 추가, `main()` 제거 |
| `archive/exp17_generalization/build.py` | `char_overlap`, `build_toc_rooms`, `attach_positions`, `apply_keep_demote`, `convert_toc_to_common_schema`, `absorb_empty_rooms` | `palace/build_rooms.py` | 모듈 상수 `K/DOMAIN/MODEL/NODE_BUDGET/N_RUNS/RUBRIC_CACHE/SET1_METHOD` 전부 인자로 외화. `build_graph_rooms`, `build_blind`, `compute_metrics`, `render_markdown`, `main()`은 복사 안 함 |
| `archive/exp10_room_gen/room_gen.py` | `load_snapshot`, `make_azure_client`, `call_json`, `derive_rubric`, `_stage_b_prompt`, `_stage_b_cache_key`, `_run_stage_b_once`, `_resolve_keep_membership`, `assign_rooms`, `check_invariants`, `HARD_CAP_K` | `palace/room_gen.py` | GRAPH arm(`base_cluster`, `_stack_normalized`, `split_oversized`, `_split_one`, `merge_to_k`, `_cluster_centroid`, `_merge_embedding`, `representatives`, `_merge_llm`, `generate_rooms`, `_summarize`)은 복사 안 함 |
| `archive/exp10_room_gen/export_palace.py` | 전체 (`normalize_title`, `caption_of`, `load_rooms`, `build_ent_lookup`, `compute_position`, `assign_palace_ids`, `build_entity_record`, `collect_relationships`, `export`, `validate`, `main`) | `palace/export_palace.py` | CWD 상대 `ROOMS=Path('archive/rooms')` 제거, `sys.path.insert` 제거, `export()`에 `rooms_dir` 인자 추가 |
| `archive/node_order_probe/node_metrics.py` | `build_text_unit_positions`, `_surface_variants`, `_count_in_chunk`, `_first_in_text`, `compute_entity_metrics` | `palace/node_metrics.py` | 모듈 상수 `SNAPSHOT/TXT_PATH` 제거, probe 전용 `load_text`, `load_snapshot_frames`, `tie_cluster_sizes`는 복사 안 함 |
| `archive/exp10_room_gen/run_repro_run3_toc.py` | `stop_if_missing`, `phase_toc`, `phase_rooms`의 와이어링 구조 | `palace/run.py` | 한국사 하드코딩(`RUN_ID/CORPUS/SNAPSHOT/DOMAIN/K/NODE_BUDGET/MODEL/RUBRIC_CACHE/STAGE_B_CACHE`)은 모두 config JSON으로 외화 |

### 폴더 grandfather 동결 목록

다음 폴더에 `ARCHIVED.md`로 동결 표시. 물리 이동·삭제 없음, git 이력·기존 보고서 상대 경로 보존.

| 폴더 | 동결 사유 |
| --- | --- |
| `archive/exp05_stage2_merge` | type 기준 keep/demote 1차 안전망, LLM rubric으로 대체됨 |
| `archive/exp06_room_probe` | 임베딩 ward 클러스터 원형, GRAPH arm 참고용 |
| `archive/exp07_keep_demote` | Stage A/B 방법론 원형, exp10에서 모듈화됨 |
| `archive/exp08_toc_feasibility` | TOC 섹션 매핑 진단, exp15→exp17→palace로 이어짐 |
| `archive/exp09_rechunk` | semantic/pagesplit 비교, palace 미사용 |
| `archive/exp10_room_gen` | end-to-end 모듈화, palace로 Stage A/B + export_palace 이식 |
| `archive/exp11_k_sweep` | GRAPH arm K 결정 진단, palace 미사용 |
| `archive/exp12_n3_stability` | Stage B n=3 안정성, `n_runs` 인자로 palace에 흡수 |
| `archive/exp13_generic_filter` | degree 사전 컷 미채택 |
| `archive/exp14_overlap200_stability` | LLM-only 배정 미채택 |
| `archive/exp15_toc_chapters` | char-overlap occurrence 진단, exp17로 이어짐 |
| `archive/exp16_room_compare` | TOC vs GRAPH 비교, palace는 TOC 단일 |
| `archive/exp17_generalization` | TOC arm 구현부, palace로 `toc_gen.py` + build TOC 함수 이식 |
| `archive/pipeline` | GRAPH arm canonical, 구 정본, GRAPH 참고용 |
| `archive/node_order_probe` | 위치 metric, palace.node_metrics로 이식 |
