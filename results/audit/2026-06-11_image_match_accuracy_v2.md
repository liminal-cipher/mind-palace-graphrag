# image-caption matching accuracy (2026-06-11, v2)

- palace: `palace/handoff/repro_run3_K6_toc.palace.json`
- snapshot: `results/snapshots/repro_run3`
- figures dir: `input/img_국사`
- captions: `input/extracted_figures.md`
- pagesplit: `input/history_joseon_pagesplit.txt`
- T_local = 0.45, T_cascade = 0.55, name bonus = +0.5, hub max = -0.1, page window = +/-1, min_name_len = 2
- name-match: whitespace tokens + exact/prefix (symmetric), length-1 tokens & ent titles excluded
- rows: 34 (figures: 33, palace nodes: 357)

| # | 제목 | 페이지 | 파일 | 매칭 노드 | tier | 점수 | 근거 |
|---:|---|---:|---|---|---|---:|---|
| 1 | 도산 서원 | 2 | `input/img_국사/fig_2_2.png` | 서원 | 1차 | 0.838 | name+0.50 cos=0.345 hub-0.007 |
| 2 | 호패 | 5 | `input/img_국사/fig_5_3.png` | 호패법 | 1차 | 0.806 | name+0.50 cos=0.311 hub-0.005 |
| 3 | 경국대전 | 6 | `input/img_국사/fig_6_2.png` | 경국대전 | 1차 | 1.283 | name+0.50 cos=0.788 hub-0.005 |
| 4 | 교린지 | 6 | `input/img_국사/fig_6_3.png` | - | 미배치 | 0.388 | cos=0.392 hub-0.005 |
| 5 | 4군과 6진 | 7 | `input/img_국사/fig_7_2.png` | 4군 | 1차 | 0.981 | name+0.50 cos=0.483 hub-0.002 |
| 6 | 왜관도(국립 중앙 박물관 소장) | 7 | `input/img_국사/fig_7_3.png` | 중앙군 | 캐스케이드 | 0.667 | name+0.50 cos=0.170 hub-0.002 |
| 7 | 조선의 8도 | 9 | `input/img_국사/fig_9_2.png` | 조선 | 1차 | 0.660 | name+0.50 cos=0.260 hub-0.100 |
| 8 | 서당 | 10 | `input/img_국사/fig_10_2.png` | 서당 | 1차 | 0.783 | name+0.50 cos=0.286 hub-0.002 |
| 9 | 향교 알성도 | 10 | `input/img_국사/fig_10_2.png` | 향교 | 1차 | 0.879 | name+0.50 cos=0.384 hub-0.005 |
| 10 | 고창 읍성 | 10 | `input/img_국사/fig_10_3.png` | 읍성 | 1차 | 0.804 | name+0.50 cos=0.307 hub-0.002 |
| 11 | 조선 시대의 조창과 조운 | 11 | `input/img_국사/fig_11_2.png` | 조선 초기 | 1차 | 0.897 | name+0.50 cos=0.397 |
| 12 | 영릉 | 12 | `input/img_국사/fig_12_2.png` | - | 미배치 | 0.359 | cos=0.361 hub-0.002 |
| 13 | 훈민정음(언해본) | 12 | `input/img_국사/fig_12_3.png` | 훈민정음 | 1차 | 0.849 | name+0.50 cos=0.359 hub-0.010 |
| 14 | 조선왕조실록 | 13 | `input/img_국사/fig_13_2.png` | 조선왕조실록 | 1차 | 1.206 | name+0.50 cos=0.706 |
| 15 | 측우기 | 13 | `input/img_국사/fig_13_4.png` | 측우기 | 1차 | 1.086 | name+0.50 cos=0.586 |
| 16 | 김종직 교지 | 16 | `input/img_국사/fig_16_2.png` | 김종직 | 1차 | 1.114 | name+0.50 cos=0.619 hub-0.005 |
| 17 | 필암 서원 확연루 | 17 | `input/img_국사/fig_17_2.png` | - | 미배치 (충돌) | 0.771 | name+0.50 cos=0.279 hub-0.007 |
| 18 | 농사직설 | 18 | `input/img_국사/fig_18_2.png` | 농사직설 | 1차 | 1.054 | name+0.50 cos=0.556 hub-0.002 |
| 19 | 소수 서원의 명륜당 | 19 | `input/img_국사/fig_19_3.png` | 소수 서원 | 1차 | 1.028 | name+0.50 cos=0.533 hub-0.005 |
| 20 | 충무공 이순신 영정 | 25 | `input/img_국사/fig_25_2.png` | 이순신 | 1차 | 0.832 | name+0.50 cos=0.349 hub-0.017 |
| 21 | 유정(사명대사) 영정 | 25 | `input/img_국사/fig_25_3.png` | 유정 (사명대사) | 1차 | 1.037 | name+0.50 cos=0.540 hub-0.002 |
| 22 | 통신사 행렬도(국사 편찬 위원회 소장) | 27 | `input/img_국사/fig_27_3.png` | 통신사 | 1차 | 0.960 | name+0.50 cos=0.470 hub-0.010 |
| 23 | 봉사도 | 28 | `input/img_국사/fig_28_2.png` | - | 미배치 | 0.393 | cos=0.396 hub-0.002 |
| 24 | 정묘호란과 병자호란 | 30 | `input/img_국사/fig_30_2.png` | 정묘호란 | 1차 | 0.959 | name+0.50 cos=0.461 hub-0.002 |
| 25 | 이완이 썼던 투구(경기도 박물관 소장) | 31 | `input/img_국사/fig_31_2.png` | - | 미배치 (충돌) | 0.768 | name+0.50 cos=0.270 hub-0.002 |
| 26 | 이완에게 내린 홍패 교지(경기도 박물관 소장) | 31 | `input/img_국사/fig_31_3.png` | 이완 | 1차 | 0.807 | name+0.50 cos=0.309 hub-0.002 |
| 27 | 나선 정벌 | 31 | `input/img_국사/fig_31_4.png` | 나선 정벌 | 1차 | 0.901 | name+0.50 cos=0.403 hub-0.002 |
| 28 | 대장간 | 36 | `input/img_국사/fig_36_2.png` | - | 미배치 | 0.489 | cos=0.492 hub-0.002 |
| 29 | 영조 어진(국립 고궁 박물관 소장) | 37 | `input/img_국사/fig_37_3.png` | 영조 | 1차 | 1.056 | name+0.50 cos=0.586 hub-0.029 |
| 30 | 거중기 모형(경기도 박물관) | 37 | `input/img_국사/fig_37_4.png` | - | 미배치 | 0.395 | cos=0.398 hub-0.002 |
| 31 | 옥산 서원 | 38 | `input/img_국사/fig_38_2.png` | - | 미배치 (충돌) | 0.728 | name+0.50 cos=0.235 hub-0.007 |
| 32 | 송시열 초상(호암 미술관 소장) | 39 | `input/img_국사/fig_39_2.png` | 송시열 | 1차 | 0.969 | name+0.50 cos=0.471 hub-0.002 |
| 33 | 탕평비 | 40 | `input/img_국사/fig_40_2.png` | 탕평비 | 1차 | 0.846 | name+0.50 cos=0.348 hub-0.002 |
| 34 | 논갈이 | 49 | `input/img_국사/fig_49_2.png` | - | 미배치 | 0.375 | cos=0.377 hub-0.002 |

## diff vs 2026-06-11_image_match_accuracy.md

- 바뀐 행: 6 / 34

| # | 제목 | before (노드, tier, 점수) | after (노드, tier, 점수) |
|---:|---|---|---|
| 2 | 호패 | 군역 제도 · 캐스케이드 · 0.452 | 호패법 · 1차 · 0.806 |
| 6 | 왜관도(국립 중앙 박물관 소장) | - · 미배치 · 0.353 | 중앙군 · 캐스케이드 · 0.667 |
| 7 | 조선의 8도 | - · 미배치 (충돌) · 0.660 | 조선 · 1차 · 0.660 |
| 11 | 조선 시대의 조창과 조운 | 조선 · 1차 · 0.752 | 조선 초기 · 1차 · 0.897 |
| 28 | 대장간 | 대동여지도 · 캐스케이드 · 0.490 | - · 미배치 · 0.489 |
| 31 | 옥산 서원 | 원 · 1차 · 0.767 | - · 미배치 (충돌) · 0.728 |