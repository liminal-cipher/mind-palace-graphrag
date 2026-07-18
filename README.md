# 회랑 (GraphRAG 파이프라인)

> 학습 자료(한국사 교과서, 통계 교안 등)를 1인칭 3D Mind Palace로 만드는 백엔드 시스템.
> 
> 자료의 TOC(목차)를 LLM이 만들고 그 섹션을 Room(방)으로 써서 개념을 배정·선별한 뒤, GraphRAG 인덱스 위에서 질의(RAG)와 쇼케이스 Palace를 서빙한다.

**Frontend Repository**: [Mindpalace_Microsoft9ai_Thirdprj-](https://github.com/PhrenO0/Mindpalace_Microsoft9ai_Thirdprj-)

---

## Repository Structure

| 폴더 | 역할 |
|---|---|
| `backend/` | 서빙(통합 FastAPI). `app`(진입점) + `serve`(RAG 질의) + `showcase`(Palace·이미지) + `query`(엔진) |
| `orchestrator/` | 업로드 → 인덱싱 → palace → 등록 자동 파이프라인(라이브 인제스트) |
| `palace/` | Room 빌드 정본. TOC → Room 배정/선별 → `palace.json` (`run.py`, `build_rooms.py`, `configs/`, `tests/`) |
| `indexing/` | 도메인별 GraphRAG 인덱싱 config (`<domain>/settings.yaml` + 튜닝 프롬프트, `_template.settings.yaml`) |
| `preprocessing/` | 원본 PDF → 정제 코퍼스 (`pipeline_v2.py`, `normalize.py`, `source/`, `result/`) |
| `snapshots/` | 빌드된 GraphRAG 인덱스 (`korean_history`=국사 골든, `statistics`) |
| `deliverables/` | 프론트가 읽는 도메인별 산출물 (`<domain>/palace.json`, `palace_with_images.json`, `images/`) |
| `docs/` | 분석 문서 (`RUNBOOK.md`, `EXPERIMENTS.md`, `CONVENTIONS.md`, `audit/`) |
| `input/` | 도메인별 정제 코퍼스 (저작물, gitignored) |
| `archive/` | 동결된 실험·분석 (`ARCHIVED.md` 표시, 새 작업 금지) |
| `prompts/` | 공유 프롬프트(검색 + 기본 인덱싱). 루트 `settings.yaml`은 쿼리 config |

---

## Getting Started

1. Python 3.13 + 가상환경(venv) 설정:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. 환경변수 설정: `.env.example`을 `.env`로 복사하고 키를 채운다 (`.env`는 gitignored).
   - `GRAPHRAG_API_KEY`, `GRAPHRAG_API_BASE`: 쿼리·인덱싱(Azure OpenAI)
   - `CONTENT_UNDERSTANDING_*`, `OPEN_AI_*`: 전처리(`preprocessing/pipeline_v2.py`)에서만 필요
3. **골든 검증 재현**: 기본 스냅샷 `snapshots/korean_history/`(국사, 357 엔티티)가 있어야 재현이 가능하다.

---

## Usage

### Running the Server
```bash
gunicorn backend.app:app --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
# 개발:  uvicorn backend.app:app --reload
```
> **참고 (App Service 배포)**: 
> - `Startup Command`: `bash startup.sh`
> - `var` 위치는 `ORCH_VAR_DIR`로 바꿀 수 있으나 `/home`(Azure Files/SMB)은 쓰지 않는다. 스냅샷 lancedb가 SMB에서 0바이트로 깨지는 문제가 있다. 기본값인 `REPO/var`(로컬)로 두고, 재시작 생존이 필요하면 Blob 영속을 따로 붙인다.

### API Specifications
서빙 도메인: `korean_history`, `statistics`.

| 메서드 · 경로 | 용도 |
|---|---|
| `GET /palace/{name}` | 쇼케이스 Palace JSON(이미지 포함) |
| `GET /images/{name}/{file}` | Palace가 참조하는 그림 |
| `POST /query` | RAG 질의. body `{"question": "...", "snapshot": "korean_history"}` → `{"answer", "snapshot", "mode", "sources", "usage"}` |
| `GET /health` · `/ready` | 헬스 / 스냅샷 준비 여부 |
| `POST /orchestrator/upload?filename=&domain=` | 파일(raw body) 업로드 → 자동 체인 → `job_id` |
| `GET /orchestrator/jobs/{id}/status` · `/palace` | Job 진행 / 산출 Palace(이미지 매칭 시 노드에 `images[]` 포함) |
| `GET /orchestrator/jobs/{id}/toc` | 조기 LLM TOC(Room 생성 전, `toc_ready` 시). 둘러보기 페이지용 |
| `GET /orchestrator/jobs/{id}/images/{file}` | 라이브 Job이 매칭한 그림(노드 `images[].path` = `images/<file>`) |
| `POST /jobs/{id}/query` | 라이브 Job RAG 질의 |
| `GET /quiz` · `POST /quiz/grade` 등 | (실험 기능) 퀴즈 페이지 및 JSON 응답 API |
| `POST /mnemonic` | (실험 기능) 핫스팟→학습노드 연상 장면 생성 |
| `GET /api/speech-token` | (실험 기능) 브라우저용 Azure Speech 단기 토큰 발급 |

### Examples
```bash
# 쇼케이스 Palace (프론트)
curl http://127.0.0.1:8000/palace/korean_history

# RAG 질의
curl -X POST http://127.0.0.1:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"조선 전기의 통치 제도를 설명해줘.","snapshot":"korean_history"}'

# 라이브 업로드 → 자동 인덱싱·Palace (이후 /orchestrator/jobs/<id>/status 폴링)
curl -X POST "http://127.0.0.1:8000/orchestrator/upload?filename=corpus.txt&domain=statistics" \
  --data-binary @input/statistics/corpus.txt
```

---

## Frontend Integration

라이브 Job과 쇼케이스는 경로 규칙이 다르다. 프론트엔드 연동 시 아래 규칙을 따른다.

### 1. Route Prefix Notes
- Job 상태/Palace/이미지는 `/orchestrator/jobs/{id}/...` 형태.
- 라이브 RAG 질의만 **prefix 없는 루트** `/jobs/{id}/query` 이다 (`serve`가 `/`에 마운트됨). `/orchestrator/jobs/{id}/query` 가 아니다.

### 2. Node Image URL Mapping
노드의 `images[].path`는 라이브·쇼케이스 모두 `images/<file>` 형식이다(끝의 파일명만 의미를 가짐). 프론트에서 서빙 URL은 출처별로 조립해야 한다.
- **쇼케이스**: `/images/{name}/<file>` (예: `images/fig_10_2.png` → `/images/korean_history/fig_10_2.png`)
- **라이브 Job**: `/orchestrator/jobs/{id}/images/<file>` (예: `/orchestrator/jobs/<job_id>/images/fig_6_3_cv_1.png`)

### 3. Job Status Polling & Loading Bar
`GET /orchestrator/jobs/{id}/status` 폴링을 통해 Job 진행 상태를 파악한다.
- `state`: `QUEUED → PREPROCESSING → TOC_READY → INDEXING → BUILDING_PALACE → PALACE_READY → DONE` (실패 시 `FAILED`). `RAG_READY`는 DONE 직전의 순간 상태.
- **게이팅**: 
  - `toc_ready=true` ➡️ `/orchestrator/jobs/{id}/toc` (Room 생성 전 TOC 미리보기)
  - `palace_ready=true` ➡️ `/orchestrator/jobs/{id}/palace`
  - `rag_ready=true` (=DONE) ➡️ `/jobs/{id}/query`

**로딩 바 구현 레시피**:
- 응답의 `progress` 객체를 그대로 활용하여 스텝퍼를 그린다. (`status`: `pending | active | done | failed`)
- 긴 `active` 단계(예: 인덱싱)에서 바가 멈춰 보이지 않게 하려면 프론트엔드에서 경과 시간으로 보간한다.
```js
// status = 방금 받은 progress, enteredAt = 그 state 진입 시각(updated_at)
const active = status.steps.find(s => s.status === "active");
let pct = status.percent;
if (active) {
  const elapsed = (Date.now() - new Date(enteredAt)) / 1000;
  const frac = Math.min(elapsed / active.est_seconds, 0.95); // 끝까진 안 채움
  pct += active.weight * frac;
}
// pct로 바를 그리되, 다음 폴링 시 단계가 넘어가면 해당 단계 weight까지 차오름
```

### 4. Early TOC & API Payload Structure
- **조기 TOC**: `GET /orchestrator/jobs/{id}/toc` ➡️ LLM TOC JSON 반환 (`toc_ready=true` 시점부터 호출 가능. 그 전엔 409 응답).
- **Request Body (요청 본문)**: 
  - `POST /query`: `{"question": str, "snapshot": str, "method"?: "auto"|"local"|"global"}` (`snapshot` 누락 시 400 응답)
  - `POST /jobs/{id}/query`: `{"question": str, "method"?: ...}` (`snapshot` 불필요)
- **Response Payload (응답 구조)**: `{"answer", "snapshot", "mode", "sources", "usage"}`
  - `sources`: `{reports:[{...}], entities:[{...}], entities_total}`. 엔티티에 `provenance`(`cited`, `chunk`, `related`)가 붙어 제공되며, 프론트는 `entities[].title`로 Palace의 Room과 맵핑한다.
  - `usage`: 질의에 사용된 LLM 토큰 정보 (`{total_tokens, total_cost_usd, calls, by_model}`).

---

## Adding Domains (Curation Showcase)

새로운 도메인을 수동으로 인덱싱하고 Palace를 구축하는 과정이다.
(라이브 사용자 업로드는 이 수동 경로가 아니라 `orchestrator`가 자동 처리한다.)

```bash
# 1. 정제 및 전처리
python -m preprocessing.pipeline_v2 --pdf preprocessing/source/<domain>.pdf
python preprocessing/normalize.py --result preprocessing/result/<domain>_vN --domain <domain>

# 2. 인덱싱 (indexing/_template.settings.yaml 복사 및 수정 후)
graphrag index --root indexing/<domain>

# 3. Palace 및 Room 구축
python -m palace.run --config palace/configs/<domain>.json --phase toc   # LLM TOC 검토용
python -m palace.run --config palace/configs/<domain>.json --phase rooms # -> palace.json

# 4. 이미지 매칭
python -m palace.match_images --palace deliverables/<domain>/palace.json \
  --snapshot snapshots/<domain> \
  --figures-json preprocessing/result/<domain>_vN/meta/figures.json \
  --pagesplit preprocessing/result/<domain>_vN/txt/content_paged.txt \
  --out-dir deliverables/<domain>
```
> 마지막으로 `backend/showcase.py`의 `SHOWCASE_PALACES`와 `backend/serve.py`의 `SNAPSHOTS`에 도메인을 등록한다.

### Golden Verification
국사 도메인은 `assignment: chunk_overlap`으로 고정되어 골든 동작을 보존하며, 신규 도메인은 `fine_pos`가 기본값이다.
```bash
python -m palace.run --config palace/configs/korean_history.json --phase rooms
python palace/tests/compare_golden.py --run-id korean_history   # 캐시 히트 시 byte-identical
```

---

## Team & Contributions

이 프로젝트(회랑 GraphRAG 백엔드)는 4명의 팀원이 협력하여 개발했다.  
각 팀원의 구체적인 기여 내역 및 역할 분담은 **프론트엔드 레포지토리**의 `Team` 및 `Contributions` 섹션에서 자세히 확인할 수 있다.

- **Frontend Repository**: [Mindpalace_Microsoft9ai_Thirdprj-](https://github.com/PhrenO0/Mindpalace_Microsoft9ai_Thirdprj-)

---

## Documentation

- **전체 API 명세 (프론트 연동 정본)**: [docs/API.md](./docs/API.md)
- **정본 방 빌드 상세**: [palace/README.md](./palace/README.md)
- **재현 절차**: [docs/RUNBOOK.md](./docs/RUNBOOK.md)
- **실험 누적 Narrative**: [docs/EXPERIMENTS.md](./docs/EXPERIMENTS.md)
- **레포지토리 규약**: [docs/CONVENTIONS.md](./docs/CONVENTIONS.md)
