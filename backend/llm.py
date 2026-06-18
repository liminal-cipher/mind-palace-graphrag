"""공용 Azure OpenAI(Responses API) 호출 헬퍼.

quiz_generator 가 쓰던 호출 패턴을 기능 무관한 인프라로 뽑은 것. 자격증명은 레포 공용
OPEN_AI_* 환경변수를 그대로 쓴다(전처리 step5, quiz 와 동일):

    OPEN_AI_KEY
    OPEN_AI_ENDPOINT                  (resource base URL 또는 전체 /openai/responses URL)
    OPEN_AI_DEPLOYMENT_NAME_4_1_MINI  (App Service 는 점(.) env 이름을 못 받아 밑줄형 우선,
                                       로컬 .env 의 점형 OPEN_AI_DEPLOYMENT_NAME_4.1_MINI 폴백)

quiz_generator 는 자체 사본을 유지한다(팀원 코드, 안 건드림). 신규 기능(mnemonic 등)은
여기를 import 한다. 나중에 quiz 도 여기로 합칠 수 있음.
"""
from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx

_RESPONSES_API_VERSION = "2025-04-01-preview"


def get_azure_responses_url() -> str | None:
    """OPEN_AI_ENDPOINT 를 Responses API URL 로 정규화. 미설정이면 None."""
    endpoint = os.environ.get("OPEN_AI_ENDPOINT")
    if not endpoint:
        return None

    if re.search(r"/openai/responses", endpoint, re.IGNORECASE):
        parts = urlsplit(endpoint)
        query = dict(parse_qsl(parts.query))
        if "api-version" not in query:
            query["api-version"] = _RESPONSES_API_VERSION
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    base = endpoint.rstrip("/")
    return f"{base}/openai/responses?api-version={quote(_RESPONSES_API_VERSION)}"


def extract_response_text(data: dict[str, Any]) -> str:
    """Responses API 응답에서 텍스트만 뽑는다(output_text 우선, 없으면 content 순회)."""
    if data.get("output_text"):
        return data["output_text"]

    texts: list[str] = []
    for item in data.get("output") or []:
        for content in item.get("content") or []:
            text = content.get("text")
            if text:
                texts.append(text)
    return "\n".join(texts).strip()


def deployment_name() -> str | None:
    """gpt-4.1-mini 배포명. App Service 밑줄형 우선, 로컬 점형 폴백."""
    return (os.environ.get("OPEN_AI_DEPLOYMENT_NAME_4_1_MINI")
            or os.environ.get("OPEN_AI_DEPLOYMENT_NAME_4.1_MINI"))


async def call_llm(input_payload: Any, max_output_tokens: int = 2400) -> str:
    """Responses API 호출 → 텍스트. input_payload 는 문자열 또는 [{role, content}, ...].

    자격증명/네트워크/4xx 오류는 RuntimeError 로 올린다(호출부가 502/503 등으로 매핑).
    """
    api_key = os.environ.get("OPEN_AI_KEY")
    deployment = deployment_name()
    url = get_azure_responses_url()

    if not (api_key and deployment and url):
        raise RuntimeError(
            "OPEN_AI_KEY / OPEN_AI_ENDPOINT / OPEN_AI_DEPLOYMENT_NAME_4_1_MINI 설정이 부족합니다."
        )

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url,
                headers={"Content-Type": "application/json", "api-key": api_key},
                json={"model": deployment, "input": input_payload,
                      "max_output_tokens": max_output_tokens},
            )
    except httpx.HTTPError as error:
        raise RuntimeError(f"Azure OpenAI 네트워크 연결 실패: {error}")

    data = response.json()
    if response.status_code >= 400:
        message = ((data.get("error") or {}).get("message")
                   or f"Azure OpenAI 호출 실패: {response.status_code}")
        raise RuntimeError(message)

    return extract_response_text(data)
