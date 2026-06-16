---
type: synthesis
id: 03_repro_step3_summary
date: 2026-06-02
---

# Step 3, 종합: max_cluster_size 효과는 자연 편차에 묻힌다

## 한눈에

| 출처 | 통제 | level 0 결과 | 해석 |
|---|---|---|---|
| Step 1 (스냅샷) | **추출 고정 + max만 변경** | max=10/15/20 모두 **30, 30, 30** | max의 **순수 효과 = 0** |
| Step 2 (재현성) | **max=15 동일 + cache 새로 N=3** | 30, 32, 40 (range **10**, std **5.3**) | **자연 편차 ±10** |

**결론: max_cluster_size는 level 0 방 개수에 영향을 주지 않는다.** 같은 추출 위에서 0의 효과, 다른 추출 사이에서는 ±10이 알아서 흔들림. 즉 max를 바꿔서 level 0이 줄거나 늘었다고 봐도 그건 자연 편차다.

## 전 회차 한 줄 요약

| 회차 | 변경 / 통제 | Entities | Relationships | Level 0 | 시간(s) | 비용 |
|---|---|---|---|---|---|---|
| baseline | max=10, cache 새로 | 385 | 392 | 31 | 964 | $1.02 |
| 실험2 (run1) | max=15, cache 새로 | 408 | 453 | 30 | 387 | $0.92 |
| snap_max10 | max=10, cache 유지 | **408** | **453** | **30** | 102 | +$0.15 |
| snap_max20 | max=20, cache 유지 | **408** | **453** | **30** | 68 | +$0.05 |
| repro2 | max=15, cache 새로 | 390 | 380 | 32 | 320 | $0.88 |
| repro3 | max=15, cache 새로 | 357 | 379 | 40 | 388 | $0.93 |

(굵게 = 추출이 cache hit으로 고정된 회차 → entities/relationships 동일)

## Why: use_lcc=false가 level 0의 결정자

- `use_lcc=false`이면 leiden은 **비연결 컴포넌트(섬)마다 따로** 클러스터링.
- 섬 자체가 level 0 root community가 됨 → **level 0 개수 = 섬 개수** (대략).
- `max_cluster_size`는 한 섬 안에서 너무 큰 클러스터가 생기면 더 쪼개라는 옵션 → **level 1, 2의 세분 깊이**만 조절.
- 섬 개수는 그래프 자체의 구조 속성 → entity 추출이 달라질 때(LLM 비결정성)만 바뀜 → **자연 편차로 흔들리는 정체가 바로 이것**.

→ Level 0을 ≤10으로 줄이려면 **`use_lcc=true`** (실험 4)만이 유효한 손잡이. 비연결 섬을 버리고 가장 큰 연결 컴포넌트(LCC)만 사용 → 그 안에서 leiden이 더 큰 군집으로 묶음 → level 0이 자연스럽게 적어짐.

## 비용/시간 사이드 이득 (스냅샷의 가치)

- baseline 인덱싱 ~16분, $1.02
- 스냅샷 후 묶기 재실행: **~1~2분, $0.05~0.15**
- 회랑 UX 시사: 시연용 슬라이더에서 1~2분 안에 재묶기 가능. baseline을 매번 다시 안 해도 됨.

## 다음 단계 권고

1. **실험 4 진행 (use_lcc=true)**: max_cluster_size는 baseline 값(10) 유지. cache는 비우거나(자연 편차 ±10 위에서) 유지(추출 고정 비교) 중 선택.
   - 권장: cache 유지. 같은 추출(408 entities) 위에서 use_lcc=true가 level 0을 얼마나 줄이는지 통제 비교 가능. 사라진 엔티티도 명확히 식별 가능 (snap_max10의 entities와 use_lcc=true 후의 entities 비교).
2. **재현성 보강 (선택)**: 만약 실험 4 결과가 흥미로우면, 그것도 N=2~3으로 자연 편차 확인. 비용 추가 $1.5~2.

## 파일 인덱스

- 실험 결과: `results/baseline_*.md`, `results/실험2_*.md`, `results/snap_max10_*.md`, `results/snap_max20_*.md`, `results/Step1_*.md`, `results/Step2_*.md`, 본 파일
- 백업: `archive/snapshots/{exp2_max15, snap_max10, snap_max20, repro_run2}/`, `results/snapshots/repro_run3/`
- 로그: `logs/{exp2, snap_max10, snap_max20, repro_run2, repro_run3}_run.log` + `_results.json`
