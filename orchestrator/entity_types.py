"""entity_types 해소: discover ON + generic 폴백 하이브리드(STOP-1 결과).

라이브 업로드의 실질 경로는 prompt-tune discover ON 이다(STOP-1 확정). 짧은 자료에서
기본 표본추출이 깨지므로 --selection-method all 을 하드코딩한다(STOP-1 실증). discover
산출 타입 개수에 새너티 게이트를 건다. 게이트/감지 실패 시 graphrag 기본 추출 프롬프트
(타입을 settings.entity_types 로 제약)에 중립 generic 목록을 물려 폴백한다. 국사 7종으로는
절대 떨어지지 않는다.

Finding A(STOP-1): 추출 타입의 실제 구동자는 extract_graph 프롬프트다.
  - discover 성공: prompt-tune 이 root/prompts/extract_graph.txt 에 타입을 baked.
  - 폴백: graphrag 기본 프롬프트(GRAPH_EXTRACTION_PROMPT, {entity_types} 치환)를 써서
    settings.entity_types(=generic)로 제약. 우리가 예시를 손으로 쓰지 않아 도메인 편향 0.

curated 룩업은 아직 채울 게 없다(쇼케이스는 scaffold 라 여기 안 옴). 빈 맵 + 훅만 둔다.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from orchestrator import config, index_root

logger = logging.getLogger("orchestrator.entity_types")

# 도메인 중립 폴백 목록(graphrag 기본 프롬프트가 이 목록으로 추출을 제약한다).
# 국사 7종(인물/사건/...)도 통계 15종도 아닌, 어느 도메인에도 안 치우친 일반 축.
GENERIC_ENTITY_TYPES: list[str] = [
    "person", "organization", "location", "event",
    "concept", "method", "artifact", "work", "role", "measure",
]

# discover 산출 타입 개수 새너티 게이트. 너무 적으면(축 붕괴) 너무 많으면(66종 폭발)
# 폴백한다.
DISCOVER_MIN_TYPES = 3
DISCOVER_MAX_TYPES = 30

# 자주 오는 도메인이 생기면 채울 curated 룩업(domain label -> entity_types). 지금은 빈
# 맵 + 훅. 채워지면 discover(비용)보다 먼저 쓰여 싸고 안정적이다.
CURATED_ENTITY_TYPES: dict[str, list[str]] = {}

_TYPES_LINE = re.compile(r"One of the following types:\s*\[(.+?)\]", re.DOTALL)


@dataclass
class Resolution:
    """entity_types 해소 결과. prompts/settings 는 root 안에 이미 반영돼 있다."""
    entity_types: list[str]
    source: str  # "curated" | "discover" | "fallback:<이유>"


def _run_prompt_tune_discover(root: Path, domain: str) -> tuple[int, str]:
    """prompt-tune discover ON 을 subprocess 로 돌린다(_run_palace 와 동형 seam).
    --output 은 graphrag 가 CWD 기준으로 resolve 하므로(--root 기준 아님) 반드시
    절대 경로(root/prompts)를 준다. 상대값이면 공유 레포 prompts/ 를 덮어써 stock
    프롬프트를 오염시킨다(serve/국사/템플릿 소스가 공유). 이 호출이 root/prompts 의
    type-bearing 프롬프트(extract_graph/summarize/community_report_graph)를 덮어쓴다.
    --selection-method all: 짧은 코퍼스에서 기본 random 표본추출이 깨지는 것 회피."""
    out_dir = (root / "prompts").resolve()
    cmd = [
        sys.executable, "-m", "graphrag", "prompt-tune",
        "--root", str(root),
        "--domain", domain,
        "--language", "Korean",
        "--selection-method", "all",
        "--output", str(out_dir),
        "--chunk-size", "1200",
        "--overlap", "100",
    ]
    proc = subprocess.run(
        cmd, cwd=str(config.REPO),
        capture_output=True, text=True, encoding="utf-8",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def parse_discovered_types(extract_prompt: Path) -> list[str]:
    """생성된 extract_graph.txt 지시문에서 baked entity_types 목록을 파싱한다.
    'One of the following types: [a, b, c]' 형태. 못 찾으면 빈 목록."""
    text = Path(extract_prompt).read_text(encoding="utf-8")
    m = _TYPES_LINE.search(text)
    if not m:
        return []
    return [t.strip() for t in m.group(1).split(",") if t.strip()]


def _apply_generic_fallback(root: Path, reason: str) -> Resolution:
    """폴백: type-bearing 프롬프트(extract_graph/summarize/community_report_graph)를
    graphrag 기본(도메인 중립) 상수로 덮고 settings 의 entity_types 를 generic 으로
    맞춘다. 기본 추출 프롬프트는 {entity_types} 를 런타임에 settings 목록으로 치환하므로
    generic 축으로 추출이 제약되고, 요약/커뮤니티 리포트도 '한국사 전문가' 톤(stock
    프롬프트 편향)이 사라진다. discover 성공 경로가 같은 3종을 덮는 것과 대칭이며,
    잡 root 의 prompts/ 에만 쓰고 공유 prompts/ 는 안 건드린다."""
    from graphrag.prompts.index.community_report import COMMUNITY_REPORT_PROMPT
    from graphrag.prompts.index.extract_graph import GRAPH_EXTRACTION_PROMPT
    from graphrag.prompts.index.summarize_descriptions import SUMMARIZE_PROMPT

    prompts_dir = root / "prompts"
    neutral_prompts = (
        (index_root.EXTRACT_PROMPT_NAME, GRAPH_EXTRACTION_PROMPT),
        (index_root.SUMMARIZE_PROMPT_NAME, SUMMARIZE_PROMPT),
        (index_root.COMMUNITY_GRAPH_PROMPT_NAME, COMMUNITY_REPORT_PROMPT),
    )
    for name, text in neutral_prompts:
        (prompts_dir / name).write_text(text, encoding="utf-8")
    index_root.write_settings(root, GENERIC_ENTITY_TYPES)
    logger.info("entity_types 폴백(generic %d종): %s", len(GENERIC_ENTITY_TYPES), reason)
    return Resolution(GENERIC_ENTITY_TYPES, f"fallback:{reason}")


def resolve_entity_types(root: Path, domain_label: str) -> Resolution:
    """root(코퍼스+settings 준비됨) + 감지 도메인 라벨로 entity_types 를 확정하고
    root 의 settings/프롬프트에 반영한다. 우선순위: curated -> discover -> generic 폴백."""
    root = Path(root)

    # 1) curated 룩업(현재 빈 맵).
    curated = CURATED_ENTITY_TYPES.get(domain_label)
    if curated:
        index_root.write_settings(root, curated)
        logger.info("entity_types curated(%d종): %s", len(curated), domain_label)
        return Resolution(curated, "curated")

    # 2) discover ON (라벨이 있어야 의미 있음).
    if domain_label:
        rc, out = _run_prompt_tune_discover(root, domain_label)
        if rc == 0:
            types = parse_discovered_types(root / "prompts" / index_root.EXTRACT_PROMPT_NAME)
            if DISCOVER_MIN_TYPES <= len(types) <= DISCOVER_MAX_TYPES:
                index_root.write_settings(root, types)
                logger.info("entity_types discover(%d종): %s", len(types), types)
                return Resolution(types, "discover")
            reason = f"discover 타입 {len(types)}종이 게이트[{DISCOVER_MIN_TYPES},{DISCOVER_MAX_TYPES}] 밖"
        else:
            reason = f"prompt-tune rc={rc}: {out[-400:]}"
    else:
        reason = "도메인 라벨 비어 있음(감지 실패)"

    # 3) generic 폴백.
    return _apply_generic_fallback(root, reason)
