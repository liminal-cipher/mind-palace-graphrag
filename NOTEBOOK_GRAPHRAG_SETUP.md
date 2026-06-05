# 노트북 GraphRAG 작업 환경 복원 안내

이 문서는 노트북에서 GraphRAG 작업만 이어가기 위한 체크리스트다. 3D 방/지도 UI 작업은 제외한다.

## 1. GitHub에서 받을 것

노트북에서 먼저 저장소를 clone 한다.

```bash
git clone https://github.com/JunK98/3cha-project.git
cd 3cha-project
```

GitHub에는 코드, 프롬프트, 설정 파일, GraphRAG 분석 결과 문서/HTML/JSON/TXT가 들어 있다.

주요 작업 폴더:

```text
그래프라그/graphrag_quickstart
```

주요 스크립트:

```text
run_llm_rag_first_pass.py
build_llm_rag_ui_first_design.py
build_12_llm_room_design.py
merge_communities.py
run_merge_judgement.py
semantic_quality_review.py
audit_entity_quality.py
apply_entity_quality_algorithms.py
read_results.py
```

주요 프롬프트/설정:

```text
그래프라그/graphrag_quickstart/settings.yaml
그래프라그/graphrag_quickstart/prompts/
```

## 2. USB에서 복원할 것

GitHub에는 API 키와 로컬 실행 산출물을 올리지 않았다. USB의 아래 폴더에서 필요한 파일을 같은 경로에 복사한다.

```text
F:/project/3차프로젝트_로컬실행파일
```

필수:

```text
.ENV
그래프라그/graphrag_quickstart/.env
```

선택:

```text
그래프라그/graphrag_quickstart/cache/
그래프라그/graphrag_quickstart/logs/
그래프라그/graphrag_quickstart/output/lancedb/
그래프라그/graphrag_quickstart/output/그래프라그 방나누기/LLM+라그/1차/graphrag_root/cache/
그래프라그/graphrag_quickstart/output/그래프라그 방나누기/LLM+라그/1차/graphrag_root/logs/
그래프라그/graphrag_quickstart/output/그래프라그 방나누기/LLM+라그/1차/graphrag_root/output/lancedb/
```

선택 항목은 이전 실행 결과를 재사용하고 싶을 때만 복사하면 된다. 새로 돌릴 거면 없어도 된다.

## 3. 노트북에서 새로 설치할 것

가상환경은 노트북에서 새로 만든다. 데스크톱의 `.venv`는 경로와 OS 환경 차이 때문에 그대로 복사하지 않는 것이 좋다.

```bash
cd 그래프라그/graphrag_quickstart
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
```

GraphRAG와 후처리 스크립트에 필요한 패키지:

```bash
pip install graphrag openai python-dotenv pandas pyarrow pyyaml requests beautifulsoup4
```

만약 실행 중 추가 패키지 오류가 나오면 해당 패키지만 추가 설치하면 된다.

## 4. Azure/OpenAI 설정 확인

`그래프라그/graphrag_quickstart/.env`에 아래 값들이 있어야 한다.

```text
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=...
AZURE_OPENAI_GPT54MINI_DEPLOYMENT=...
```

키 값은 GitHub에 올리지 말고 로컬 `.env`에만 둔다.

## 5. GraphRAG 작업 실행 위치

GraphRAG 관련 명령은 보통 아래 폴더에서 실행한다.

```bash
cd 그래프라그/graphrag_quickstart
```

예시:

```bash
graphrag index --root .
python read_results.py
```

LLM+RAG UI 우선 방 설계 쪽은 기존 결과를 참고해 아래 스크립트부터 확인한다.

```bash
python build_llm_rag_ui_first_design.py --help
python run_llm_rag_first_pass.py --help
```

## 6. GitHub에 올리지 않는 것

아래 항목은 노트북에서도 Git에 올리지 않는다.

```text
.env
.ENV
.venv/
cache/
logs/
output/lancedb/
node_modules/
```

## 7. 3D 방 관련 제외

이번 노트북 복원 목적은 GraphRAG 분석과 LLM 기반 방 구성 실험이다. 3D 방/지도 UI 관련 의존성은 따로 설치하지 않아도 된다.

`준상test` 쪽 Node 작업이나 대용량 3D UI 산출물은 필요할 때 별도로 다룬다.
