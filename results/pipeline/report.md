# Pipeline cost report: pipeline_K10_n3_embedding

- model: `gpt-4.1-mini` | n_runs: 3 | parallel_stage_b: False
- generated_at: 2026-06-08T02:47:03.113501+00:00
- pricing source: set when known; null leaves $ as 'pending'  (cost shown as "pending" because input_per_1m/output_per_1m unset)

## Per-stage

| stage | wall s | call_sum s | LLM calls | prompt tok | completion tok | cost $ |
|---|---:|---:|---:|---:|---:|---:|
| snapshot_load | 1.244 | 0.0 | 0 | 0 | 0 | 0.0 |
| clustering | 0.169 | 0.0 | 0 | 0 | 0 | 0.0 |
| stage_a | 0.003 | 0.0 | 0 | 0 | 0 | 0.0 |
| stage_b | 77.812 | 77.791 | 30 | 101799 | 4776 | pending |
| aggregate | 0.0 | 0.0 | 0 | 0 | 0 | 0.0 |
| export | 0.116 | 0.0 | 0 | 0 | 0 | 0.0 |

stage_b note: 3 passes serial; wall = sum of call durations (77.791 s) since parallel=False. Per-pass wall 25.937 s.

## Totals

- wall: **79.344 s**
- LLM calls: **30** (prompt 101799 + completion 4776 tokens)
- cost: **$pending**

## Pipeline settings (locked)

- snapshot: `results/snapshots/repro_run3`
- K=10, k_base=12, max_cluster_size=55, merge=embedding, n_runs=3, node_budget=20
- domain: 한국사

## Rooms summary

| id | name | kept | demoted | coherence |
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

total entities 357/357 (전수보존 OK)

## Concurrency

- mode: **serial**
- rooms: sequential for-loop in room_gen.assign_rooms
- passes_per_room: sequential list comprehension over n_runs
- evidence: stage_b wall_seconds ≈ call_seconds; no thread/async pool used

## Stage B n-pass agreement

- spec: keep iff votes > n/2 (= >= ceil((n+1)/2)); for n=3 means >= 2/3.
- overall mean pair-jaccard: **0.906**
- overall min pair-jaccard: **0.6154**
- split entities (not unanimous across passes): **26/357** (0.0728)

## Majority vote effect

- entities the 2/3 majority changed vs unanimous-only: **26**
- majority decided non-trivially (entity classifications were not unanimous).
- implementation verified: actual kept set matches majority spec (>= 2/3) within node_budget cap.

### Per-room

| room | size | keep sizes per pass | mean jacc | min jacc | split | maj changed | name unanim |
|---|---:|---|---:|---:|---:|---:|---|
| 0 | 82 | [20, 20, 20] | 0.7172 | 0.6667 | 10 | 10 | yes |
| 1 | 34 | [20, 20, 20] | 1.0 | 1.0 | 0 | 0 | yes |
| 2 | 93 | [20, 20, 20] | 0.8788 | 0.8182 | 4 | 4 | yes |
| 3 | 13 | [7, 7, 7] | 1.0 | 1.0 | 0 | 0 | yes |
| 4 | 39 | [8, 13, 13] | 0.7436 | 0.6154 | 5 | 5 | yes |
| 5 | 23 | [18, 18, 18] | 1.0 | 1.0 | 0 | 0 | yes |
| 6 | 24 | [15, 15, 13] | 0.7647 | 0.6471 | 6 | 6 | yes |
| 7 | 20 | [15, 15, 14] | 0.9556 | 0.9333 | 1 | 1 | yes |
| 8 | 11 | [6, 6, 6] | 1.0 | 1.0 | 0 | 0 | no |
| 9 | 18 | [11, 11, 11] | 1.0 | 1.0 | 0 | 0 | yes |
