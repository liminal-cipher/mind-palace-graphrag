"""인룸 퀴즈용 JSON API (트랙 B 일부): 프론트(3D 기억의 궁전)가 호출하는 생성 엔드포인트.

기존 테스트 페이지(quiz_page.py: GET/POST /quiz, POST /quiz/grade)와 생성 로직
(quiz_generator.py)은 **건드리지 않는다**. 같은 생성 로직·정답 보관(_SESSIONS)·은닉 규칙
(_ANSWER_KEYS)을 그대로 재사용해, HTML 대신 JSON만 돌려주는 라우트 하나(POST /quiz/json)를
더한다(추가만). 채점은 기존 POST /quiz/grade 를 그대로 쓴다 - 같은 _SESSIONS 에 quiz_id 로
보관하므로 호환된다(별도 채점 라우트를 새로 만들지 않는다).

경로 주의(docs/quiz.md §9.1): POST /quiz(HTML form)는 quiz_page 가 점유하므로, JSON 은
/quiz/json 으로 분리해 충돌을 피한다.

배선: app.py 에서 include_router(quiz_json.router) (serve mount('/') 앞, quiz_page 옆).
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.quiz.quiz_generator import EvidenceBuilder, generate_quizzes
from backend.quiz.quiz_page import (
    ROOT,
    SNAPSHOT_DIR,
    _ANSWER_KEYS,
    _get_builder,
    _store_quiz,
)

router = APIRouter()

# 기본 데모(korean_history) 빌더는 테스트 페이지와 같은 인스턴스를 공유한다(_get_builder).
# 그 외 스냅샷만 여기서 1회 lazy 로드해 캐시한다(같은 parquet 이 RAM 에 중복 적재되지 않게).
_builders: dict[str, EvidenceBuilder] = {}

DEFAULT_SNAPSHOT = SNAPSHOT_DIR.name  # "korean_history"


def _builder_for(snapshot: str | None) -> EvidenceBuilder:
    """스냅샷 키로 빌더를 고른다. 미지정/미등록이면 기본 데모(korean_history)로 폴백.

    기본 키는 테스트 페이지와 같은 빌더를 공유하고, 임의의 다른 등록 스냅샷만 여기서
    snapshots/<키> 를 추가 로드한다. 데모 안정성을 위해 없는 키는 막지 않고 데모로 떨군다.
    """
    key = (snapshot or "").strip() or DEFAULT_SNAPSHOT
    if key == DEFAULT_SNAPSHOT:
        return _get_builder()
    snap_dir = ROOT / "snapshots" / key
    if not snap_dir.exists():
        return _get_builder()
    if key not in _builders:
        _builders[key] = EvidenceBuilder(snap_dir)
    return _builders[key]


class QuizJsonRequest(BaseModel):
    topic: str = ""
    count: int = 10
    quiz_types: list[str] | None = None
    snapshot: str | None = None   # 등록 스냅샷 키(예: korean_history, statistics). 미지정=데모


@router.post("/quiz/json")
async def quiz_json(req: QuizJsonRequest):
    """프론트(인룸 퀴즈)용 JSON 퀴즈 생성. 질문만 반환(정답 은닉), 채점은 POST /quiz/grade.

    응답: {quiz_id, questions[], mode, warning}.
    - quiz_id: 채점(POST /quiz/grade {quiz_id, answers})에 그대로 넘긴다. 정답 포함 원본은
      서버 _SESSIONS 에 보관되고 클라엔 quiz_id 만 내려간다.
    - questions: _ANSWER_KEYS(answerIndex/answerText/explanation/sourceIds)를 떼어낸 뷰
      (응답 본문에 정답이 안 실려 은닉 유지).
    - mode: "llm_verified" | "fallback". fallback 도 정상 200(배지/안내용).
    """
    builder = _builder_for(req.snapshot)
    selected = builder.select_candidates(topic=req.topic, count=req.count)
    result = await generate_quizzes(
        selected, count=req.count, quiz_types=req.quiz_types or None, topic=req.topic,
    )

    quizzes = result.get("quizzes") or []
    quiz_id = _store_quiz(quizzes) if quizzes else None
    questions = [
        {k: v for k, v in quiz.items() if k not in _ANSWER_KEYS} for quiz in quizzes
    ]
    return {
        "quiz_id": quiz_id,
        "questions": questions,
        "mode": result.get("mode"),
        "warning": result.get("warning"),
    }
