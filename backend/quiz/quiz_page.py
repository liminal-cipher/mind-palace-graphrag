"""퀴즈 테스트 페이지 (트랙 A: 서버 렌더링 + AJAX 채점).

모듈 전체 문서는 `docs/quiz.md` 참조. quiz_generator의 EvidenceBuilder + generate_quizzes 를
그대로 호출해 form 제출만으로 퀴즈를 만들고, 사용자 풀이를 받아 채점한다.
기존 코드(serve/query)는 건드리지 않는다.

렌더는 Jinja2(`templates/`)로 한다. HTML은 이 모듈 인라인 문자열이 아니라 별도
템플릿 파일이며, 값 주입/escape 는 Jinja2가 처리한다(수동 html.escape 불필요):
  templates/base.html  -> 공통 셸(<head>·CSS·{% block script %})
  templates/quiz.html  -> form + (POST면) 입력 UI·채점 fetch JS. result 유무로 분기.

배선: app.py 에서 `include_router(quiz_page.router)` (serve mount('/') 앞).
  GET  /quiz       -> 입력 form
  POST /quiz       -> 퀴즈 생성 결과 HTML(정답은 마크업에 미포함, quiz_id만 노출)
  POST /quiz/grade -> quiz_id + 사용자답 -> 서버 채점 결과 JSON (docs/quiz.md §5)

채점은 서버에서 한다(정답 은닉). 정답 포함 원본은 `_SESSIONS`(프로세스 메모리)에
quiz_id로 보관하고 클라엔 quiz_id만 내려간다. 매끄러운 "전체 채점"을 위해 JS(fetch)를
쓰며, JS는 비교가 아니라 서버 응답 표시만 한다. 빌더는 앱 부팅을 막지 않도록 첫 요청 때
lazy로 한 번만 로드한다(테스트라 캐시/락/503 게이트는 생략).
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from backend.quiz.quiz_generator import EvidenceBuilder, generate_quizzes

ROOT = Path(__file__).resolve().parents[2]  # backend/quiz/ -> repo root
SNAPSHOT_DIR = ROOT / "snapshots" / "korean_history"

TYPE_LABELS = {
    "multiple_choice": "객관식",
    "true_false": "OX",
    "short_answer": "단답형",
}

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

router = APIRouter()

_builder: EvidenceBuilder | None = None

# 생성한 퀴즈(정답 포함)를 채점 때까지 서버 메모리에 보관한다. 클라이언트엔 quiz_id만
# 넘겨 정답 노출을 막는다. 테스트용이라 최근 _SESSIONS_MAX개만 유지(삽입 순서로 폐기).
_SESSIONS: dict[str, list[dict]] = {}
_SESSIONS_MAX = 50


def _get_builder() -> EvidenceBuilder:
    """첫 요청 때 한 번만 빌더를 만든다(부팅 비차단, 디스크 1회 로드)."""
    global _builder
    if _builder is None:
        _builder = EvidenceBuilder(SNAPSHOT_DIR)
    return _builder


def _store_quiz(quizzes: list[dict]) -> str:
    """채점용으로 퀴즈를 보관하고 quiz_id를 돌려준다.

    RAM(_SESSIONS) 보관에 더해 Cosmos(quiz_sessions)에도 best-effort 로 영속한다 —
    serve 재시작/재배포 뒤에도 채점이 되도록(미설정/오류는 조용히 무시, RAM 채점엔 영향 0).
    """
    quiz_id = uuid.uuid4().hex
    _SESSIONS[quiz_id] = quizzes
    while len(_SESSIONS) > _SESSIONS_MAX:
        del _SESSIONS[next(iter(_SESSIONS))]
    from backend.quiz import quiz_store
    quiz_store.save_session(quiz_id, quizzes)
    return quiz_id


def _is_correct(quiz: dict, user_answer: object) -> bool:
    if user_answer is None or str(user_answer).strip() == "":
        return False
    if quiz.get("type") == "short_answer":
        # 느슨 매칭(Quiz 방식): 입력(trim)이 정답 문자열의 부분 문자열이면 정답.
        user = str(user_answer).strip()
        return user in str(quiz.get("answerText") or "")
    try:  # 객관식 / OX: 제출값은 보기 인덱스
        return int(user_answer) == quiz.get("answerIndex")
    except (TypeError, ValueError):
        return False


class GradeRequest(BaseModel):
    quiz_id: str
    answers: dict[str, str] = {}   # {"문항 index": "보기 index 또는 단답 텍스트"}


# 렌더 시 정답을 마크업에서 제외하기 위해 떼어내는 키(서버 은닉).
_ANSWER_KEYS = ("answerIndex", "answerText", "explanation", "sourceIds")


def _clean_evidence_text(text: object) -> str:
    """근거 표시용 정리: GraphRAG 인용 마커(`[Data: ...]`)와 `중요도: N` 메타를 제거."""
    s = str(text or "")
    s = re.sub(r"\[Data:[^\]]*\]", "", s)                 # [Data: Entities (2); ...]
    s = re.sub(r"중요도:\s*[0-9]+(?:\.[0-9]+)?\.?", "", s)  # 중요도: 8.5
    s = re.sub(r"\s+([.;,])", r"\1", s)                   # 구두점 앞 공백 제거
    s = re.sub(r"([.;,])\s*(?=[.;,])", "", s)             # 연속 구두점 정리
    s = re.sub(r"^[\s.;,]+", "", s)                       # 앞쪽 잔여 구두점
    return re.sub(r"\s{2,}", " ", s).strip()


# --- 라우트 ------------------------------------------------------------------

@router.get("/quiz", response_class=HTMLResponse)
async def quiz_form(request: Request):
    return templates.TemplateResponse(
        request,
        "quiz.html",
        {
            "topic": "",
            "count": 10,
            "type_labels": TYPE_LABELS,
            "selected_types": list(TYPE_LABELS),  # 최초엔 3종 모두 체크
            "result": None,
        },
    )


@router.post("/quiz", response_class=HTMLResponse)
async def quiz_submit(
    request: Request,
    topic: str = Form(""),
    count: int = Form(10),
    quiz_types: list[str] = Form([]),
):
    builder = _get_builder()
    selected = builder.select_candidates(topic=topic, count=count)
    result = await generate_quizzes(
        selected, count=count, quiz_types=quiz_types or None, topic=topic,
    )

    # 정답 포함 원본은 서버 메모리에 보관(채점용), 클라엔 quiz_id만 내려간다.
    quizzes = result.get("quizzes") or []
    quiz_id = _store_quiz(quizzes) if quizzes else None
    # 렌더용 뷰는 정답 필드를 떼어내 마크업/페이지 소스에 정답이 안 남게 한다.
    view_quizzes = [
        {k: v for k, v in quiz.items() if k not in _ANSWER_KEYS} for quiz in quizzes
    ]
    # 근거(선택된 후보)는 정답이 아니라 출처 자료라 Quiz처럼 그대로 노출한다(서랍 패널).
    # text는 인용 마커/중요도 메타를 떼어내 표시용으로 정리한다.
    evidence_view = [
        {
            "kind": ev.get("kind"),
            "source": ev.get("source"),
            "title": ev.get("title"),
            "topic": ev.get("topic"),
            "text": _clean_evidence_text(ev.get("text")),
        }
        for ev in (result.get("evidence") or [])
    ]

    return templates.TemplateResponse(
        request,
        "quiz.html",
        {
            "topic": topic,
            "count": count,
            "type_labels": TYPE_LABELS,
            "selected_types": quiz_types or list(TYPE_LABELS),
            "result": {
                "mode_ok": result.get("mode") == "llm_verified",
                "warning": result.get("warning"),
                "quiz_id": quiz_id,
                "quizzes": view_quizzes,
                "evidence": evidence_view,
            },
        },
    )


@router.post("/quiz/grade")
async def quiz_grade(req: GradeRequest):
    """quiz_id로 보관된 정답과 사용자답을 서버에서 대조해 채점 결과만 돌려준다.

    **제출된 문항만** 채점·공개한다. 문제별 채점(answers에 1개)도 전체 채점(answers에 N개)도
    같은 라우트로 처리되며, 응답에 안 푼 문제의 정답은 실리지 않아 은닉이 유지된다.
    """
    quizzes = _SESSIONS.get(req.quiz_id)
    if quizzes is None:  # RAM miss(서버 재시작 시 _SESSIONS 소실) → Cosmos 에서 복구 시도.
        from backend.quiz import quiz_store
        quizzes = quiz_store.load_session(req.quiz_id)
        if quizzes is not None:
            _SESSIONS[req.quiz_id] = quizzes  # 복구분을 RAM 에 재적재(다음 채점은 빠르게).
    if quizzes is None:  # 만료/미존재(Cosmos 미설정·TTL 만료 포함)
        raise HTTPException(404, "만료됐거나 알 수 없는 quiz_id 입니다. 퀴즈를 다시 생성하세요.")

    results: list[dict] = []
    score = 0
    for key, user_answer in req.answers.items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(quizzes):
            continue
        quiz = quizzes[index]
        correct = _is_correct(quiz, user_answer)
        score += int(correct)
        results.append({
            "index": index,
            "correct": correct,
            "answerText": quiz.get("answerText"),
            "explanation": quiz.get("explanation"),
        })

    results.sort(key=lambda r: r["index"])
    return {"score": score, "total": len(results), "results": results}
