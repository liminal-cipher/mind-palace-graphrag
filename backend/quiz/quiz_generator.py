"""Quiz generation/verification logic ported from server.js.

Two halves:

1. ``EvidenceBuilder`` loads the six GraphRAG parquet files, builds id lookup
   maps, and turns every row into a unified candidate evidence item shaped::

        {
            "kind": "entity | relationship | finding | community_report | document | text_unit | community",
            "source": "entities #12",
            "title": "...",
            "topic": "...",
            "answerSeed": "...",
            "text": "...",
        }

   ``select_candidates()`` then scores/samples those candidates for a topic.

2. ``generate_quizzes(selected, ...)`` takes a list of candidate items (from
   ``select_candidates`` or supplied directly) and produces verified quizzes.

Azure OpenAI 자격증명은 레포 공용 OPEN_AI_* 환경변수를 그대로 쓴다(전처리 step5 와
동일 리소스/스킴 재사용 -> 별도 키 체계를 새로 만들지 않는다):
    OPEN_AI_KEY
    OPEN_AI_ENDPOINT                  (resource base URL 또는 전체 /openai/responses URL)
    OPEN_AI_DEPLOYMENT_NAME_5_4_MINI  (App Service 는 점(.) env 이름을 못 받아 밑줄형 우선,
                                       로컬 .env 의 점형 OPEN_AI_DEPLOYMENT_NAME__5_4_MINI 폴백)
Responses API 버전은 step5 의 _OAI_API_VER 처럼 코드 상수로 고정한다(.env 에 버전 변수 없음).
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx
import numpy as np
import pandas as pd

QUIZ_TYPES = ("multiple_choice", "true_false", "short_answer")
DEFAULT_QUIZ_TYPES = list(QUIZ_TYPES)

PARQUET_FILES = (
    "communities.parquet",
    "community_reports.parquet",
    "documents.parquet",
    "entities.parquet",
    "relationships.parquet",
    "text_units.parquet",
)

CANDIDATE_KINDS = (
    "entity",
    "relationship",
    "finding",
    "community_report",
    "document",
    "text_unit",
    "community",
)


# --- text utilities --------------------------------------------------------

def _s(value: Any) -> str:
    """Render a scalar for evidence text, treating None as an empty string."""
    return "" if value is None else str(value)


def compact(text: Any, max_len: int = 900) -> str:
    base = str(text) if text else ""
    return re.sub(r"\s+", " ", base).strip()[:max_len]


def split_sentences(text: Any, limit: int = 18) -> list[str]:
    base = str(text) if text else ""
    sentences: list[str] = []
    for part in re.split(r"(?<=[.!?。！？])\s+|\n+", base):
        sentence = compact(part, 260)
        if len(sentence) >= 35:
            sentences.append(sentence)
            if len(sentences) >= limit:
                break
    return sentences


def summarize_list(items: list[Any] | None, limit: int = 10) -> str:
    values = [value for value in (items or []) if value]
    if not values:
        return "없음"
    visible = ", ".join(str(value) for value in values[:limit])
    hidden = len(values) - limit
    return f"{visible} 외 {hidden}개" if hidden > 0 else visible


def tokenize(text: Any) -> list[str]:
    stopwords = {"퀴즈", "문제", "생성", "만들어줘", "알려줘", "설명", "한국사"}
    particle = re.compile(r"(으로|에서|에게|까지|부터|라고|은|는|이|가|을|를|의|에|로|와|과|도|만)$")

    base = (str(text) if text else "").lower()
    cleaned = re.sub(r"[^\w\s]", " ", base, flags=re.UNICODE)

    expanded: list[str] = []
    for token in cleaned.split():
        stripped = particle.sub("", token)
        if stripped and stripped != token:
            expanded.extend([token, stripped])
        else:
            expanded.append(token)

    seen: set[str] = set()
    result: list[str] = []
    for token in expanded:
        if token in seen:
            continue
        seen.add(token)
        if len(token) >= 2 and token not in stopwords:
            result.append(token)
    return result


def score_candidate(candidate: dict[str, Any], tokens: list[str]) -> float:
    if not tokens:
        return random.random()
    title = str(candidate.get("title") or "").lower()
    topic = str(candidate.get("topic") or "").lower()
    haystack = f"{candidate.get('title')} {candidate.get('topic')} {candidate.get('text')}".lower()
    score = 0
    for token in tokens:
        if token in title:
            score += 8
        if token in topic:
            score += 4
        if token in haystack:
            score += 1
    return score


def pick_many(items: list[Any], count: int) -> list[Any]:
    pool = list(items)
    selected: list[Any] = []
    while pool and len(selected) < count:
        selected.append(pool.pop(random.randrange(len(pool))))
    return selected


# --- parquet loading & candidate building ----------------------------------

def _normalize_value(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return [_normalize_value(item) for item in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_value(val) for key, val in value.items()}
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def load_rows(path: str | Path) -> list[dict[str, Any]]:
    frame = pd.read_parquet(path)
    return [
        {key: _normalize_value(val) for key, val in record.items()}
        for record in frame.to_dict(orient="records")
    ]


class EvidenceBuilder:
    """Loads GraphRAG parquet files and builds quiz candidate evidence."""

    def __init__(self, data_dir: str | Path = "."):
        base = Path(data_dir)
        self.raw = {
            "communities": load_rows(base / "communities.parquet"),
            "community_reports": load_rows(base / "community_reports.parquet"),
            "documents": load_rows(base / "documents.parquet"),
            "entities": load_rows(base / "entities.parquet"),
            "relationships": load_rows(base / "relationships.parquet"),
            "text_units": load_rows(base / "text_units.parquet"),
        }

        self._document_by_id = {row.get("id"): row for row in self.raw["documents"]}
        self._entity_by_id = {row.get("id"): row for row in self.raw["entities"]}
        self._relationship_by_id = {row.get("id"): row for row in self.raw["relationships"]}
        self._community_by_number = {row.get("community"): row for row in self.raw["communities"]}
        self._text_unit_by_id = {row.get("id"): row for row in self.raw["text_units"]}

        self.candidates = self._build_candidates()

    # id -> human-readable name helpers

    def _community_title(self, number: Any) -> str:
        if number is None or number < 0:
            return "없음"
        community = self._community_by_number.get(number)
        return (community and community.get("title")) or f"주제 묶음 {_s(number)}"

    def _entity_name(self, entity_id: Any) -> str:
        entity = self._entity_by_id.get(entity_id)
        if not entity:
            return "알 수 없는 개념"
        entity_type = entity.get("type")
        return f"{_s(entity.get('title'))}{f'({_s(entity_type)})' if entity_type else ''}"

    def _relationship_name(self, relationship_id: Any) -> str:
        relationship = self._relationship_by_id.get(relationship_id)
        if not relationship:
            return "알 수 없는 관계"
        return f"{_s(relationship.get('source'))} ↔ {_s(relationship.get('target'))}"

    def _text_unit_name(self, text_unit_id: Any) -> str:
        text_unit = self._text_unit_by_id.get(text_unit_id)
        if not text_unit:
            return "원문 단위"
        document = self._document_by_id.get(text_unit.get("document_id"))
        title = (document and document.get("title")) or f"문서 {_s(text_unit.get('document_id'))}".strip()
        return f"{title} {_s(text_unit.get('human_readable_id'))}번 텍스트 단위"

    # candidate construction (one unified shape across all six parquet files)

    def _build_candidates(self) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []

        for row in self.raw["entities"]:
            candidates.append(
                {
                    "kind": "entity",
                    "source": f"entities #{_s(row.get('human_readable_id'))}",
                    "title": row.get("title"),
                    "topic": row.get("type") or "개념",
                    "answerSeed": row.get("title"),
                    "text": compact(
                        f"유형: {_s(row.get('type'))}. 설명: {_s(row.get('description'))}. "
                        f"빈도: {_s(row.get('frequency'))}. 연결 정도: {_s(row.get('degree'))}."
                    ),
                }
            )

        for row in self.raw["relationships"]:
            source = row.get("source")
            target = row.get("target")
            candidates.append(
                {
                    "kind": "relationship",
                    "source": f"relationships #{_s(row.get('human_readable_id'))}",
                    "title": f"{_s(source)} - {_s(target)}",
                    "topic": "관계",
                    "answerSeed": f"{_s(source)}와 {_s(target)}",
                    "text": compact(
                        f"출발: {_s(source)}. 대상: {_s(target)}. 관계 설명: {_s(row.get('description'))}. "
                        f"가중치: {_s(row.get('weight'))}. 결합 차수: {_s(row.get('combined_degree'))}."
                    ),
                }
            )

        for row in self.raw["community_reports"]:
            report_id = _s(row.get("human_readable_id"))
            candidates.append(
                {
                    "kind": "community_report",
                    "source": f"community_reports #{report_id}",
                    "title": row.get("title"),
                    "topic": "단원 요약",
                    "answerSeed": row.get("title"),
                    "text": compact(
                        f"요약: {_s(row.get('summary'))}. 평가: {_s(row.get('rating_explanation'))}. "
                        f"중요도: {_s(row.get('rank'))}. 전체 내용: {_s(row.get('full_content'))}",
                        1300,
                    ),
                }
            )
            findings = row.get("findings") if isinstance(row.get("findings"), list) else []
            for index, finding in enumerate(findings):
                summary = finding.get("summary") if isinstance(finding, dict) else None
                explanation = finding.get("explanation") if isinstance(finding, dict) else None
                candidates.append(
                    {
                        "kind": "finding",
                        "source": f"community_reports #{report_id}.{index + 1}",
                        "title": summary or row.get("title"),
                        "topic": row.get("title"),
                        "answerSeed": summary or row.get("title"),
                        "text": compact(
                            f"단원 묶음: {_s(row.get('title'))}. 핵심: {_s(summary)}. "
                            f"설명: {_s(explanation)}. 중요도: {_s(row.get('rank'))}."
                        ),
                    }
                )

        for row in self.raw["documents"]:
            report_id = _s(row.get("human_readable_id"))
            for index, sentence in enumerate(split_sentences(row.get("text"), 12)):
                candidates.append(
                    {
                        "kind": "document",
                        "source": f"documents #{report_id}.{index + 1}",
                        "title": row.get("title") or f"문서 {report_id}",
                        "topic": "원문 지문",
                        "answerSeed": row.get("title") or "원문",
                        "text": sentence,
                    }
                )

        for row in self.raw["text_units"]:
            document = self._document_by_id.get(row.get("document_id"))
            document_title = (document and document.get("title")) or "원문"
            candidates.append(
                {
                    "kind": "text_unit",
                    "source": f"text_units #{_s(row.get('human_readable_id'))}",
                    "title": f"{document_title} {_s(row.get('human_readable_id'))}번 텍스트 단위",
                    "topic": "원문 텍스트 단위",
                    "answerSeed": (document and document.get("title")) or "원문 텍스트",
                    "text": compact(
                        f"원문: {_s(row.get('text'))}. 토큰 수: {_s(row.get('n_tokens'))}. "
                        f"연결 개념: {summarize_list([self._entity_name(i) for i in (row.get('entity_ids') or [])], 12)}. "
                        f"연결 관계: {summarize_list([self._relationship_name(i) for i in (row.get('relationship_ids') or [])], 8)}.",
                        1200,
                    ),
                }
            )

        for row in self.raw["communities"]:
            community_label = row.get("title") or f"주제 묶음 {_s(row.get('community'))}"
            candidates.append(
                {
                    "kind": "community",
                    "source": f"communities #{_s(row.get('human_readable_id'))}",
                    "title": row.get("title") or f"Community {_s(row.get('community'))}",
                    "topic": f"level {_s(row.get('level'))}",
                    "answerSeed": row.get("title") or f"Community {_s(row.get('community'))}",
                    "text": compact(
                        f"주제 묶음: {community_label}. 계층: {_s(row.get('level'))}. "
                        f"상위 묶음: {self._community_title(row.get('parent'))}. "
                        f"하위 묶음: {summarize_list([self._community_title(c) for c in (row.get('children') or [])], 8)}. "
                        f"포함 개념: {summarize_list([self._entity_name(i) for i in (row.get('entity_ids') or [])], 14)}. "
                        f"포함 관계: {summarize_list([self._relationship_name(i) for i in (row.get('relationship_ids') or [])], 10)}. "
                        f"관련 원문 단위: {summarize_list([self._text_unit_name(i) for i in (row.get('text_unit_ids') or [])], 8)}. "
                        f"기간: {_s(row.get('period'))}. 크기: {_s(row.get('size'))}."
                    ),
                }
            )

        return [c for c in candidates if c.get("title") and c.get("text")]

    def select_candidates(
        self, topic: str = "", types: list[str] | None = None, count: int = 10
    ) -> list[dict[str, Any]]:
        tokens = tokenize(topic)
        allowed = set(types) if types else set(CANDIDATE_KINDS)
        allowed_candidates = [c for c in self.candidates if c["kind"] in allowed]

        scored = []
        for candidate in allowed_candidates:
            score = score_candidate(candidate, tokens)
            if tokens and not score > 0:
                continue
            scored.append({**candidate, "score": score})
        scored.sort(key=lambda candidate: candidate["score"], reverse=True)

        primary = scored[: max(count * 4, 20)]
        return pick_many(primary or allowed_candidates, max(count * 2, 12))


# --- prompt building -------------------------------------------------------

def build_evidence(selected: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"[{index + 1}] {item.get('kind')} | {item.get('source')} | {item.get('title')}\n{item.get('text')}"
        for index, item in enumerate(selected)
    )


def build_quiz_prompt(count: int, quiz_types: list[str], topic: str, selected: list[dict[str, Any]]) -> str:
    evidence = build_evidence(selected)
    return f"""다음 GraphRAG parquet 근거만 사용해서 한국사 학습 퀴즈를 만들어라.

