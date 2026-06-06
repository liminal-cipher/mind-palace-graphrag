---
type: synthesis
id: 03_repro_step1_snapshot
date: 2026-06-02
---

# Step 1 종합: 스냅샷으로 본 max_cluster_size의 순수 효과

**핵심 메시지 (요약)**
1. **스냅샷이 진짜로 작동한다** → 회랑 설계의 "추출 고정 + 재묶기" 즉시 가능, 시연용 UI에 직결.
2. **`use_lcc=false`일 때 `max_cluster_size`는 level 0에 무력하다** → 10/15/20 모두 level 0 = 30. 다음 실험은 `use_lcc=true`로 가야 함.
3. **묶기만 다시 돌리는 비용은 매우 작다** ($0.05~0.15, ~1~2분). 시연용 즉시 리클러스터링이 실용적.

---

## 스냅샷 작동 증거 (캐시 hit 검증)

| 회차 | max | entities | relationships | extract_graph 시간 |
|---|---|---|---|---|
| 실험2 (cache 새로) | 15 | 408 | 453 | 148.6초 |
| snap_max10 (cache 유지) | 10 | **408** ✅ | **453** ✅ | **24.1초** (6배↓) |
| snap_max20 (cache 유지) | 20 | **408** ✅ | **453** ✅ | **21.5초** (7배↓) |

- entities/relationships가 토씨 하나 안 틀리고 동일.
- extract_graph 시간이 ~6~7배 줄어듦 (LLM 호출이 cache 응답으로 즉답).
- → **graphrag의 cache 메커니즘이 "추출 결과를 그대로 재사용"하는 스냅샷으로 사용 가능**.
- 회랑 UX 시사: 사용자가 슬라이더로 `max_cluster_size`를 조정해도 1~2분 안에 새 community 구조 + 새 리포트 생성 가능. baseline 인덱싱 16분을 매번 다시 안 해도 됨.

---

## max_cluster_size 순수 효과 (같은 추출 408 entities / 453 relationships 위에서)

| max_cluster_size | Communities 전체 | Level 0 (건물) | Level 1 | Level 2 | community_reports 시간 | 이번 회차 추가 비용 |
|---|---|---|---|---|---|---|
| 10 (snap_max10) | 91 | **30** | 56 | 5 | 55.4초 | $0.153 |
| 15 (실험2)        | 80 | **30** | 48 | 2 | 171.9초* | (baseline) |
| 20 (snap_max20) | 59 | **30** | 29 | 0 | 32.0초 | $0.053 |

*실험 2는 cache 새로 시작이라 community_reports 시간이 큼. snap_max10/20은 cache 활용으로 더 짧음.

**해석**
- **Level 0 = 30 / 30 / 30, 변화 0**. `use_lcc=false`로 비연결 컴포넌트(섬)가 그대로 level 0 root가 되므로, leiden 알고리즘 파라미터로는 섬 개수를 못 줄임.
- **Level 1, 2만 단조 변화**: max 커질수록 묶음이 커져 1·2 레벨 community 수가 줄어듦. max=20에서는 level 2가 아예 0 (모든 클러스터가 max 안에 들어감).
- **Level 0 방 30개는 max 무관하게 똑같음**. 제목·크기·번호 모두 완전 일치. 즉 max는 "위쪽 묶음"이 아니라 "아래쪽 세분"만 건드림.

---

## 의미와 다음 단계

**회랑 프로젝트 관점**
- 추출(LLM, 비싸고 비결정적, ~3분 비용 $0.5~0.6 차지) 한 번만 하면, 묶기/리포트는 캐시 기반으로 빠르게 여러 번 시도 가능.
- 시연 UI: 슬라이더 → 1분 안에 평면 재배치 가능. 사용자가 "이 정도가 좋다" 고를 수 있음.
- 단, "방 구성 자체가 바뀌어 한 평면 배치가 다른 평면에서 안 통하는 문제"는 별개 → 추후 어떤 level/방을 정착 단위로 쓸지 결정 필요.

**다음 실험 방향**
- 실험 3(max=20 cache 새로)은 사실상 정보 가치 작음 → Step 1에서 max=20 효과가 이미 통제 비교로 나옴. 자연 편차 N=3에 max=20 케이스도 끼워서 한 번만 더 돌리는 게 효율적이지만, 사용자 합의는 max=15로 N=3.
- 다음 진짜 효과 있는 실험: **`use_lcc=true`** (실험 4). 비연결 섬을 버려 level 0 = LCC 내부 클러스터로만 구성. 다만 사라진 엔티티 보고 필수.

---

## 파일
- 상세: `results/snap_max10_2026-06-02.md`, `results/snap_max20_2026-06-02.md`
- 백업: `results/snapshots/{exp2_max15, snap_max10, snap_max20}/`
- 로그: `logs/snap_max{10,20}_run.log`, `logs/snap_max{10,20}_results.json`
