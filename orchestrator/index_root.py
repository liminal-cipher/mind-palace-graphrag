"""per-job GraphRAG 인덱싱 root 격리.

라이브 업로드는 레포 루트(국사 input/ 풋건 + output/ bare 점유)를 못 쓰므로, 잡마다
var/jobs/<id>/index_root/ 아래 독립 root(settings + input + prompts + output)를 세운다.
base_dir 는 전부 이 root 기준 상대라 graphrag index --root <root> 가 잡 폴더 안에서만
읽고 쓴다. settings 템플릿(stock)을 복사해 도메인 슬롯(entity_types + extract_graph
프롬프트)만 잡 생성 시 치환한다.

Finding A(STOP-1): entity_types 의 실제 구동자는 extract_graph 프롬프트(지시문 + 예시)다.
settings.yaml 의 entity_types 목록은 보조적이다. 그래서 도메인 프롬프트를 잡 prompts/ 로
복사하고(우선), entity_types 도 settings 에 함께 치환해 둘을 일관되게 맞춘다.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from orchestrator import config
from orchestrator.jobs import Job

# stock settings 템플릿 + 레포 stock 프롬프트(잡 root 가 자기 복사본을 쓰게 한다).
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
SETTINGS_TEMPLATE = TEMPLATE_DIR / "settings.live.yaml"
STOCK_PROMPTS_DIR = config.REPO / "prompts"

# 도메인 프롬프트로 덮어쓸 수 있는(덮어쓰면 그 도메인에 맞춰지는) 파일들.
EXTRACT_PROMPT_NAME = "extract_graph.txt"
SUMMARIZE_PROMPT_NAME = "summarize_descriptions.txt"
COMMUNITY_GRAPH_PROMPT_NAME = "community_report_graph.txt"

_ENTITY_TYPES_TOKEN = "__ENTITY_TYPES__"


def _render_settings(entity_types: list[str]) -> str:
    """stock 템플릿의 entity_types 토큰을 해소된 목록으로 치환. JSON flow 리스트는
    YAML 의 부분집합이라 공백 포함 타입('statistical concept')도 안전하게 인용된다."""
    if not entity_types:
        raise ValueError("entity_types 가 비어 있다. 라이브 인덱싱 root 를 세울 수 없다.")
    template = SETTINGS_TEMPLATE.read_text(encoding="utf-8")
    if _ENTITY_TYPES_TOKEN not in template:
        raise RuntimeError(f"settings 템플릿에 {_ENTITY_TYPES_TOKEN} 토큰이 없다.")
    return template.replace(_ENTITY_TYPES_TOKEN, json.dumps(entity_types, ensure_ascii=False))


def write_settings(root: Path, entity_types: list[str]) -> None:
    """root 의 settings.yaml 을 주어진 entity_types 로 (재)렌더한다. entity_types
    해소(discover/폴백)가 확정된 뒤 호출해 settings 와 프롬프트를 일관되게 맞춘다."""
    (root / "settings.yaml").write_text(_render_settings(entity_types), encoding="utf-8")


def build_index_root(
    job: Job,
    corpus_src: Path,
    entity_types: list[str],
    *,
    extract_prompt_src: Optional[Path] = None,
    summarize_prompt_src: Optional[Path] = None,
    community_graph_prompt_src: Optional[Path] = None,
) -> Path:
    """잡의 격리 인덱싱 root 를 materialize 하고 그 경로를 반환한다.

    corpus_src        업로드된 .txt (input/ 로 복사)
    entity_types      해소된 도메인 entity_types(settings 에 치환)
    *_prompt_src      도메인 프롬프트로 덮어쓸 소스(없으면 레포 stock 사용)

    재실행 멱등: 기존 root 는 통째로 지우고 새로 만든다(콜드).
    """
    corpus_src = Path(corpus_src)
    if not corpus_src.is_file():
        raise FileNotFoundError(f"코퍼스 입력 없음: {corpus_src}")

    root = config.job_dir(job.job_id) / "index_root"
    if root.exists():
        shutil.rmtree(root)
    input_dir = root / "input"
    prompts_dir = root / "prompts"
    input_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    # 1) 레포 stock 프롬프트 전체를 잡 prompts/ 로 복사(쿼리/인덱싱 프롬프트 자급).
    for p in sorted(STOCK_PROMPTS_DIR.glob("*.txt")):
        shutil.copy2(p, prompts_dir / p.name)

    # 2) 도메인 프롬프트 오버라이드(있으면). 타입을 박는 extract_graph 가 핵심.
    overrides = (
        (extract_prompt_src, EXTRACT_PROMPT_NAME),
        (summarize_prompt_src, SUMMARIZE_PROMPT_NAME),
        (community_graph_prompt_src, COMMUNITY_GRAPH_PROMPT_NAME),
    )
    for src, name in overrides:
        if src is not None:
            src = Path(src)
            if not src.is_file():
                raise FileNotFoundError(f"프롬프트 오버라이드 소스 없음: {src}")
            shutil.copy2(src, prompts_dir / name)

    # 3) 코퍼스를 input/ 으로(graphrag 는 input base_dir 의 모든 .txt 를 읽는다).
    shutil.copy2(corpus_src, input_dir / corpus_src.name)

    # 4) settings.yaml 렌더(entity_types 치환).
    write_settings(root, entity_types)
    return root


def index_output_dir(job: Job) -> Path:
    """graphrag 가 parquet + lancedb 를 떨구는 잡 출력 dir(=스냅샷 원본)."""
    return config.job_dir(job.job_id) / "index_root" / "output"
