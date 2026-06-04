# 레포 컨벤션

향후 작업에 적용할 규칙. 과거(exp1~9, snapshots 명명 등)는 grandfather: 그대로 두고 새로 만드는 것부터 따른다.

## 실험 디렉토리

- 위치: `results/exp{N}_{slug}/` (예: `results/exp10_<slug>/`). slug는 짧고 영문 소문자, 단어 사이는 `_`.
- 안에 코드·산출·리포트가 같이 산다.
  - 코드: `*.py`. 진입점이 하나면 `probe.py`, 여러 단계면 의미 있는 이름(`build_inputs.py`, `run_full.py`, `eval_run.py` 등).
  - 리포트: `report.md` (단독 결과) 또는 `comparison.md` (둘 이상 비교).
  - 산출 JSON·표는 같은 디렉토리에. 대용량 원시 응답은 `raw/` 하위.
- 루트(`/`)엔 새 실험 코드를 두지 않는다. 범용 유틸(`analyze_baseline.py`, `extract_results.py`)만 루트에.

## 인덱스

- 정본: `results/EXPERIMENTS.md`. 모든 실험을 한 곳에서 훑을 수 있는 narrative. 새 실험 끝나면 여기 한 섹션 추가.
- 보조: `results/reports/INDEX.md` (구 체계, exp1~5 보고서 매핑). 새 실험은 여기 안 추가, EXPERIMENTS.md만 갱신.

## 스냅샷

- 위치: `results/snapshots/<name>/`. gitignored.
- 새 이름은 `<descriptor>_run<N>` 권장 (예: `pagesplit_run1`, `semantic_run2`). 과거 명명(`repro_runN`, `snap_maxN`, `exp{N}_{var}`)은 grandfather라 그대로 둔다.
- 한 스냅샷 = entities/relationships/communities/community_reports parquet + lancedb/ 한 묶음. 부분만 떠 있으면 안 됨.

## 입력 자료

- 원천: `input/`. 사람이 만든·받아 온 자료 그대로.
- 실험별 변환 입력: 그 실험이 쓰는 graphrag 프로젝트의 `proj_*/input/` (예: `proj_semantic/input/`). build 스크립트로 원천을 변환해 떨어뜨린다.
- 원천에 사람 이름·내부 식별자가 들어 있으면 변환 단계에서 중립 표현으로 바꾼다.

## graphrag 프로젝트

- 위치: `proj_<descriptor>/` (예: `proj_semantic`, `proj_pagesplit`).
- 안에 `settings.yaml`과 `input/`만.
- `settings.yaml`의 `output_storage`·`reporting`·`cache`·`vector_store.db_uri`는 모두 `../output/<run>`, `../logs/<run>`, `../cache/<run>`, `../output/<run>/lancedb` 패턴으로 repo 루트 기준에 맞춘다.

## 커밋

- 영어 conventional (`feat(scope): ...`, `fix(scope): ...`, `chore: ...`, `docs(scope): ...`).
- 스코프는 실험 ID 또는 모듈(`exp9`, `exp5`, `index`, `eval`).
- 메시지에 AI 도구·세션·`Claude`/`Co-Authored-By: Claude` 같은 흔적 금지.
- push는 사용자 명시 지시 받기 전까지 안 함.
- 한 단계 = 한 커밋. 실패한 단계는 커밋하지 않고 멈춰서 보고.

## 문서

- `.md`엔 em dash(유니코드 U+2014) 금지. 콜론·쉼표·괄호로 대체.
- 모든 수치·주장은 repo 내 출처 파일을 참조해 검증 가능해야 함. 출처 없는 해석은 명시적으로 "추정"으로 표시.
