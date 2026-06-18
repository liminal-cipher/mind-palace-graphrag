# 퀴즈 모듈 (Quiz Module)

GraphRAG parquet 산출물로부터 **한국사 학습 퀴즈를 생성·채점**하는 모듈의 통합 문서다.
다른 개발자(및 그 Claude)가 이 모듈을 프로덕션에 통합할 때 맥락을 빠르게 공유하도록,
**현재 구현된 것**과 **앞으로 통합할 때 바뀔 것**을 함께 적는다.

> 이 문서는 이전의 `QUIZ_LOGIC.md`(생성 로직 상세)와 `퀴즈 설계서.md`(통합 설계)를 대체한다.

---

## 0. 한눈에 보기 (TL;DR)

- **무엇**: GraphRAG parquet(6종) → 통일된 "근거 후보" → 주제 관련도로 추림 → LLM 생성 →
  LLM 2차 검증 → (실패 시) 근거 기반 fallback. 그리고 그 결과를 **풀고 채점**하는 테스트 웹페이지.
- **두 부분**으로 나뉜다:
  1. **`quiz_generator.py`** — 순수 생성·검증 로직(웹/상태 없음). 안정적이고 재사용 가능.
  2. **`quiz_page.py` + `templates/`** — FastAPI 라우터 + Jinja2 서버 렌더링 **테스트 페이지**
     (생성·풀이·채점·근거 보기). "트랙 A"(최소 동작 확인용)다.
- **현재 상태**: 테스트 페이지는 **단일 스냅샷(`snapshots/repro_run3`)을 디스크에서 1회 로드**해
  동작한다. 프로덕션 통합("트랙 B": serve의 인메모리 dfs 재사용, 멀티 스냅샷, 503 게이트)은
  **아직 미구현**이며 §8에 통합 가이드를 둔다.
- **엔드포인트**: `GET /quiz`(폼) · `POST /quiz`(생성+렌더) · `POST /quiz/grade`(채점 JSON).
- **정답 은닉**: 정답은 클라이언트로 안 내려간다. 서버 메모리(`_SESSIONS`)에 `quiz_id`로 보관하고
  채점은 서버에서 한다. ⚠️ 단, **근거(evidence)는 출처 자료라 그대로 노출**된다(§6.4).

---

## 1. 파일/모듈 지도

```
graphrag/backend/
├── quiz_generator.py        # ① 생성·검증 순수 로직 (상태/HTTP 없음). Node 원본 server.js 포팅.
├── quiz_page.py             # ② FastAPI APIRouter: /quiz, /quiz/grade + 채점·은닉·근거 정리
├── templates/
│   ├── base.html            #    공통 셸(<head>·인라인 CSS·{% block body %}·{% block script %})
│   └── quiz.html            #    생성 폼 + (POST 시) 입력 UI·채점 JS·근거 서랍
├── app.py                   # ③ ASGI 조립: include_router(quiz_page.router) (serve '/' 캐치올 앞)
└── snapshots/repro_run3/    #    데이터: 6종 parquet (테스트 페이지가 디스크에서 직접 로드)

graphrag/docs/quiz.md        # (이 문서)
```

| 모듈 | 책임 | 상태/HTTP 의존 | 변경 빈도 |
|---|---|---|---|
| `quiz_generator.py` | parquet→후보, 선택/랭킹, LLM 생성·검증·fallback | 없음(순수) | 안정 |
| `quiz_page.py` | 라우팅, 정답 은닉/보관, 채점, 근거 표시 정리 | FastAPI/메모리 | 테스트용 |
| `templates/*.html` | 서버 렌더 UI + 채점/서랍 JS | — | 테스트용 |

> **핵심 분리 원칙**: 생성 로직(`quiz_generator`)은 웹·상태를 모른다. 웹/캐시/채점은
> `quiz_page`가 담당한다. 프로덕션 통합 시에도 `quiz_generator`는 거의 그대로 재사용한다.

---

## 2. 데이터 흐름 (생성 → 풀이 → 채점)

