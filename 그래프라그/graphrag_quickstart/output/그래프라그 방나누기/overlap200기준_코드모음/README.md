# overlap200 기준 코드모음

이 폴더는 `LLM+라그/2차/overlap200` 결과를 다른 조원이 확인하거나 필요한 부분을 바로 복붙해서 쓸 수 있도록 코드, 프롬프트, 설정, 대표 산출물만 모은 것이다.

## 기준 산출물

- GraphRAG chunk_size: 1200
- GraphRAG chunk_overlap: 200
- 입력 원문: `01_graphrag_step1/input/content.txt`
- GraphRAG 주요 결과:
  - documents: 1
  - text_units: 27
  - entities: 288
  - relationships: 263
  - communities: 37
  - community_reports: 37

## 폴더 구성

- `01_graphrag_step1/`
  - GraphRAG 1단계 실행에 사용된 `settings.yaml`, `prompts/`, `input/`
  - downstream에서 바로 읽을 수 있는 parquet snapshot도 `output_snapshot/`에 포함
- `02_downstream_code/`
  - GraphRAG 결과를 LLM 방 설계, quality gate, coverage repair, 시각화로 넘기는 Python 코드
- `03_overlap200_outputs/`
  - overlap200 최종 JSON/MD/HTML 산출물
  - manual backup 파일은 제외
## 실행 흐름

1. `01_graphrag_step1/settings.yaml`과 `prompts/`를 기준으로 GraphRAG를 실행한다.
2. 생성된 GraphRAG output parquet을 downstream 코드가 읽는다.
3. `02_downstream_code/build_llm_rag_ui_first_design.py`가 UI 우선 방 설계, supporting quality gate, LLM coverage repair를 수행한다.
4. 최종 결과는 `03_overlap200_outputs/UI우선_방설계.json`, `UI우선_방설계.md`, `UI우선_방_엔티티_시각화.html` 형태로 확인한다.

## 주의

- `.env`, 가상환경, 설치 파일, cache, logs는 포함하지 않았다.
- `cache/`, `logs/`, `manual_coverage_backup` 파일은 재현에 필수는 아니라 제외했다.
- 이 모음은 overlap200 결과 기준이다. 다른 overlap 또는 pagesplit/semantic 방식과 비교하려면 GraphRAG 1단계 설정을 별도 실험 폴더로 분리해서 돌리는 것이 좋다.
