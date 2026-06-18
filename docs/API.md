# 회랑 백엔드 API 명세

프론트(3D 뷰어 + 채팅/업로드 패널)가 붙는 HTTP API. 통합 FastAPI 앱 `backend.app:app` 하나가 전부 서빙한다.

- **베이스 URL(현재 배포)**: `https://3d-mindpalace-ai-backend-h3gze8h7hfhqg3h8.canadacentral-01.azurewebsites.net`
- **CORS**: 개방(GET, POST). 프론트 JS가 직접 호출.
- 응답은 별도 표기 없으면 JSON.

## 마운트 구조 (먼저 읽을 것)

앱은 세 부분이 한 주소에 얹혀 있다:

- `serve` → 루트 `/` : RAG 질의(`/query`, `/jobs/{id}/query`), 헬스(`/health`, `/ready`)
- `showcase` 라우터 → 루트 `/` : `/palace/{name}`, `/images/{name}/{file}`
- `orchestrator` → **`/orchestrator`** prefix : 업로드, 잡 상태/팰리스/목차/이미지

> ⚠️ **함정**: 잡 상태/팰리스/목차/이미지는 `/orchestrator/jobs/{id}/...` 인데, **라이브 RAG 질의만 prefix 없는 루트 `/jobs/{id}/query`** 다(serve 소관). `/orchestrator/jobs/{id}/query` 아님.

## 공통 규칙 (프론트 필수)

- **노드 이미지 → URL**: 팰리스 노드의 `images[].path`는 쇼케이스·라이브 모두 `images/<파일>` 형식. 서빙 URL은 출처별로 조립:
  - 쇼케이스: `/images/{name}/<파일>` (예: `images/fig_10_2.png` → `/images/korean_history/fig_10_2.png`)
  - 라이브 잡: `/orchestrator/jobs/{id}/images/<파일>`
  - 둘 다 `<파일>`(basename)만 떼어 각 base에 붙인다. 없는 이미지는 404 → 조용히 스킵.
- **게이팅**(잡 status 플래그): `toc_ready=true` → `/toc` 가능, `palace_ready=true` → `/palace` 가능, `rag_ready=true`(=DONE) → `/jobs/{id}/query` 가능.
- **로딩바**: status의 `progress` 사용(아래 스키마).
- **업로드 상한**: 본문 30MB 초과 → `413`(`ORCH_MAX_UPLOAD_MB`로 조정).

자동 생성 인터랙티브 문서도 있다(보조용): `/docs`·`/openapi.json`(serve), `/orchestrator/docs`·`/orchestrator/openapi.json`. 단 dict 반환 엔드포인트(status·progress·sources)와 마운트 함정은 안 잡히니, 이 문서가 정본이다.

---

## 헬스 / 준비

### `GET /health`
serve 헬스. **항상 200**(콜드 시작에 헬스 프로브가 컨테이너를 죽이지 않게). 본문에 스냅샷별 warm 상태.
```json
{"status": "ok", "method": "global", "aliases": {}, "snapshots": {"korean_history": {"status": "ok", "ready": true, "snapshot_dir": "snapshots/repro_run3"}, "statistics": {"status": "ok", "ready": true}}}
```
- `status`: 하나라도 ready면 `ok`, 전부 아니면 `warming`.

### `GET /ready`
준비 게이트. `/health`와 달리 **준비 안 됐으면 `503`**(warm/poll·게이팅용).
- 파라미터 없음: 등록 스냅샷이 전부 ready면 200, 아니면 503.
```json
{"ready": true, "snapshots": {"korean_history": {"status": "ok", "ready": true, "warmup_seconds": 0.9, "synthesis_model": "gpt-5.4-mini"}, "statistics": {"status": "ok", "ready": true}}}
```
- `?snapshot=<키>`: 그 키 하나만 게이팅 → 200/503, 응답 `{ready, snapshot, detail}`. 미등록 키면 `404`.