```
[브라우저] GET /quiz
   └─> quiz.html (빈 생성 폼)

[브라우저] POST /quiz (topic, count, quiz_types)
   │
   ▼ quiz_page.quiz_submit
   builder = EvidenceBuilder(snapshots/repro_run3)        # lazy, 최초 1회 디스크 로드
   selected = builder.select_candidates(topic, count)     # 근거 랭킹/샘플
   result   = await generate_quizzes(selected, ...)        # LLM 생성→검증→fallback
   │   result = {mode, quizzes[정답포함], evidence, reviews, warning?}
   │
   ├─ quiz_id = _store_quiz(result.quizzes)               # 정답 포함 원본을 _SESSIONS에 보관
   ├─ view_quizzes = 정답 필드 제거본                       # 마크업엔 정답 없음(은닉)
   ├─ evidence_view = 근거 text 정리(_clean_evidence_text) # [Data:...]·중요도 제거
   └─> quiz.html 렌더 (입력 UI + quiz_id + 근거 서랍)

[브라우저] "채점"/"전체 채점" 클릭 → JS가 답 수집 → POST /quiz/grade {quiz_id, answers}
   │
   ▼ quiz_page.quiz_grade
   quizzes = _SESSIONS[quiz_id]            # 없으면 404 (재시작/만료)
   제출된 문항만 _is_correct로 채점
   └─> {score, total, results:[{index, correct, answerText, explanation}]}
   │
   ▼ [브라우저] JS가 응답으로 정오·정답·해설·점수를 DOM에 표시
```

---

## 3. 생성 로직 — `quiz_generator.py`

웹/상태가 없는 순수 함수 묶음. **검색 후 생성(retrieve-then-generate)** + **생성·검증 분리**가
핵심이다. (Node.js `Quiz/server.js`에서 생성 로직만 떼어 포팅한 것.)

### 3.1 파이프라인

```
6개 parquet ─① load_rows/_normalize_value→ rawData(행 dict 배열)
            ─② EvidenceBuilder._build_candidates→ candidates[] (통일 후보)
            ─③ select_candidates→ selected[] (근거 묶음)
            ─④ build_quiz_prompt→ LLM(Azure OpenAI Responses)
            ─⑤ parse_json_object/normalize_quiz→ quizzes[]
            ─⑥ verify_quizzes→ 통과 문항 (LLM 2차 호출)
            ─⑦ 통과 0건이면 fallback_quizzes (근거 기반 단답형)
            → {mode, quizzes, evidence, reviews}
```

### 3.2 입력: 6개 parquet

| 파일 | 내용 | rawData 키 |
|---|---|---|
| `entities.parquet` | 개념/인물/사건 엔티티 | `entities` |
| `relationships.parquet` | 엔티티 간 관계 | `relationships` |
| `community_reports.parquet` | 주제 묶음 요약 + findings | `community_reports` |
| `documents.parquet` | 원문 문서 | `documents` |
| `text_units.parquet` | 문서를 쪼갠 텍스트 단위 | `text_units` |
| `communities.parquet` | 계층적 주제 묶음 | `communities` |

`load_rows`는 `pandas.read_parquet` → 행 dict 배열로 바꾸며 `_normalize_value`로 정규화한다
(numpy 스칼라→native, ndarray/리스트→list 재귀, NaN/NA→None).

### 3.3 통일 후보 스키마

6종 parquet 행은 모두 아래 형태로 통일된다(= `candidates[]` = `selected[]` 요소).

```python
{
  "kind":       "entity|relationship|finding|community_report|document|text_unit|community",
  "source":     "entities #12",      # 사람이 읽는 출처 라벨
  "title":      str,
  "topic":      str,                 # 분류/주제 라벨
  "answerSeed": str,                 # fallback 단답형 정답 시드
  "text":       str,                 # LLM 근거 본문 (compact 처리, kind별 메타 포함)
}
```
- `select_candidates` 통과분엔 `score`(랭킹 점수)가 추가로 붙는다(이후 무시).
- **`title`과 `text`가 모두 truthy인 후보만** 최종 유지.
- parquet→후보 변환 규칙(필드 매핑, `text_units`/`communities`의 id→이름 lookup,
  `community_reports`의 1행→리포트+findings N개 분기 등)은 `_build_candidates`에 구현돼 있다.
  `text`에는 `kind`별로 `빈도`/`연결 정도`/`가중치`/`중요도`/`[Data: ...]` 같은 **메타가 섞여
  들어간다** → 화면 표시 시 `quiz_page._clean_evidence_text`가 일부를 떼어낸다(§6.4).

### 3.4 근거 선택 — `EvidenceBuilder.select_candidates(topic, types, count)`

수백~수천 후보 중 **주제 관련 근거만 추려 LLM에 줄 묶음**을 만드는 랭킹/샘플러.

1. `tokenize(topic)`: 소문자화·문장부호 제거·공백 분리·**한국어 조사 제거**(원형+제거형 둘 다)·
   2글자 미만/불용어(`퀴즈/문제/생성/한국사…`) 제외.
