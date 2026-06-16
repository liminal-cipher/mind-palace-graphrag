# archive (동결)

정본은 `palace/`. 여기만 보면 된다.

이 디렉토리는 정본이 확정되기까지의 실험 전부를 동결 보관한다. 새 작업 금지: 여기에 코드를 추가하거나 실험을 다시 돌리지 않는다. 각 실험 폴더에는 동결 시점을 표시한 `ARCHIVED.md`가 있다.

## 구성

- `pipeline/`: 구 GRAPH arm canonical 러너 (K=10 embedding). palace 정본에서 빠진 grandfather.
- `rooms/`, `viewer/`, `reports/`, `status/`: 실험 산출물, 뷰어, 리포트, 진행 기록.
- `node_order_probe/`, `exp_model_compare/`: 위치 metric 및 모델 비교 프로브.
- `exp05_stage2_merge` … `exp17_generalization`: 실험 회차별 코드와 리포트.
- `snapshots/`: 실험 전용 인덱스 스냅샷 (exp2_max15, exp4_lcc_true, snap_max10, snap_max20, repro_run2, semantic_run1, pagesplit_run1).

## live는 어디에

live 스냅샷(`repro_run3`, `ai_school`, `ai_school_realistic`)과 audit 리포트는 `results/`에 그대로 있다. 재현 절차는 `results/RUNBOOK.md`, 실험 누적 narrative는 `results/EXPERIMENTS.md` 참조.
