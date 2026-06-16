# exp12 n=3 안정성 (Stage B 흔들림)

베이스: `repro_run3` (357 엔티티). 결정적 클러스터링은 K=10 / K=5 한 번씩 (exp11 결과와 동일), Stage B (LLM keep/demote)만 클러스터당 3회 반복. 모델: `gpt-4.1-mini`, temp=0. rubric은 캐시 재사용 (`cache/exp10_room_gen/rubric_repro_run3.json`)이라 Stage A LLM 0회. 코드: `run_n3.py`, 집계: `aggregate_n3.py`. 산출: `K{10,5}_run{1,2,3}.json` 6개.

## 질문

exp7에서 Stage B 1회로 본 결과가 만들어졌을 때, "같은 클러스터를 3번 보면 LLM이 다르게 분류할 수 있다"는 가능성이 남아 있었다. 그래서 (1) 앵커(외울 핵심 14 + 배경 8) recall은 n=1과 n=3에서 다른가, (2) 다수결(>= 2/3)이 단일 패스 대비 어떤 엔티티를 뒤집는가, (3) K=10과 K=5에서 안정성이 비슷한가.

## 설정

- K=10 / K=5 각각 Stage B 3패스. 클러스터 자체는 결정적이라 패스 간 멤버 구성은 동일.
- 앵커: `archive/exp10_room_gen/anchors_korean_history.json` (한국사). should_show 14 / should_demote 8.
- 다수결 규칙: votes > n/2. n=3이면 keep ≥ 2/3 → keep, 아니면 demote.

## 앵커 (3런 + 다수결)

| K | run | should_show /14 | should_demote /8 |
|---:|---|---:|---:|
| 10 | run1 | 13 | 7 |
| 10 | run2 | 13 | 7 |
| 10 | run3 | 13 | 7 |
| 10 | **majority** | **13** | **7** |
| 5 | run1 | 7 | 8 |
| 5 | run2 | 7 | 6 |
| 5 | run3 | 7 | 7 |
| 5 | **majority** | **7** | **8** |

K=10 패스 간 flip rate (앵커 한정): should_show 0/14, should_demote 0/8. 14+8 = 22 앵커 전부 3패스에서 같은 분류. 다수결도 같음. 앵커 recall에 한해서는 n=3이 no-op.

K=5는 다르다. should_demote가 8/6/7로 흔들림 (flip 3/8 = 37.5%). 클러스터가 거칠어 경계 라벨이 매번 같지 않다. K=5는 그래서 안정성 평가에서 fail.

## 다수결이 뒤집은 것 (전체 357 기준)

| K | 전체 flip | should_show flip | should_demote flip |
|---:|---|---|---|
| 10 | 32/357 (9.0%) | 0/14 (0.0%) | 0/8 (0.0%) |
| 5 | 27/357 (7.6%) | 0/14 (0.0%) | 3/8 (37.5%) |

- K=10: 앵커는 다 안정인데 비-앵커 32개(9%)가 패스 간 흔들림. 다수결이 그 중 일부를 가르는 역할.
- K=5: 앵커 자체가 일부 흔들리고 비-앵커는 27개(7.6%).

## 이성계 회귀 (참고)

| K | run1 | run2 | run3 | maj | room |
|---:|---|---|---|---|---|
| 10 | demote | demote | demote | demote | 2 (`임진왜란과 조선 군사`) |
| 5 | demote | demote | demote | demote | 1 (`임진왜란과 군사 지도자`) |

exp7에서 keep으로 살아남던 이성계가 exp10/exp12에서 임진왜란 방으로 끌려가 demote 처리됨. 패스 3회 모두 동일 분류. n=3으론 안 풀린다 (exp13에서 다른 처방을 시도하지만 결국 hub 매개 문제로 판명, exp13 보고서 참조).

## 방 이름 일관성 (참고)

K=10 10방 중 5방이 3패스 모두 동일, 5방은 어순·단어가 살짝 다름 ("조선 토지·시험·정책" vs "조선 토지·시험·제도" 등). 의미는 동일 수준.

## 전체 keep-set 정밀 일치도 (canonical runner)

이 디렉토리는 클러스터별 결과·앵커만 본다. 방 단위 keep-set이 패스 간 얼마나 일치하는지, 다수결이 몇 개 엔티티를 정리했는지는 confirmed-pipeline runner (`archive/pipeline/`)가 측정한다. 참조: [`archive/pipeline/report.md`](../pipeline/report.md). 거기에 다음이 있다:

- per-room mean pair-jaccard 0.906, min 0.6154 (room 4가 [8, 13, 13]으로 가장 흔들림).
- split entities (3패스 만장일치 아님): 26/357 (7.3%) → 다수결이 정리.
- 만장일치 방 5/10, 방 이름 unanim 9/10.

즉 앵커 단위로는 K=10에서 n=3이 no-op처럼 보이지만, 전체 keep-set으로 보면 다수결이 ~7%의 경계 엔티티를 매번 같은 결정으로 수렴시킨다.

## 그래서

- 앵커 recall만 본다면 K=10·n=1으로 충분. 3패스가 모두 같은 답.
- 전체 keep-set의 일관성·재현성을 원하면 n=3. 경계 ~7% 엔티티 결정이 안정됨.
- K=5는 안정성 평가에서 fail (should_demote flip 37.5%). 제품에서 안 씀.
- 확정·평가 런: n=3.
- 제품에서 7% churn을 감수할 수 있으면 비용 1/3인 n=1도 후보.

## 비용

- Stage A: 0 LLM (rubric 캐시 hit).
- Stage B: 클러스터 × n_runs × K 조합. K=10×3 = 30 호출, K=5×3 = 15 호출. 합 45 호출. 토큰·달러는 confirmed-pipeline 보고서(`archive/pipeline/report.md`)에 별도 기록.

## 다음 단계 (이번 작업 밖)

- n=5도 의미 있는 추가 안정화를 주는지(=비용 vs 일치도 곡선)는 안 봄. 7% churn이 더 줄어들 가능성.
- 경계 엔티티 26개의 특성(degree·type) 패턴 분석.