2. `types`로 `kind` 필터(미지정 시 7종 전부).
3. `score_candidate`: `title` 포함 +8, `topic` +4, 전체(haystack) +1 누적.
   **토큰이 하나도 없으면 점수 대신 `random.random()`** → 주제 미지정이면 전체 무작위.
4. 토큰이 있으면 `score>0`만 유지 → 점수 내림차순 정렬.
5. 상위 `max(count*4, 20)`개로 1차 풀 좁힘 → `pick_many`로 `max(count*2, 12)`개 **무작위 추출**.

> 의도: 관련도 상위로 좁히되 내부에서 랜덤 추출 → 같은 주제라도 매번 다른 조합. `count*2`로
> 넉넉히 뽑는 건 이후 검증에서 일부 탈락해도 문항 수를 확보하기 위함.

### 3.5 퀴즈 생성 — `await generate_quizzes(selected, *, count, quiz_types, topic)`

- 파라미터 정규화: `count` 1~20 clamp, `quiz_types` 기본 3종, `topic` trim.
- `build_quiz_prompt`: 근거를 `[n] kind | source | title\n text`로 나열, 유형/개수/주제 지시,
  "**근거에서 확인되는 사실만 사용**", JSON 외 출력 금지.
- `call_llm`: **Azure OpenAI Responses API**(`/openai/responses`)에 `httpx`로 POST.
  URL 조립 `get_azure_responses_url`, 응답 추출 `extract_response_text`.
- `parse_json_object` → `normalize_quiz`(문항당): `type` 화이트리스트, `choices`/`answerIndex`
  정리, **4지선다 보기 셔플 + 정답 index 재계산**, 고유 `id` 부여, 빈 `question` 제거.
- `verify_quizzes`: **2차 LLM 호출**로 근거 대조 채점(pass/fail + `safeExplanation`).
  **pass 문항만** 채택, `safeExplanation` 있으면 해설 교체.
