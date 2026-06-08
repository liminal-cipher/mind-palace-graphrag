# Pipeline cost report: pipeline_K10_n3_embedding

- model: `gpt-4.1-mini` | n_runs: 3 | parallel_stage_b: False
- generated_at: 2026-06-08T02:19:04.821800+00:00
- pricing source: set when known; null leaves $ as 'pending'  (cost shown as "pending" because input_per_1m/output_per_1m unset)

## Per-stage

| stage | wall s | call_sum s | LLM calls | prompt tok | completion tok | cost $ |
|---|---:|---:|---:|---:|---:|---:|
| snapshot_load | 1.459 | 0.0 | 0 | 0 | 0 | 0.0 |
| clustering | 0.282 | 0.0 | 0 | 0 | 0 | 0.0 |
| stage_a | 16.666 | 16.653 | 1 | 925 | 913 | pending |
| stage_b | 66.666 | 66.636 | 30 | 101799 | 4880 | pending |
| aggregate | 0.0 | 0.0 | 0 | 0 | 0 | 0.0 |
| export | 0.08 | 0.0 | 0 | 0 | 0 | 0.0 |

stage_b note: 3 passes serial; wall = sum of call durations (66.636 s) since parallel=False. Per-pass wall 22.222 s.

## Totals

- wall: **85.153 s**
- LLM calls: **31** (prompt 102724 + completion 5793 tokens)
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
| 6 | 조선 행정과 제도 | 14 | 10 | coherent |
| 7 | 조선 북방 군사와 교통 제도 | 15 | 5 | coherent |
| 8 | 조선 후기 수원과 지도 | 6 | 5 | coherent |
| 9 | 조선-일본 교역과 외교 | 11 | 7 | coherent |

total entities 357/357 (전수보존 OK)
