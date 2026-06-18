"""
공용 Azure OpenAI 헬퍼 (step4·step5 공용)

- 본문/캡션 정제: gpt-4.1-mini (_OAI_MINI)
- 이미지 읽기/생성: gpt-4o vision (_OAI_4O)

읽기(전사)와 생성(묘사)은 동일 gpt-4o 배포에 프롬프트만 다르게 호출한다.
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image

load_dotenv(Path(__file__).parent.parent.parent / ".env")

OAI_ENDPOINT = os.environ.get("OPEN_AI_ENDPOINT", "").rstrip("/")
OAI_KEY      = os.environ.get("OPEN_AI_KEY", "")
OAI_MINI     = (os.environ.get("OPEN_AI_DEPLOYMENT_NAME_4_1_MINI")  # Azure Linux App Service 는 env 이름의 '.' 를 못 넘김 -> '_' 형 우선
                or os.environ.get("OPEN_AI_DEPLOYMENT_NAME_4.1_MINI", ""))  # 로컬 .env(점 이름) 폴백
OAI_4O       = os.environ.get("OPEN_AI_DEPLOYMENT_NAME_4O", "")
OAI_API_VER  = "2024-10-21"


def oai_chat(messages: list[dict], deployment: str, max_tokens: int = 4096) -> str:
    url = f"{OAI_ENDPOINT}/openai/deployments/{deployment}/chat/completions?api-version={OAI_API_VER}"
    resp = requests.post(
        url,
        headers={"api-key": OAI_KEY, "Content-Type": "application/json"},
        json={"messages": messages, "max_tokens": max_tokens},
        timeout=120,
    )
    if not resp.ok:
        print(f"  [LLM ERROR] {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _b64_png(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def read_caption(image: Image.Image) -> str:
    """이미지에 인쇄된 캡션 문구를 그대로 전사(transcribe)한다. 없으면 빈 문자열."""
    if not OAI_ENDPOINT or not OAI_KEY:
        raise RuntimeError("환경변수 OPEN_AI_ENDPOINT / OPEN_AI_KEY 미설정")
    b64 = _b64_png(image)
    msgs = [
        {"role": "system", "content": "당신은 한국어 교육 자료의 캡션을 정확히 옮겨 적는 전문가입니다."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    "이미지에 인쇄된 캡션 문구를 그대로 옮겨 적어 주세요. "
                    "설명을 새로 만들지 말고 보이는 글자만 전사하세요. "
                    "캡션이 없으면 빈 문자열만 답하세요."
                )},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        },
    ]
    return oai_chat(msgs, OAI_4O, max_tokens=256)
