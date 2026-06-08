# node_order_probe REPORT

> Deterministic position + weight metrics for the 357 entities in `results/snapshots/repro_run3`. LLM calls: 0. Two runs return identical numbers.

## 무엇을 계산했나

- text_unit char span: 청크의 첫 100자(실패 시 50자)를 원문에서 string-find. exp08·exp15와 동일 경로.
- pos_first: 엔티티가 들어있는 text_unit들의 char_start 최소값.
- pos_mode: text_unit 내부에서 엔티티 표면형 등장 수가 최대인 청크의 char_start. 동률은 더 이른 청크.
- pos_centroid: 표면형 등장 수 가중 평균 char_start. 표면 매칭 0이면 청크 char_start의 단순 평균으로 폴백.
- pos_first_fine: 엔티티 표면형을 원문 전체에서 직접 찾은 첫 char 오프셋. 실패 시 pos_first로 폴백.
- fine_matched: 위 폴백 발생 여부 (1=실제 매칭).
- weight_count: entity.text_unit_ids 길이 (이 엔티티가 들어있는 청크 수).
- graph_degree: entities.parquet의 degree 컬럼.

대상 엔티티: 357개 (텍스트 매핑 실패: 0개).

## pos_first_fine 매칭률

- 매칭 성공: 323/357 (90.5%)
- 매칭 실패(폴백): 34개

pos_first vs pos_first_fine 절대차(매칭 성공 한정, N=323): mean=1426.07, median=1043, |diff|>500인 케이스 259건.

## 동률 덩어리 (한 청크에 몰리는 엔티티)

- pos_first 기준: 12개 distinct 값, 최대 한 덩어리 크기 60.

| 덩어리 크기 | 덩어리 수 (pos_first) |
|---|---|
| 10 | 1 |
| 15 | 1 |
| 17 | 2 |
| 22 | 1 |
| 25 | 1 |
| 26 | 1 |
| 34 | 1 |
| 37 | 1 |
| 46 | 1 |
| 48 | 1 |
| 60 | 1 |

- pos_first_fine 기준: 327개 distinct 값, 최대 한 덩어리 크기 10.
  (fine은 문자 단위라 청크 단위 덩어리가 풀린다.)

## weight_count 분포

| n_text_units | 엔티티 수 |
|---|---|
| 1 | 322 |
| 2 | 26 |
| 3 | 7 |
| 4 | 2 |

## graph_degree 요약

- mean=2.01, median=1, max=41.

## top-K 추렸을 때 방 무게 비율 (방 무게 = 멤버 weight_count 합)

top-K 비율 = top-K 멤버 weight_count 합 / 방 전체 weight_count 합. 1.0이면 top-K가 방 전체 weight를 담는다는 뜻 (작은 방).

### TOC arm

| room | size | K | top-K coverage |
|---|---|---|---|
| toc_1 | 34 | 10 | 0.3514 |
| toc_2 | 94 | 10 | 0.1064 |
| toc_3 | 34 | 10 | 0.2941 |
| toc_4 | 23 | 10 | 0.5185 |
| toc_5 | 89 | 10 | 0.2422 |
| toc_6 | 83 | 10 | 0.1205 |
| toc_1 | 34 | 15 | 0.4865 |
| toc_2 | 94 | 15 | 0.1596 |
| toc_3 | 34 | 15 | 0.4412 |
| toc_4 | 23 | 15 | 0.7037 |
| toc_5 | 89 | 15 | 0.3203 |
| toc_6 | 83 | 15 | 0.1807 |

### Graph arm

| room | size | K | top-K coverage |
|---|---|---|---|
| graph_1 | 95 | 10 | 0.2137 |
| graph_2 | 93 | 10 | 0.2232 |
| graph_3 | 67 | 10 | 0.1618 |
| graph_4 | 50 | 10 | 0.2157 |
| graph_5 | 34 | 10 | 0.2941 |
| graph_6 | 18 | 10 | 0.619 |
| graph_1 | 95 | 15 | 0.2991 |
| graph_2 | 93 | 15 | 0.3036 |
| graph_3 | 67 | 15 | 0.2353 |
| graph_4 | 50 | 15 | 0.3137 |
| graph_5 | 34 | 15 | 0.4412 |
| graph_6 | 18 | 15 | 0.8571 |

## top-K로 추렸을 때 방이 깨지나

top-K는 partition을 깨지 않는다 (멤버를 제거할 뿐, 방 경계는 그대로). 의미 있는 질문은 "top-K가 방을 어느 정도 대표하나". 위 coverage 표를 보면:

- size > 15 인데 top-10 coverage < 0.5 인 방:
  - TOC toc_1: size=34, top-10 coverage=0.3514
  - TOC toc_2: size=94, top-10 coverage=0.1064
  - TOC toc_3: size=34, top-10 coverage=0.2941
  - TOC toc_5: size=89, top-10 coverage=0.2422
  - TOC toc_6: size=83, top-10 coverage=0.1205
  - Graph graph_1: size=95, top-10 coverage=0.2137
  - Graph graph_2: size=93, top-10 coverage=0.2232
  - Graph graph_3: size=67, top-10 coverage=0.1618
  - Graph graph_4: size=50, top-10 coverage=0.2157
  - Graph graph_5: size=34, top-10 coverage=0.2941

weight_count 분포가 1로 강하게 쏠려 있어(아래 분포 참고) top-K가 "무게가 같은 평평한 꼬리" 위에서 잘리기 쉽다. coverage 값을 "top-K로 방을 요약하면 어느 정도가 남나"의 거친 신호로만 읽을 것.

## 한계 / 결정점

- 청크 단위가 1200 토큰이라 pos_first가 청크 시작 오프셋으로 강하게 몰린다. pos_first_fine은 그 덩어리를 풀어 주는 용도.
- entity.text_unit_ids 길이가 1인 엔티티가 322개. weight_count 단독으로는 결정력이 약하고 graph_degree와 합쳐 봐야 한다.
- 표면 검색은 정규화 이름·표기 변형(별칭, 한자 등)에 약하다. 매칭률은 위 "pos_first_fine 매칭률"이 전부.

inputs:
- corpus: `input/국사교과서_조선_본문_정제.txt`
- snapshot: `results/snapshots/repro_run3/`
- TOC rooms: `results/exp16_room_compare/toc_rooms.json`
- Graph rooms: `results/exp16_room_compare/graph_rooms.json`
