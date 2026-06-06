---
type: synthesis
id: 03_repro_step2_variance
date: 2026-06-02
---

# Step 2: 재현성 측정 (max=15 동일 설정 N=3)

같은 입력·모델·설정으로 cache+output 비우고 3번 인덱싱. 회차 간 차이가 LLM 비결정성에 의한 "자연 편차".

## 결과 (max_cluster_size=15, use_lcc=false)

| 회차 | entities | relationships | communities | level 0 | level 1 | level 2 | extract 시간 | 비용 |
|---|---|---|---|---|---|---|---|---|
| run1 (실험2) | 408 | 453 | 80 | 30 | 48 | 2 | 148.6s | $0.92 |
| run2 (repro2) | 390 | 380 | 73 | 32 | 41 | 0 | 149.0s | $0.88 |
| run3 (repro3) | 357 | 379 | 73 | 40 | 31 | 2 | 197.7s | $0.93 |

## 자연 편차 통계 (N=3)

| metric | mean | std | range (max-min) |
|---|---|---|---|
| entities | 385.0 | 25.87 | 51 |
| relationships | 404.0 | 42.44 | 74 |
| communities | 75.3 | 4.04 | 7 |
| **level 0** | **34.0** | **5.29** | **10** |
| level 1 | 40.0 | 8.54 | 17 |
| level 2 | 1.3 | 1.15 | 2 |

## 한 줄 요약 (baseline 포맷)
```
회차=repro2 | 2026-06-02 | 자료=교과서2만 | 모델=gpt-4.1-mini | 변경=cache새로(재현성 run2/3) | Entities=390 | Relationships=380 | Level0방수=32 | 추출시간=149.0s | 추정비용=$0.8788
회차=repro3 | 2026-06-02 | 자료=교과서2만 | 모델=gpt-4.1-mini | 변경=cache새로(재현성 run2/3) | Entities=357 | Relationships=379 | Level0방수=40 | 추출시간=197.7s | 추정비용=$0.9331
```

## 관찰
- **엔티티 수가 크게 흔들림**: 357~408 (범위 51, std ~26). LLM이 텍스트 청크에서 어떤 단어를 entity로 뽑을지가 회차마다 다름. extract 단계의 `max_gleanings=2`로 보강 시도해도 비결정성 잔존.
- **Level 0이 ±10 흔들림**: 30, 32, 40. 같은 설정인데도 회차마다 다른 그래프 구조 → 다른 비연결 컴포넌트 개수 → 다른 level 0 수.
- **entities 적을수록 level 0이 많아짐**: run3 entities 357로 가장 적은데 level 0이 40으로 가장 많음. 추측: entity가 적게 뽑히면 연결도 적게 만들어져 더 많은 작은 섬으로 쪼개짐.
- **N=3은 표본이 작음**: 통계 신뢰도 한계. 정밀하게 보려면 N≥10 필요하지만, 비용·시간 대비 정성적 결론은 이걸로 충분 ("±10 정도 흔들린다").

## 백업
`results/snapshots/{exp2_max15, repro_run2, repro_run3}/`: 각 회차 parquet/cache/log