- `fallback_quizzes`: LLM 실패/파싱 실패/**검증 0건**이면 LLM 없이 근거로 단답형 생성.

#### 생성 결과(응답) 형태
```python
# 정상
{ "mode": "llm_verified", "quizzes": [...], "evidence": selected, "reviews": [...] }
# 대체(검증 0건 또는 오류) — 이것도 정상 200, 프론트는 mode로 배지 표시
{ "mode": "fallback", "warning": "...", "quizzes": [...], "evidence": selected, "reviews"?: [...] }
```

#### 문항 스키마 (`normalize_quiz` 출력)
```python
{
  "id": "q-{timestamp}-{i}", "type": "multiple_choice|true_false|short_answer",
  "difficulty": "medium", "question": str,
  "choices": list[str],   # 단답형은 []
  "answerIndex": int,     # 단답형은 의미 없음 / 객관식·OX는 정답 보기 인덱스
  "answerText": str, "explanation": str,
  "sourceIds": list[str], # 사용한 근거 번호 (추적성)
}
```

### 3.6 공개 API 요약

```python
from backend.quiz_generator import EvidenceBuilder, generate_quizzes

builder = EvidenceBuilder("snapshots/repro_run3")              # 디스크 로드 (현재 유일 경로)
selected = builder.select_candidates(topic="조선 건국", count=10)
result   = await generate_quizzes(selected, count=10, topic="조선 건국")
```
- `EvidenceBuilder.__init__(self, data_dir=".")` — **현재는 디스크 경로 로드만** 지원.
  (프로덕션 통합 시 인메모리 dfs 주입 경로 `raw=`를 추가할 예정 — §8.2. **아직 미구현**.)

### 3.7 환경변수 (LLM)

`call_llm`이 읽는 4개. 누락/오설정이면 호출이 실패해 **조용히 `fallback`(단답형)으로 떨어진다**
(에러가 200 응답의 `warning`으로 흡수되므로 눈치채기 어렵다).

```
AZURE_OPENAI_API_KEY        AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_API_VERSION    AZURE_OPENAI_DEPLOYMENT
```
- `ENDPOINT`가 base URL이면 `get_azure_responses_url`이 `/openai/responses?api-version=…`를
  자동 부착한다.
- ⚠️ `AZURE_OPENAI_DEPLOYMENT`가 실재 배포명이 아니면 404 → 전부 fallback. 스모크 테스트에서
  `mode=="llm_verified"`가 나오는지로 검증할 것.

---

## 4. 테스트 페이지 라우터 — `quiz_page.py`

`quiz_generator`를 호출해 **form 제출만으로** 생성·풀이·채점이 되는 서버 렌더링 페이지.
`serve.py`/`query.py`/`quiz_generator.py`는 건드리지 않는다.

### 4.1 엔드포인트

| 메서드/경로 | 입력 | 출력 | 설명 |
|---|---|---|---|
| `GET /quiz` | — | HTML | 빈 생성 폼 |
| `POST /quiz` | Form: `topic`, `count`, `quiz_types[]` | HTML | 생성 + 입력 UI + 근거 서랍 렌더 |
| `POST /quiz/grade` | JSON: `{quiz_id, answers}` | JSON | 제출 문항 채점 결과 |

- 라우터는 [app.py](../backend/app.py)에서 `app.include_router(quiz_page.router)`로 조립되며,
  **serve의 `app.mount("/", serve_app)` 캐치올보다 앞**에 등록돼야 `/quiz`가 먼저 매칭된다
  (showcase 라우터 옆).

### 4.2 빌더 로딩 (lazy)

```python
_builder = None
def _get_builder():           # 첫 POST /quiz 때 1회만 디스크 로드 → 부팅 비차단
    global _builder
    if _builder is None:
        _builder = EvidenceBuilder(SNAPSHOT_DIR)   # snapshots/repro_run3 고정
    return _builder
```
- **현재는 단일 스냅샷 고정**(멀티 스냅샷/스냅샷 파라미터 없음 — 트랙 B에서 도입).
- 테스트용이라 캐시 락/503 warmup 게이트는 생략.

---

## 5. 채점과 정답 은닉 (저장 방식)

### 5.1 정답은 어디에 저장되나 — `_SESSIONS` (프로세스 메모리)

```python
_SESSIONS: dict[str, list[dict]] = {}   # quiz_id(uuid) -> 퀴즈 리스트(정답 포함)
_SESSIONS_MAX = 50
```
- **DB·파일이 아니라 서버 프로세스 RAM의 `dict`**. 생성된 퀴즈 **전체**(정답
  `answerIndex`/`answerText`/`explanation` 포함)를 `quiz_id`로 보관한다.
- 클라이언트엔 **`quiz_id`만** 내려간다(정답 미전송). 채점 때 `quiz_id`+사용자답을 받아 서버가
  `_SESSIONS[quiz_id]`에서 정답을 꺼내 대조한다.
- 용량: 최근 50개만 **삽입 순서 FIFO**로 유지(`_store_quiz`).
- **성격(테스트용 단순함)**:
  - 휘발성 — 서버 재시작 시 전부 소실 → 그 전 생성분은 채점 시 **404**.
  - 프로세스 종속 — 멀티 워커면 다른 워커엔 그 `quiz_id`가 없음(app.py 단일 워커 전제라 현재 OK).
  - 만료는 시간이 아니라 개수(50) 초과 시 폐기.
  > 프로덕션에선 Redis/서명 토큰(정답 해시) 등으로 교체 여지(§8.4).

### 5.2 렌더 시 정답 제거 (은닉)

`POST /quiz`는 두 가지 뷰를 만든다.
- `_store_quiz(quizzes)` → `quiz_id` (정답 포함 원본은 `_SESSIONS`에).
- `view_quizzes` = `_ANSWER_KEYS`(`answerIndex/answerText/explanation/sourceIds`)를 **제거한 뷰**
  → 템플릿엔 이것만 넘겨 **페이지 소스에도 정답이 없다**.

### 5.3 채점 규칙 — `_is_correct(quiz, user_answer)`

- 빈 답 → 오답.
- **단답형: 느슨 매칭(Quiz 방식)** — `user.strip() in answerText`(부분 문자열이면 정답).
  예: 정답 "태조 이성계"에 "이성계"만 입력해도 정답.
- 객관식/OX: `int(user_answer) == answerIndex`(제출값은 보기 인덱스).

### 5.4 채점 라우트 — `POST /quiz/grade`

```python
class GradeRequest(BaseModel):
    quiz_id: str
    answers: dict[str, str] = {}     # {"문항 index": "보기 index 또는 단답 텍스트"}
```
- `quiz_id` 미존재/만료 → **404**.
- **제출된 문항(`answers`의 키)만** 순회해 채점·공개한다. → `answers` 1개면 **문제별 채점**,
  N개면 **전체 채점**. 같은 라우트가 둘 다 처리하며 **안 푼 문제의 정답은 응답에 안 실려** 은닉 유지.
- 응답: `{ "score": 맞은수, "total": 채점한수, "results": [{index, correct, answerText, explanation}] }`.

---

## 6. 프론트엔드 (templates + 인라인 JS)

브라우저 JS를 쓴다(원래 "JS 0줄" 목표는 **정답 은닉 + 매끄러운 AJAX 채점**을 위해 의도적으로 포기).
JS는 **채점하지 않고**(비교는 서버), 서버 응답을 DOM에 **표시만** 한다.

### 6.1 템플릿 구조

- `base.html`: `<head>` + 인라인 `<style>`(폼·퀴즈 카드·`.opts/.opt`·`.r-ok/.r-no`·근거 서랍 CSS)
  + `{% block body %}` + `{% block script %}`.
- `quiz.html`: `base.html` 상속. GET/POST 공통 생성 폼 + `{% if result %}` 결과(입력 UI·채점
  버튼·근거 서랍) + `{% block script %}` 인라인 채점/서랍 JS. (별도 `app.js` 서빙 없음 — 정적
  마운트가 없어 인라인이 가장 단순.)

### 6.2 입력 UI / 문제별·전체 채점

- 객관식/OX: `.opts/.opt` + `<input type="radio" name="q{qi}" value="{보기 index}">`.
- 단답형: `<input type="text" class="short-answer">`.
- 각 문항에 **"채점" 버튼**(`.check-btn`) → 그 문항 1개만 `/quiz/grade`로 보냄.
- 하단 **"전체 채점"**(`#grade-btn`) → 모든 문항을 한 번에 보냄.
- 정답/해설(`.ans`/`.explain`)은 `hidden`, 채점 응답이 오면 JS가 채워 공개.
- 점수(`#score`)는 응답 숫자가 아니라 **DOM의 채점된 카드(`.r-ok`/`.r-no`)를 세어** 갱신 →
  문제별·전체를 섞어도 "맞음 / 채점함"이 일관.
- 컨테이너 `#quiz-set[data-quiz-id]`에 `quiz_id` 보관, 각 카드 `data-qi`(문항 index)/`data-type`.

### 6.3 근거 서랍 (Evidence drawer)

- 화면 오른쪽 가장자리 `«` 탭(`#evi-toggle`) → 클릭 시 `#evi-drawer`가 `translateX`로 슬라이드.
  열리면 `»`로 토글, 탭도 패널 왼쪽 가장자리로 이동. JS는 `.open` 클래스/ARIA만 토글.
- 패널 콘텐츠(근거 카드: 번호·`source`·`title`·`kind·topic`·`text`)는 **서버가 Jinja로 렌더**.

### 6.4 ⚠️ 근거 노출 트레이드오프

- 근거는 정답 필드가 아니라 **출처 자료**라 Quiz처럼 **그대로 노출**한다(정답 은닉과 별개 축).
  채점 정답·해설은 여전히 채점 후에만 공개되지만, **근거 본문에서 답이 유추될 수 있다**.
- 표시 전 `_clean_evidence_text`로 **GraphRAG 인용 마커 `[Data: Entities (2); …]`와
  `중요도: 8.5` 메타를 제거**하고 잔여 구두점/공백을 정리한다(생성/채점엔 영향 없음, 표시용).

---

## 7. 실행 / 스모크 테스트

```bash
# (예시) backend 앱 실행 후
#   GET  http://localhost:8000/quiz                      → 생성 폼
#   POST http://localhost:8000/quiz  (form)              → 생성+렌더
#   POST http://localhost:8000/quiz/grade (json)         → 채점

curl -s -X POST localhost:8000/quiz/grade \
  -H 'Content-Type: application/json' \
  -d '{"quiz_id":"<생성응답의 quiz_id>","answers":{"0":"2","1":"이성계"}}'
```
- 생성이 `mode=llm_verified`로 나오는지 확인(아니면 §3.7 LLM 환경변수/배포명 점검).
- 채점이 404면 `quiz_id`가 만료(서버 재시작/50개 초과)됐을 가능성 — 다시 생성.

---

## 8. 프로덕션 통합 가이드 (트랙 B — 아직 미구현)

테스트 페이지(트랙 A)를 정식 제품으로 올릴 때의 방향. **여기 항목들은 현재 코드에 없다.**

### 8.1 데이터: serve의 인메모리 dfs 재사용 (RAM 중복 방지)

- 현재: `quiz_page`가 `EvidenceBuilder(SNAPSHOT_DIR)`로 **디스크에서 직접** 6 parquet 로드.
- 목표: serve가 warmup 때 이미 메모리에 올린 `st.engine.dfs`를 재사용 → **parquet이 RAM에
  2벌 올라가는 것 방지**(app.py 단일 워커·RAM 절약 전제와 정합).
- 방법: `quiz_service.py`가 `from backend.serve import STATE, SNAPSHOTS, _resolve_key` 임포트.

### 8.2 `EvidenceBuilder`에 `raw=` 주입 경로 추가 (quiz_generator 소폭 수정)

```python
def __init__(self, data_dir=None, *, raw=None):
    if raw is not None:
        self.raw = raw                 # serve dfs에서 변환해 주입 (인메모리)
    else:
        ... 기존 디스크 로드 ...        # 스크립트/테스트 하위 호환
```
- DataFrame → 행 변환은 `quiz_generator._normalize_value`와 동일 정규화를 거쳐야 한다
  (`rows_from_df(df) = [{k: _normalize_value(v) ...} for rec in df.to_dict("records")]`).

### 8.3 변환 캐시 + 멀티 스냅샷 + 503 게이트

- `get_builder(run_id)`: serve dfs → 후보 변환을 **run_id별 1회만** 수행·캐시
  (`_BUILDERS: dict[str, EvidenceBuilder]`), run_id별 `asyncio.Lock`으로 동시 첫 요청 직렬화.
- warmup 미완료(`st.ready`/`st.engine` 없음)면 **503**(serve `/ready`와 같은 게이트).
- 요청에 `snapshot` 파라미터(run_id/alias) 추가, `_resolve_key`로 정규화, 미등록 키 404.

### 8.4 정답 보관 교체

- `_SESSIONS`(인메모리·휘발·프로세스 종속) → 멀티 워커/영속이 필요하면 **Redis**나 **서명 토큰**
  (정답 해시를 클라에 주되 위변조 방지)으로 교체.

### 8.5 라우터/모듈 분리

- 로직(`quiz_generator`) ↔ 서비스(`quiz_service.py`: 캐시·HTTP·채점) 분리, showcase처럼 독립
  `APIRouter`를 app.py에서 `include_router`로 조립.

---

## 9. ⚠️ 통합 시 반드시 알아야 할 주의점

1. **`/quiz` 경로 충돌 (가장 중요).** 현재 테스트 페이지가 **`POST /quiz`(HTML form)** 를
   점유한다. 프로덕션 설계는 같은 **`POST /quiz`를 JSON API**로 쓰려 했다 → 트랙 B의
   `quiz_service.py`를 붙이면 **두 핸들러가 충돌**한다. 통합 착수 시 **둘 중 하나를 옮겨야 한다**:
   테스트 페이지를 `/quiz/ui`로, 또는 프로덕션 JSON을 `/api/quiz`로. (지금은 테스트 페이지만
   있어 충돌 없음 — 결정은 트랙 B 시작 시점에.)

2. **정답 은닉 ⇒ 서버 채점은 필수.** 정답을 클라에 안 내리는 한 채점은 서버에서만 가능하다.
   클라이언트 채점으로 바꾸면(정답을 DOM에 내려보내면) `_SESSIONS`/`/quiz/grade`가 불필요해지지만
   **정답이 개발자도구로 노출**된다. 현재는 은닉을 택했다.

3. **`_SESSIONS`는 휘발성.** 서버 재시작·50개 초과 시 `quiz_id`가 사라져 채점이 404. 데모 중
   서버를 재시작하면 기존 화면의 채점이 깨진다(§5.1).

4. **LLM 실패가 조용히 fallback으로 흡수된다.** 환경변수/배포명 오설정 시 에러가 200의
   `warning`으로 흡수되고 단답형으로 떨어진다 → `mode`로 반드시 확인(§3.7).

5. **근거는 노출된다.** 정답 은닉과 달리 근거(evidence)는 그대로 보인다 → 근거 본문에서 답이
   유추될 수 있음(§6.4). 표시 정리(`_clean_evidence_text`)는 가독성용일 뿐 은닉이 아니다.

6. **단답형 채점은 느슨(부분 문자열).** "이성계"가 "태조 이성계"에 매칭된다(§5.3). 더 엄격히
   하려면 `_is_correct`를 정규화 완전일치 등으로 바꾼다.

7. **단일 스냅샷 고정.** 테스트 페이지는 `snapshots/repro_run3`만 본다. 멀티 스냅샷은 트랙 B(§8.3).