요구사항:
- 문제 수: {count}개
- 허용 문제 유형: {", ".join(quiz_types)}
- 사용자가 요청한 주제: {topic or "전체"}
- 다양한 parquet 출처(entities, relationships, community_reports, documents, text_units, communities)를 가능한 한 섞어라.
- 각 문제는 근거에서 확인되는 사실만 사용한다.
- 4지선다 문제는 보기 4개를 만들고 정답 index는 0부터 시작한다.
- OX 문제는 choices를 ["O", "X"]로 만들고 정답 index는 0 또는 1이다.
- 단답형 문제는 choices를 빈 배열로 둔다.
- explanation에는 왜 정답인지 1~2문장으로 설명한다.
- sourceIds에는 사용한 근거 번호를 문자열 배열로 넣는다.
- JSON 이외의 텍스트는 절대 출력하지 마라.

JSON 형식:
{{
  "quizzes": [
    {{
      "type": "multiple_choice | true_false | short_answer",
      "question": "문제",
      "choices": ["보기1", "보기2", "보기3", "보기4"],
      "answerIndex": 0,
      "answerText": "정답",
      "explanation": "해설",
      "sourceIds": ["1"]
    }}
  ]
}}

근거:
{evidence}"""


def build_verification_prompt(quizzes: list[dict[str, Any]], selected: list[dict[str, Any]]) -> str:
    evidence = build_evidence(selected)
    quiz_payload = [
        {
            "index": index,
            "type": quiz.get("type"),
            "question": quiz.get("question"),
            "choices": quiz.get("choices"),
            "answerIndex": quiz.get("answerIndex"),
            "answerText": quiz.get("answerText"),
            "explanation": quiz.get("explanation"),
            "sourceIds": quiz.get("sourceIds"),
        }
        for index, quiz in enumerate(quizzes)
    ]

    payload = json.dumps({"quizzes": quiz_payload}, ensure_ascii=False, indent=2)
    return f"""You are a strict quiz fact-checker.