### `GET /orchestrator/health`
오케스트레이터(업로드/잡 워커) 헬스.
```json
{"status": "ok", "worker_alive": true}
```

---

## 쇼케이스 (미리 만든 국사·통계)

### `GET /palace/{name}`
프리베이크 팰리스 JSON(그림 포함, `palace_with_images.json`). `name`: `korean_history` | `statistics`.
- 200: 팰리스 JSON(맨 위 `image_matching`, 방마다 `kept`/`demoted` 노드, 노드에 `images[]`).
- 404: 미등록 이름.

### `GET /images/{name}/{filename}`
쇼케이스 팰리스가 참조하는 그림(PNG).
- 200: `image/png` 바이트. 404: 없음.

---

## RAG 질의 (채팅)

답변 모델 `gpt-5.4-mini`. 기본 global, `method="auto"`면 라우터가 local/global/basic 선택.

### `POST /query` (쇼케이스/등록 스냅샷)
요청 body:
```json
{"question": "조선 전기의 통치 제도를 설명해줘.", "snapshot": "korean_history", "method": "auto"}
```
- `snapshot`(필수): 등록 키(`korean_history`/`statistics` 또는 라이브 `job_id`/alias). 누락/미등록 시 `400`.
- `method`(선택): `auto`(기본) | `local` | `global` | `basic`.
- 스냅샷 warm 전이면 `503`.

응답:
```json
{"answer": "...[Data: Reports (0, 2)]", "snapshot": "korean_history", "mode": "global", "sources": { ... }}
```
`sources` 스키마는 아래 부록 참고(인용 없으면 `null`).

### `POST /jobs/{job_id}/query` (라이브 잡) — 루트 경로 주의
요청 body:
```json
{"question": "...", "method": "auto"}
```
- `snapshot` 불필요(`job_id`가 path). `rag_ready=true`(DONE) 후 가능.
- 응답: `/query`와 동일(`{answer, snapshot, mode, sources}`, `snapshot`=job_id).

---

## 라이브 업로드 & 잡

### `POST /orchestrator/upload?filename=&domain=`
파일을 raw 본문으로 업로드 → 백그라운드 파이프라인 시작.
- 쿼리: `filename`(확장자로 PDF/txt 판별), `domain`(라벨, 스냅샷 선택엔 무관), `showcase`(선택, 프리베이크 키).
- 본문: 파일 바이트 그대로(`Content-Type: application/pdf` 등). multipart 아님.
- 201:
```json
{"job_id": "f2d51bcc...", "state": "QUEUED"}
```
- `413`: 30MB 초과. `422`: 빈 본문 / 미지원 showcase 키.

### `GET /orchestrator/jobs/{job_id}/status`
폴링(2~3초 권장).
```json
{"job_id": "...", "state": "INDEXING", "toc_ready": true, "palace_ready": false, "rag_ready": false,
 "domain": "통계 기초 ...", "showcase_key": null, "run_id": "...", "error": null,
 "created_at": "...", "updated_at": "...",
 "progress": {"percent": 25, "current_step": "indexing",
   "steps": [{"key": "preprocess", "label": "전처리", "weight": 25, "est_seconds": 90, "status": "done"},
             {"key": "indexing", "label": "인덱싱", "weight": 55, "est_seconds": 280, "status": "active"},
             {"key": "rooms", "label": "방 생성", "weight": 20, "est_seconds": 60, "status": "pending"}]}}
```
- `state`: `QUEUED → PREPROCESSING → TOC_READY → INDEXING → BUILDING_PALACE → PALACE_READY → DONE`(실패 시 `FAILED`, `error`에 사유). `RAG_READY`는 DONE 직전 순간.
- 404: 없는 잡.

### `GET /orchestrator/jobs/{job_id}/toc`
방 생성 전 목차 미리보기(인덱싱과 분리돼 먼저 나옴).
- 200: LLM 목차 JSON `{"meta": {...}, "sections": [{"idx", "name", "start_marker", "start_offset", ...}]}`.
- `409`: `toc_ready` 아직 아님. 404: 없는 잡.

