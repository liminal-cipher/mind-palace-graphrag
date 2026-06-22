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

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import llm as _llm
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


def _resolve_snapshot_dir(key: str) -> tuple[str, Path] | None:
    """스냅샷 키를 (정규키, parquet 디렉터리)로 해석한다. 못 찾으면 None.

    1) serve 레지스트리(STATE): 쇼케이스 키 + 라이브 잡(job_id) + alias 를 모두 포함한다.
       라이브 잡은 rag 스테이지가 job_id 를 키로 serve 에 register 하므로(같은 프로세스,
       통합 app), 여기서 그 snapshot_dir 을 그대로 얻는다. serve 미가용(퀴즈 라우터 단독
       기동 등)이면 조용히 디스크로 폴백.
    2) 디스크 snapshots/<키>: serve warmup 전이거나 단독 기동된 쇼케이스 스냅샷.

    entities.parquet 존재까지 확인해 실제로 읽을 수 있는 스냅샷만 통과시킨다.
    """
    try:
        from backend.serve import STATE, _resolve_key

        rk = _resolve_key(key) or key
        st = STATE.snapshots.get(rk)
        if st is not None:
            d = Path(st.snapshot_dir)
            if not d.is_absolute():
                d = ROOT / d
            if (d / "entities.parquet").exists():
                return rk, d
    except Exception:  # noqa: BLE001  serve 미가용 등 -> 디스크 폴백
        pass
    d = ROOT / "snapshots" / key
    if (d / "entities.parquet").exists():
        return key, d
    return None


def _builder_for(snapshot: str | None) -> EvidenceBuilder | None:
    """스냅샷 키로 빌더를 고른다. 미지정/기본키이면 데모(테스트 페이지와 빌더 공유).

    명시 키가 해석되지 않으면 None 을 돌려준다(호출부에서 404). 데모로 조용히 떨구지
    않는다 - 라이브 잡(사용자 업로드 PDF)이 엉뚱한 도메인 퀴즈로 보이는 걸 막는다.
    """
    key = (snapshot or "").strip()
    if not key or key == DEFAULT_SNAPSHOT:
        return _get_builder()
    resolved = _resolve_snapshot_dir(key)
    if resolved is None:
        return None
    rk, snap_dir = resolved
    if rk == DEFAULT_SNAPSHOT:          # alias(repro_run3 등)도 데모 빌더를 공유
        return _get_builder()
    if rk not in _builders:
        _builders[rk] = EvidenceBuilder(snap_dir)
    return _builders[rk]


class QuizJsonRequest(BaseModel):
    topic: str = ""
    count: int = 10
    quiz_types: list[str] | None = None
    snapshot: str | None = None   # 등록 스냅샷 키(korean_history, statistics) 또는 라이브 잡 job_id. 미지정=데모


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
    if builder is None:
        raise HTTPException(
            404,
            f"스냅샷 '{req.snapshot}' 을(를) 찾을 수 없습니다(미등록이거나 아직 준비 안 됨).",
        )
    selected = builder.select_candidates(topic=req.topic, count=req.count)
    acc = _llm.start_usage_capture()  # 생성+검증 LLM 토큰 누적(이 요청 한정).
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
        "usage": _llm.usage_summary(acc),  # {total_tokens,...} - 프론트가 사용량 추적에 쓴다.
    }
