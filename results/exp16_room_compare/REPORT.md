# exp16: 방-만들기 head-to-head (TOC vs 그래프 ward)

## 무엇을 했나

같은 코퍼스(repro_run3, 357 엔티티)에서 두 가지 결정적 방식으로 357 엔티티 전수를 6개 방에 배정해 같은 형식으로 떨궜다. 블라인드 평가용 데이터까지 같이 만들어 두 방식을 사람 눈으로 비교할 수 있게 했다. LLM 호출 0, 두 방식 모두 결정적, 두 번 돌려 동일.

본 단계 범위는 데이터·지표 생성까지다. 학습 흐름·응집도 같은 사람 블라인드 평가는 별도 뷰어에서 한다.

## 입력

- 스냅샷: `results/snapshots/repro_run3/` (357 엔티티, 1536-D 임베딩)
- 임베딩: `results/snapshots/repro_run3/lancedb/entity_description` (exp10이 쓴 그것 그대로 재사용, 재계산 안 함)
- TOC 배정: `results/exp15_toc_chapters/entity_chapter_assignments.csv` 의 `dominant_chapter_B` 컬럼 (B 파티션 6챕터)
- 챕터 정의: `results/exp15_toc_chapters/chapter_definition.json` `partition_B`
- 앵커: `results/exp10_room_gen/anchors_korean_history.json` (should_show 14 + should_demote 8, alias 적용)

## 두 방식

### TOC 방 (exp15 B 파티션 재사용)
exp15에서 결정한 entity → dominant_chapter_B 배정을 그대로 가져왔다. 새로 계산하지 않음. 6개 방.

### 그래프 방 (ward, K=6)
exp10 `room_gen.base_cluster(entities, K=6)` 호출. L2 정규화한 357개 임베딩에 scipy ward linkage(euclidean), fcluster maxclust로 6개로 자른다. 본 실험에서는 LLM keep/demote·라벨링·LLM-TOC 정리는 적용하지 않는다 (방 그룹 비교에 필요 없음, 범위 외). 6개 방.

두 방식 모두 방 개수 6으로 맞춰 공정 비교.

## 결과 요약 (results/exp16_room_compare/metrics.json)

### 방 크기 분포
- TOC: 34, 94, 34, 23, 89, 83 (합 357)
- 그래프: 95, 93, 67, 50, 34, 18 (합 357)

두 방식 모두 357 전수배정. 미배정 0.

### 앵커 커버리지
should_show 14개 둘 다 14/14 전부 어딘가 방에 배정됨 (357 전수배정이라 자명).

- TOC: 4개 방에 분포. toc_1=2, toc_2=1, toc_3=5, toc_5=6.
- 그래프: 5개 방에 분포. graph_1=1, graph_2=6, graph_3=1, graph_4=5, graph_5=1.

should_demote 8개도 둘 다 8/8 배정됨.
- TOC: 3개 방에 분포. toc_1=4, toc_2=3, toc_6=1.
- 그래프: 3개 방에 분포. graph_1=4, graph_2=1, graph_4=3.

### 앵커 동거 ("같이 있어야 할" 그룹)

| 그룹 | 멤버 | TOC | 그래프 |
| --- | --- | --- | --- |
| 건국 | 이성계, 정도전 | 같은 방 (toc_1) | 갈림 (이성계→graph_2, 정도전→graph_4) |
| 전쟁 | 이순신, 권율, 곽재우, 김시민, 임진왜란, 거북선 | 같은 방 (toc_5) | 갈림 (곽재우만 graph_1, 나머지 5명 graph_2) |
| 15세기 과학 | 측우기, 자격루, 앙부일구, 혼천의, 인지의 | 같은 방 (toc_3) | 갈림 (인지의만 graph_3, 나머지 4종 graph_4) |

TOC는 세 그룹 모두 한 방에 모았고, 그래프는 세 그룹 모두 갈렸다.

세 그룹에 안 들어가는 앵커:
- 훈민정음: TOC toc_2, 그래프 graph_5.

should_demote 앵커별 방:
- TOC: 조선/백성/성리학/함경도 → toc_1, 백성들/경상도/전라도 → toc_2, 붕당 정치 → toc_6.
- 그래프: 조선/백성/성리학/붕당 정치 → graph_1, 함경도 → graph_2, 백성들/경상도/전라도 → graph_4.

### 재현성
- TOC: exp15 B 배정 그대로 재사용이라 결정적 (자명).
- 그래프: ward + fcluster, 랜덤 시드 없음. 같은 입력 두 번 돌려 클러스터 멤버 완전 동일 확인 (`two_runs_identical: true`).
- 둘 다 결정적임을 명시.

## 블라인드 비교 데이터 읽는 법

- 데이터: `results/exp16_room_compare/blind_compare.json`. `sets.set1`, `sets.set2` 각각 6방, 방마다 엔티티 이름 목록. 어느 쪽이 TOC인지·챕터 이름은 이 파일에 없다.
- 키: `results/exp16_room_compare/blind_key.json`. 중립 라벨(set1_room1..6, set2_room1..6) → 실제 방식·방 ID·(TOC만) 챕터 정보. 사람 평가가 끝난 뒤 이 키로 공개.
- 운영: 평가 뷰어는 `blind_compare.json`만 로드해 두 set을 나란히 보여주고, 평가자가 응집도/학습흐름 판단을 마친 뒤 `blind_key.json`을 열어 어느 쪽이 어떤 방식이었는지 공개한다.
- set 순서는 고정해 둠 (set1 = TOC, set2 = 그래프). 그 사실은 키 파일에만.

블라인드 뷰어 UI(.html)는 이 작업 범위 밖이라 만들지 않았다.

## 본 실험에서 안 한 것
- 학습 흐름·방 응집도 정량 판정: 사람 블라인드 평가용이라 여기서 계산 안 함.
- 그래프 방에 LLM keep/demote·이름 짓기·LLM-TOC 정리: 방 그룹 비교에 불필요하고 범위 외.
- 임베딩 재계산: exp10이 쓴 lancedb 그대로 재사용.

## 한계
- 앵커 그룹 3개 + 단독 앵커 1개(훈민정음)만으로는 방 품질을 다 측정 못한다. 나머지 ~340 엔티티의 배치 차이는 사람 블라인드 평가로 가린다.
- 그래프 ward는 본 단계에서 LLM 후처리 없이 raw 클러스터다. exp10에서 보였듯 라벨링·keep/demote를 LLM에 얹으면 방 의미가 정리되는데, 본 비교에서는 데이터 정렬(어느 엔티티가 어느 방)만 본다.
- TOC 방 6개는 B 파티션의 한 분할 선택이라 (V.1을 3분할), 다른 granularity(A 파티션 4챕터 등)는 비교 대상 아님.
- should_show 앵커가 14개라 분포 표본이 작다. 다른 도메인에서 같은 head-to-head를 돌리면 결과 모양이 달라질 수 있음.

## 산출물

- `results/exp16_room_compare/build.py`: 빌드 스크립트 (no-LLM, 결정적).
- `results/exp16_room_compare/toc_rooms.json`: TOC 방 6개, entity→방 배정.
- `results/exp16_room_compare/graph_rooms.json`: 그래프 ward 방 6개, entity→방 배정.
- `results/exp16_room_compare/metrics.json`: 커버리지·동거·재현성 머신리더블.
- `results/exp16_room_compare/blind_compare.json`: 중립 라벨 블라인드 데이터.
- `results/exp16_room_compare/blind_key.json`: 중립 라벨 → 실제 방식 매핑.