### `GET /orchestrator/jobs/{job_id}/palace`
산출 팰리스. 이미지 매칭됐으면 노드에 `images[]` 포함(없으면 텍스트 팰리스).
- 200: 팰리스 JSON(`/palace/{name}`과 동형 + 라이브 잡 키).
- `409`: `palace_ready` 아직 아님. 404: 없는 잡.

### `GET /orchestrator/jobs/{job_id}/images/{filename}`
라이브 잡이 매칭한 그림(PNG).
- 200: `image/png`. 404: 없음. 400: 경로 traversal 차단.

---

## 퀴즈 (테스트 페이지)

GraphRAG parquet로 한국사 학습 퀴즈 생성 + 서버 채점.

### `GET /quiz`
퀴즈 생성 폼(HTML).

### `POST /quiz` (form-encoded)
- 필드: `topic`(str), `count`(int, 기본 10), `quiz_types`(반복 필드: `multiple_choice`/`true_false`/`short_answer`).
- 응답: 생성 결과 HTML(정답은 마크업에 없음, `quiz_id`만 노출). LLM 검증 실패 시 단답형 fallback.

### `POST /quiz/grade` (JSON)
```json
{"quiz_id": "51dc779c...", "answers": {"0": "2", "1": "0", "2": "정답텍스트"}}
```
- 서버가 보관한(`quiz_id`) 정답과 대조. **제출한 문항만** 채점·반환(안 푼 문항 정답은 은닉 유지).
- 응답: `{"score": 2, "total": 3, "results": [{"index": 0, "correct": true, "answerText": "...", "explanation": "..."}]}`. (`total`=채점된 문항 수.)
- `404`: 만료/미존재 `quiz_id`(서버 재시작 시 세션 소실).

---

## 부록: 스키마

### `sources` (RAG 응답)
답변 인용을 엔티티(노드)로 변환한 근거. 라우터 모드에 따라 인용 종류가 다르며, 각 엔티티에 `provenance`가 붙는다.
```json
{
  "reports": [{"id": "3", "title": "상관분석과 상관계수 중심 통계교육 커뮤니티"}],
  "entities": [{"id": 36, "title": "상관계수", "type": "CORRELATION COEFFICIENT", "degree": 7,
                "description": "...", "provenance": "related"}],
  "entities_total": 20
}
```
- `provenance`: `cited`(local — 답변이 직접 인용한 엔티티/관계, **정확**) · `chunk`(basic — 인용 청크의 엔티티) · `related`(global — 인용 커뮤니티 구성 개념 degree 상위, **근사**).
- `cited` 우선 정렬, degree 순, 상위 N(`RAG_SOURCE_MAX_ENTITIES`, 기본 12)까지. `reports`는 실제 인용된 커뮤니티 리포트(global). 인용 없으면 `sources=null`.
- 프론트는 `entities[].title`로 팰리스 노드와 잇는다("관련 방").

### `progress` (status 응답)
- `percent`: 완료 단계 가중치 합(서버는 단계 **내부** 진행률 모름).
- `current_step`: 진행 중 단계 key(`preprocess`/`indexing`/`rooms`) 또는 `null`.
- `steps[].status`: `pending` | `active` | `done` | `failed`.
- 긴 `active` 단계(인덱싱)는 프론트가 `est_seconds` + `updated_at`(그 state 진입 시각)으로 보간해 바를 움직인다.

### 팰리스 노드 `images[]`
```json
{"path": "images/fig_5_3.png", "caption": "...", "score": 0.62}
```
- `path`는 `images/<파일>` 형식. URL 조립은 위 "공통 규칙" 참고.

---

## 내부 전용 (외부 호출 금지)
- `POST /snapshots/register`: 오케스트레이터→serve 내부 등록(127.0.0.1 전제). 프론트에서 쓰지 않는다.
