## 리포트 인덱스

`results/` 루트에 흩어져 있던 리포트를 여기로 모았다. 파일명 규칙은 `REPORT_TEMPLATE.md` 참고.

## 매핑표

| 원본 파일 | 현재 파일 | type |
|---|---|---|
| `results/baseline_2026-06-02.md` | `00_baseline.md` | experiment |
| `results/실험2_2026-06-02.md` | `01_max15.md` | experiment |
| `results/snap_max10_2026-06-02.md` | `02_snap_max10.md` | experiment |
| `results/snap_max20_2026-06-02.md` | `02_snap_max20.md` | experiment |
| `results/Step1_스냅샷비교_2026-06-02.md` | `03_repro_step1_snapshot.md` | synthesis |
| `results/Step2_재현성_2026-06-02.md` | `03_repro_step2_variance.md` | synthesis |
| `results/Step3_종합_2026-06-02.md` | `03_repro_step3_summary.md` | synthesis |
| `results/실험4_lcc_2026-06-02.md` | `04_use_lcc.md` | experiment |
| `results/exp5_data_contract.md` | `05_exp5_data_contract.md` | spec |

## 접두 규칙

- `00` baseline
- `01` 실험 2 (max_cluster_size 변경)
- `02` 스냅샷 캐시 검증 (max=10, max=20)
- `03` 재현성 분석 3단계 (synthesis)
- `04` 실험 4 (use_lcc)
- `05` 실험 5 (방 병합, spec/계약서)

날짜는 파일명에서 뺐다. 날짜는 frontmatter의 `date` 필드에 있다.
