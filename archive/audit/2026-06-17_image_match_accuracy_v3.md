# image-caption matching accuracy (2026-06-17, v3)

- palace: `deliverables/statistics/palace.json`
- snapshot: `snapshots/statistics`
- figures dir: `input/statistics/img`
- captions: `input/statistics/captions.md`
- pagesplit: `input/statistics/pagesplit.txt`
- T_local = 0.45, T_cascade = 0.55, name bonus = +0.5, hub max = -0.1, page window = +/-1, min_name_len = 2
- name-match: whitespace tokens from TITLE only (trailing parenthetical stripped) + exact/prefix (symmetric), length-1 tokens & ent titles excluded
- rows: 14 (figures: 14, palace nodes: 92)

| # | 제목 | 페이지 | 파일 | 매칭 노드 | tier | 점수 | 근거 |
|---:|---|---:|---|---|---|---:|---|
| 1 | 데이터 분포의 비대칭성 유형(양의 왜도, 대칭 분포, 음의 왜도)에 따른 평균, 중앙값, 최빈값의 위치 변화를 보여주는 그래프입니다. | 18 | `input/statistics/img/fig_18_1.png` | 왜도 | 1차 | 1.056 | name+0.50 cos=0.568 hub-0.011 |
| 2 | 그래프는 Leptokurtic, Mesokurtic, Platykurtic 분포의 확률 밀도 차이를 비교하여 보여줍니다. | 19 | `input/statistics/img/fig_19_1.png` | 확률 밀도 함수 | 캐스케이드 | 0.918 | name+0.50 cos=0.429 hub-0.011 |
| 3 | 확률 분포의 관계와 상호 연결성을 시각적으로 나타낸 다이어그램. | 25 | `input/statistics/img/fig_25_1.png` | 확률밀도함수 | 1차 | 0.897 | name+0.50 cos=0.419 hub-0.022 |
| 4 | 베르누이 분포 X ~ Bernoulli(p)의 확률 질량 함수(PMF)를 보여주는 그래프로, 0과 1에서 각각의 확률값 p와 1-p를 나타냅니다. | 26 | `input/statistics/img/fig_26_1.png` | 베르누이 분포 | 1차 | 1.073 | name+0.50 cos=0.618 hub-0.044 |
| 5 | 이 이미지는 데이터를 시각화한 정규 분포 히스토그램을 보여줍니다. | 27 | `input/statistics/img/fig_27_1.png` | 시각화 | 캐스케이드 | 0.827 | name+0.50 cos=0.338 hub-0.011 |
| 6 | 이 이미지는 확률 분포의 히스토그램과 이론적 확률 밀도 함수를 비교한 그래프입니다. | 28 | `input/statistics/img/fig_28_1.png` | 확률 변수 | 1차 | 0.906 | name+0.50 cos=0.462 hub-0.056 |
| 7 | 정규분포 곡선은 평균을 기준으로 데이터의 68.3%, 95.4%, 99.7%가 각각 ±1σ, ±2σ, ±3σ 범위 안에 분포함을 보여줍니다. | 29 | `input/statistics/img/fig_29_1.png` | 정규 분포 | 1차 | 1.092 | name+0.50 cos=0.647 hub-0.056 |
| 8 | 지수적으로 감소하는 함수 \(f(t) = \lambda e^{-\lambda t}\)의 그래프를 나타냅니다. | 30 | `input/statistics/img/fig_30_1.png` | - | 미배치 | 0.310 | cos=0.310 |
| 9 | n값에 따라 분포의 형태가 달라지는 그래프를 나타냅니다. | 31 | `input/statistics/img/fig_31_1.png` | - | 미배치 | 0.346 | cos=0.346 |
| 10 | 정규분포에서 신뢰구간과 유의수준(α)을 나타낸 그래프입니다. | 35 | `input/statistics/img/fig_35_1.png` | 신뢰 구간 | 캐스케이드 | 0.847 | name+0.50 cos=0.358 hub-0.011 |
| 11 | 상관계수 r 값에 따른 음의 상관관계, 무상관, 양의 상관관계의 강도를 나타낸 그래프들입니다. | 45 | `input/statistics/img/fig_45_1.png` | - | 미배치 | 0.416 | cos=0.450 hub-0.033 |
| 12 | 사람 A부터 E까지 각각 키와 몸무게의 순위를 나타낸 표입니다. | 48 | `input/statistics/img/fig_48_1.png` | - | 미배치 | 0.313 | cos=0.324 hub-0.011 |
| 13 | 사람 A부터 E까지의 키와 몸무게를 동일한 값으로 비교한 표입니다. | 48 | `input/statistics/img/fig_48_2.png` | 동일한 확률 하에서 표본 추출 | 캐스케이드 | 0.811 | name+0.50 cos=0.311 |
| 14 | 사람들의 키와 몸무게 순위를 비교한 표입니다. | 48 | `input/statistics/img/fig_48_3.png` | - | 미배치 | 0.322 | cos=0.333 hub-0.011 |