# 파이프라인 비용 리포트: pipeline_K10_n3_embedding

- model: `gpt-4.1-mini` | n_runs: 3 | parallel_stage_b: False
- generated_at: 2026-06-08T02:47:03.113501+00:00
- 가격 출처: set when known; null leaves $ as 'pending' (input_per_1m/output_per_1m 미설정이라 cost는 "pending" 표기)

## 단계별

| stage | wall s | call_sum s | LLM calls | prompt tok | completion tok | cost $ |
|---|---:|---:|---:|---:|---:|---:|
| snapshot_load | 1.244 | 0.0 | 0 | 0 | 0 | 0.0 |
| clustering | 0.169 | 0.0 | 0 | 0 | 0 | 0.0 |
| stage_a | 0.003 | 0.0 | 0 | 0 | 0 | 0.0 |
| stage_b | 77.812 | 77.791 | 30 | 101799 | 4776 | pending |
| aggregate | 0.0 | 0.0 | 0 | 0 | 0 | 0.0 |
| export | 0.116 | 0.0 | 0 | 0 | 0 | 0.0 |

stage_b 메모: 3 pass serial 실행; parallel=False이므로 wall = call duration 합 (77.791 s). pass별 wall 25.937 s.

## 합계

- wall: **79.344 s**
- LLM calls: **30** (prompt 101799 + completion 4776 tok)
- cost: **$pending**

## 파이프라인 설정 (고정)

- snapshot: `results/snapshots/repro_run3`
- K=10, k_base=12, max_cluster_size=55, merge=embedding, n_runs=3, node_budget=20
- domain: 한국사

## 방 요약

| id | 이름 | 유지 | 강등 | 정합성 |
|---|---|---:|---:|---|
| 0 | 조선 정치·학문 세력 | 20 | 62 | coherent |
| 1 | 조선 법전과 문헌·인물 | 20 | 14 | coherent |
| 2 | 임진왜란과 조선 군사 | 20 | 73 | coherent |
| 3 | 조선 의병과 지도자 | 7 | 6 | coherent |
| 4 | 조선 주요 인물·제도·문서 | 13 | 26 | coherent |
| 5 | 조선 제도와 실학 인물 | 18 | 5 | coherent |
| 6 | 조선 행정과 제도 | 15 | 9 | coherent |
| 7 | 조선 북방 군사와 교통 제도 | 15 | 5 | coherent |
| 8 | 조선 후기 수원과 지도 | 6 | 5 | coherent |
| 9 | 조선-일본 교역과 외교 | 11 | 7 | coherent |

총 엔티티 357/357 (전수보존 OK)

## 동시성

- mode: **serial**
- rooms: sequential for-loop in room_gen.assign_rooms
- passes_per_room: sequential list comprehension over n_runs
- evidence: stage_b wall_seconds ≈ call_seconds; no thread/async pool used

## Stage B n-pass 일치도

- spec: keep iff votes > n/2 (= >= ceil((n+1)/2)); for n=3 means >= 2/3.
- 전체 평균 pair-jaccard: **0.906**
- 전체 최소 pair-jaccard: **0.6154**
- split 엔티티 (pass 간 불일치): **26/357** (0.0728)

## 다수결 효과

- 다수결(2/3)이 만장일치 대비 바꾼 엔티티: **26**
- 다수결이 실제로 분류에 관여 (일부 엔티티가 pass 간 불일치).
- 구현 확인: 실제 keep set이 다수결 spec(>= 2/3)과 일치 (node_budget 한도 내).

### 방별

| room | size | pass별 keep 크기 | mean jacc | min jacc | split | maj 변경 | 이름 일치 |
|---|---:|---|---:|---:|---:|---:|---|
| 0 | 82 | [20, 20, 20] | 0.7172 | 0.6667 | 10 | 10 | 예 |
| 1 | 34 | [20, 20, 20] | 1.0 | 1.0 | 0 | 0 | 예 |
| 2 | 93 | [20, 20, 20] | 0.8788 | 0.8182 | 4 | 4 | 예 |
| 3 | 13 | [7, 7, 7] | 1.0 | 1.0 | 0 | 0 | 예 |
| 4 | 39 | [8, 13, 13] | 0.7436 | 0.6154 | 5 | 5 | 예 |
| 5 | 23 | [18, 18, 18] | 1.0 | 1.0 | 0 | 0 | 예 |
| 6 | 24 | [15, 15, 13] | 0.7647 | 0.6471 | 6 | 6 | 예 |
| 7 | 20 | [15, 15, 14] | 0.9556 | 0.9333 | 1 | 1 | 예 |
| 8 | 11 | [6, 6, 6] | 1.0 | 1.0 | 0 | 0 | 아니오 |
| 9 | 18 | [11, 11, 11] | 1.0 | 1.0 | 0 | 0 | 예 |
