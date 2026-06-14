"""업로드 자료의 도메인 라벨을 싼 LLM 1콜로 감지한다.

이 라벨이 단일 소스다: prompt-tune --domain 과 toc_gen {domain} 둘 다 이 문자열을
먹는다(palace config 의 domain 필드로 흘러간다). 스냅샷 선택엔 절대 쓰지 않는다
(showcase 트리거와 분리, [orchestrator.stages] 참조).

감지 실패/빈 라벨은 예외로 올리지 않고 빈 문자열을 돌려준다. 호출부(entity_types
해소)가 빈 라벨을 generic 폴백 신호로 받는다(국사 7종 회귀 금지).
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("orchestrator.domain_detect")

# 비용 가드: 앞부분만 본다(슬라이드/교안은 도입부에 도메인 표지가 몰려 있다).
_MAX_CHARS = 4000
_DEFAULT_MODEL = "gpt-4.1-mini"

_SYS_PROMPT = (
    "당신은 학습 자료 분류기다. 주어진 한국어 학습 자료의 도메인을 한 줄로 요약하라. "
    "GraphRAG 추출/목차 생성을 도메인에 맞추는 데 쓰일 라벨이다. "
    "분야와 핵심 하위 주제를 괄호로 묶어 함께 적되, 장황한 설명은 금지한다. "
    '예: "조선 전기 한국사 (건국·통치제도·문화·사림·왜란)", '
    '"통계 기초 교안 (기술통계·확률분포·추정·가설검정·상관분석)".'
)


def detect_domain(corpus_text: str, *, model: str = _DEFAULT_MODEL) -> str:
    """코퍼스 앞부분으로 도메인 라벨을 감지한다. 실패 시 빈 문자열."""
    text = (corpus_text or "").strip()
    if not text:
        return ""
    sample = text[:_MAX_CHARS]
    try:
        from orchestrator import config
        from palace.room_gen import call_json, make_azure_client

        config.load_env()  # GRAPHRAG_API_KEY/BASE 보장(없으면 make_azure_client 가 SystemExit).
        client = make_azure_client()
        user_p = (
            "다음 자료의 도메인을 위 형식의 한 줄 라벨로만 출력하라.\n\n"
            f"자료(앞부분):\n{sample}\n\n"
            '출력 JSON: {"domain": "<한 줄 라벨>"}'
        )
        raw, _usage = call_json(client, model, _SYS_PROMPT, user_p)
        label = (json.loads(raw).get("domain") or "").strip()
        if not label:
            logger.warning("도메인 감지: 빈 라벨 반환됨")
        else:
            logger.info("도메인 감지: %s", label)
        return label
    except (Exception, SystemExit) as e:  # noqa: BLE001  감지 실패는 폴백으로 흡수.
        # make_azure_client 는 키 미설정 시 SystemExit 을 던지므로 함께 잡는다.
        logger.warning("도메인 감지 실패(폴백 진행): %s", e)
        return ""