Validate each quiz using ONLY the provided GraphRAG evidence.

Pass a quiz only when:
- The correct answer is directly supported by the evidence.
- The explanation is supported by the evidence and does not add unsupported facts.
- For multiple-choice questions, no other choice is also correct according to the evidence.
- The question is clear and not misleading.

Fail a quiz when:
- The answer or explanation requires outside knowledge.
- The evidence is too weak or unrelated.
- Multiple choices could be correct.
- The quiz asks about a fact not present in the evidence.

Return JSON only. Do not include markdown.

JSON format:
{{
  "reviews": [
    {{
      "index": 0,
      "verdict": "pass | fail",
      "reason": "short reason in Korean",
      "safeExplanation": "Korean explanation strictly grounded in evidence, or empty string"
    }}
  ]
}}

Evidence:
{evidence}

Quizzes to verify:
{payload}"""


# --- Azure OpenAI client ---------------------------------------------------

# Responses API 버전. step5_llm 의 _OAI_API_VER 와 같은 패턴으로 코드에 고정(.env 미사용).
_RESPONSES_API_VERSION = "2025-04-01-preview"


def get_azure_responses_url() -> str | None:
    endpoint = os.environ.get("OPEN_AI_ENDPOINT")
    api_version = _RESPONSES_API_VERSION
    if not endpoint:
        return None

    if re.search(r"/openai/responses", endpoint, re.IGNORECASE):
        parts = urlsplit(endpoint)
        query = dict(parse_qsl(parts.query))
        if "api-version" not in query:
            query["api-version"] = api_version
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    base = endpoint.rstrip("/")
    return f"{base}/openai/responses?api-version={quote(api_version)}"


def parse_json_object(text: str) -> dict[str, Any]:
    trimmed = str(text or "").strip()
    try:
        return json.loads(trimmed)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", trimmed)
        if not match:
            raise ValueError("LLM 응답에서 JSON을 찾지 못했습니다.")
        return json.loads(match.group(0))


def extract_response_text(data: dict[str, Any]) -> str:
    if data.get("output_text"):
        return data["output_text"]

    texts: list[str] = []
    for item in data.get("output") or []:
        for content in item.get("content") or []:
            text = content.get("text")
            if text:
                texts.append(text)
    return "\n".join(texts).strip()


async def call_llm(input_payload: Any, max_output_tokens: int = 2400) -> str:
    api_key = os.environ.get("OPEN_AI_KEY")
    # App Service env 는 점(.)을 못 받아 밑줄형이 올라간다; step5_llm 과 동일 폴백.
    deployment = (os.environ.get("OPEN_AI_DEPLOYMENT_NAME_5_4_MINI")
                  or os.environ.get("OPEN_AI_DEPLOYMENT_NAME_5.4_MINI"))
    url = get_azure_responses_url()

    if not (api_key and deployment and url):
        raise RuntimeError(
            "OPEN_AI_KEY / OPEN_AI_ENDPOINT / OPEN_AI_DEPLOYMENT_NAME_5_4_MINI 설정이 부족합니다."
        )

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url,
                headers={"Content-Type": "application/json", "api-key": api_key},
                json={"model": deployment, "input": input_payload, "max_output_tokens": max_output_tokens},
            )
    except httpx.HTTPError as error:
        raise RuntimeError(f"Azure OpenAI 네트워크 연결 실패: {error}")

    data = response.json()
    if response.status_code >= 400:
        message = (data.get("error") or {}).get("message") or f"Azure OpenAI 호출 실패: {response.status_code}"
        raise RuntimeError(message)

    from backend.llm import record_usage  # 공용 누적기에 토큰 기록(누적기 깔려 있을 때만).
    record_usage(data)
    return extract_response_text(data)


# --- quiz normalization ----------------------------------------------------

def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def shuffle_array(items: list[Any]) -> list[Any]:
    shuffled = list(items)
    random.shuffle(shuffled)
    return shuffled


def shuffle_choices_with_answer(choices: list[str], answer_index: Any) -> tuple[list[str], int]:
    normalized = answer_index if _is_int(answer_index) else 0
    pairs = [{"choice": choice, "index": index} for index, choice in enumerate(choices)]
    random.shuffle(pairs)
    new_choices = [pair["choice"] for pair in pairs]
    new_index = next((i for i, pair in enumerate(pairs) if pair["index"] == normalized), -1)
    return new_choices, new_index


def normalize_quiz(quiz: dict[str, Any], index: int) -> dict[str, Any]:
    quiz_type = quiz.get("type") if quiz.get("type") in QUIZ_TYPES else "multiple_choice"
    raw_choices = quiz.get("choices")
    choices = [str(choice) for choice in raw_choices] if isinstance(raw_choices, list) else []
    answer_index = quiz.get("answerIndex") if _is_int(quiz.get("answerIndex")) else 0
    fallback_choice = choices[answer_index] if 0 <= answer_index < len(choices) else ""
    answer_text = str(quiz.get("answerText") or fallback_choice or "")

    if quiz_type == "multiple_choice" and len(choices) > 1:
        choices, answer_index = shuffle_choices_with_answer(choices, answer_index)

    raw_source_ids = quiz.get("sourceIds")
    return {
        "id": f"q-{int(time.time() * 1000)}-{index}",
        "type": quiz_type,
        "difficulty": quiz.get("difficulty") or "medium",
        "question": str(quiz.get("question") or "").strip(),
        "choices": choices,
        "answerIndex": answer_index,
        "answerText": answer_text,
        "explanation": str(quiz.get("explanation") or "").strip(),
        "sourceIds": [str(s) for s in raw_source_ids] if isinstance(raw_source_ids, list) else [],
    }


# --- verification & fallback ----------------------------------------------

async def verify_quizzes(
    quizzes: list[dict[str, Any]], selected: list[dict[str, Any]]
) -> dict[str, Any]:
    if not quizzes:
        return {"quizzes": [], "reviews": []}

    text = await call_llm(
        [
            {"role": "system", "content": "You are a strict fact-checker. Return valid JSON only."},
            {"role": "user", "content": build_verification_prompt(quizzes, selected)},
        ],
        2200,
    )

    parsed = parse_json_object(text)
    reviews = parsed.get("reviews") if isinstance(parsed.get("reviews"), list) else []
    review_by_index = {int(review.get("index")): review for review in reviews if review.get("index") is not None}

    verified: list[dict[str, Any]] = []
    for index, quiz in enumerate(quizzes):
        review = review_by_index.get(index)
        if not review or str(review.get("verdict")).lower() != "pass":
            continue
        safe_explanation = str(review.get("safeExplanation") or "").strip()
        verified.append({**quiz, "explanation": safe_explanation} if safe_explanation else quiz)

    return {"quizzes": verified, "reviews": reviews}


def fallback_quizzes(selected: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(selected[:count]):
        if item.get("kind") == "relationship":
            source, _, target = str(item.get("title", "")).partition(" - ")
            result.append(
                normalize_quiz(
                    {
                        "type": "short_answer",
                        "difficulty": "medium",
                        "question": f"다음 설명과 관련된 두 대상은 무엇인가요?\n{item.get('text')}",
                        "choices": [],
                        "answerText": f"{source}와 {target}",
                        "explanation": item.get("text"),
                        "sourceIds": [str(index + 1)],
                    },
                    index,
                )
            )
            continue

        result.append(
            normalize_quiz(
                {
                    "type": "short_answer",
                    "difficulty": "medium",
                    "question": f"다음 설명에 해당하는 개념이나 주제는 무엇인가요?\n{item.get('text')}",
                    "choices": [],
                    "answerText": item.get("answerSeed"),
                    "explanation": item.get("text"),
                    "sourceIds": [str(index + 1)],
                },
                index,
            )
        )
    return result


# --- orchestration ---------------------------------------------------------

async def generate_quizzes(
    selected: list[dict[str, Any]],
    *,
    count: int = 10,
    quiz_types: list[str] | None = None,
    topic: str = "",
) -> dict[str, Any]:
    """Generate quizzes from already-selected evidence.

    Returns a dict with ``mode`` ("llm_verified" or "fallback"), ``quizzes``,
    ``evidence`` (the selected items) and, for the LLM path, ``reviews``.
    """
    count = min(max(int(count or 10), 1), 20)
    topic = str(topic or "").strip()
    quiz_types = quiz_types if quiz_types else DEFAULT_QUIZ_TYPES

    prompt = build_quiz_prompt(count, quiz_types, topic, selected)

    try:
        text = await call_llm(
            [
                {"role": "system", "content": "너는 한국사 교사용 퀴즈 출제 도우미다. 반드시 유효한 JSON만 출력한다."},
                {"role": "user", "content": prompt},
            ],
            6000,
        )
        parsed = parse_json_object(text)
        raw_quizzes = (parsed.get("quizzes") or [])[:count]
        quizzes = [normalize_quiz(quiz, index) for index, quiz in enumerate(raw_quizzes)]
        quizzes = [quiz for quiz in quizzes if quiz["question"]]

        verification = await verify_quizzes(quizzes, selected)
        if not verification["quizzes"]:
            return {
                "mode": "fallback",
                "warning": "LLM 검증 단계에서 통과한 문제가 없어 근거 기반 단답형 문제로 대체했습니다.",
                "quizzes": shuffle_array(fallback_quizzes(selected, count)),
                "evidence": selected,
                "reviews": verification["reviews"],
            }

        return {
            "mode": "llm_verified",
            "quizzes": shuffle_array(verification["quizzes"])[:count],
            "evidence": selected,
            "reviews": verification["reviews"],
        }
    except Exception as error:  # noqa: BLE001 - mirror server.js fallback behavior
        return {
            "mode": "fallback",
            "warning": str(error),
            "quizzes": shuffle_array(fallback_quizzes(selected, count)),
            "evidence": selected,
        }
