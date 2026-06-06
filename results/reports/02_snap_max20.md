---
type: experiment
id: 02_snap_max20
date: 2026-06-02
input: 국사교과서_조선_본문_정제.txt (20,921자)
model: gpt-4.1-mini / text-embedding-3-small
variable: max_cluster_size 10 → 20, cache 유지 (실험 2 캐시 재사용)
params:
  entity_types: 7
  max_gleanings: 2
  use_lcc: false
  max_cluster_size: 20
entities: 408
relationships: 453
communities_total: 59
level0: 30
level1: 29
level2: 0
time_total_s: 67.9
cost_usd: +$0.05
conclusion: max=10/15/20 모두 같은 추출 위에서 level 0=30 동일. max_cluster_size는 level 0에 무력. level 1·2만 묶음이 커지며 줄어듦(max=20은 level 2 0개). use_lcc=true만이 유효한 손잡이.
next: use_lcc=true 시도(실험 4).
snapshot: null
---

## GraphRAG 실험 결과: Step 1-B 스냅샷 (max=20, 추출 캐시 hit)

**실험 정보**: 2026-06-02 / 국사교과서_조선_본문_정제.txt (20,921자) / gpt-4.1-mini / text-embedding-3-small / entity_types=7, max_gleanings=2, use_lcc=false, **max_cluster_size=20** / **cache 유지 (실험 2의 캐시 재사용)**

### (1) Database 행 요약
```
회차=snap_max20 | 2026-06-02 | 자료=교과서2만 | 모델=gpt-4.1-mini | 변경=캐시유지+max 10→20 (추출고정) | Entities=408 | Relationships=453 | Level0방수=30 | 추출시간=21.5s | 추정비용=+$0.05
```

### (2) 상세

**추출 결과** (실험 2 / snap_max10 와 완전 동일, cache hit 검증)
| 항목 | 수 | (실험2 max=15) | (snap_max10) |
|---|---|---|---|
| Entities | 408 | 408 ✅ | 408 ✅ |
| Relationships | 453 | 453 ✅ | 453 ✅ |
| Communities (전체) | 59 | 80 | 91 |

**Level별 Community(방) 개수**
| Level | 개수 | (실험2 max=15) | (snap_max10) |
|---|---|---|---|
| 0 (건물 후보) | **30** | **30** | **30** |
| 1 | 29 | 48 | 56 |
| 2 | 0 | 2 | 5 |

**단계별 소요 시간**
| 단계 | 시간(초) | (snap_max10) |
|---|---|---|
| 추출 (extract_graph) | 21.5 | 24.1 |
| 묶기 (create_communities) | 0.3 | 0.7 |
| 리포트 (create_community_reports) | 32.0 | 55.4 |
| 임베딩 (generate_text_embeddings) | 11.8 | 17.9 |
| 전체 | 67.9 | 102.2 |

**비용 (이번 회차 추가분)**
- 누적 LLM input $0.5948 / output $0.5265 / 임베딩 $0.0071 = $1.1284
- snap_max10 누적 $1.0751 → **이번 회차 추가 ≈ $0.053** (community 수 59개로 더 적어 community_reports 비용 더 작음)

**Level 0 방 이름** (30개), snap_max10과 완전 동일 (community 번호·크기·제목 모두 일치)

**관찰**
- **Level 0 = 30, 또 동일**: max=10/15/20 모두 같은 추출 위에서 level 0 = 30. **max_cluster_size는 level 0에 전혀 영향 안 줌.**
- **Level 1, 2만 변함**: max 커질수록 묶음이 커져서 1·2 레벨이 줄어듦. max=20은 level 2가 아예 없음 (모든 클러스터가 max 안에 맞음).
- **이유**: `use_lcc=false`로 비연결 컴포넌트(섬)마다 leiden을 따로 돌리는데, 섬 개수 = level 0 개수가 그래프 구조의 속성이라 클러스터링 파라미터가 못 바꿈. leiden의 max_cluster_size는 한 섬 안의 세분 깊이만 조절.
- **결론적 시사**: **level 0을 ≤10으로 줄이는 데 max_cluster_size는 무력**. `use_lcc=true`(섬 자체를 버려서 1개의 연결 그래프만 사용)만이 유효한 손잡이.
