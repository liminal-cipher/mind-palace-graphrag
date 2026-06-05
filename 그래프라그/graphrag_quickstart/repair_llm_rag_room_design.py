from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from build_12_llm_room_design import (
    call_model,
    compact_text,
    enrich_entities,
    extract_json_object,
    generate_html,
    load_config,
    load_dotenv,
    load_inputs,
    make_prompt,
    remove_duplicate_entities,
    validate_rooms,
    write_flow,
    write_markdown,
    build_payload,
)


DEFAULT_SOURCE = Path("output/그래프라그 방나누기/LLM+라그/1차/graphrag_root/output")
DEFAULT_BAD_JSON = Path("output/그래프라그 방나누기/LLM+라그/1차/1차_LLM방재설계.json")
DEFAULT_OUTPUT = Path("output/그래프라그 방나누기/LLM+라그/1차(수정)")
DEFAULT_CONFIG = Path("output/그래프라그 방나누기/gpt4.1mini/NEW/settings_gpt5.4mini.yaml")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair LLM+RAG room design through LLM semantic re-assignment, without forced local placement."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--bad-json", type=Path, default=DEFAULT_BAD_JSON)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--min-rooms", type=int, default=4)
    parser.add_argument("--max-rooms", type=int, default=7)
    return parser.parse_args()


def summarize_communities(communities: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "community_id": community.cid,
            "title": community.title,
            "summary": compact_text(community.summary, 520),
            "size": community.size,
            "rank": round(community.rank, 4),
            "entity_ids": sorted(community.entity_ids),
        }
        for community in communities
    ]


def make_repair_prompt(
    bad_result: dict[str, Any],
    validation: dict[str, Any],
    communities: list[Any],
    min_rooms: int,
    max_rooms: int,
) -> str:
    community_summaries = summarize_communities(communities)
    return f"""
아래는 GraphRAG 근거를 바탕으로 만든 3D 학습방 설계안입니다.
하지만 로컬 검증 결과, 원본 커뮤니티 누락/중복과 의미적으로 어색한 자동 보정 가능성이 확인되었습니다.

이번 작업의 목표:
- 로컬이 누락 커뮤니티를 강제로 붙이지 않습니다.
- 당신이 의미를 보고 커뮤니티를 다시 배치합니다.
- 최종 방은 {min_rooms}~{max_rooms}개 사이에서 품질 우선으로 선택합니다.
- 모든 community_id는 정확히 한 번만 배치해야 합니다.
- 방 제목과 source_communities가 의미적으로 맞아야 합니다.
- 특히 조선 건국 방에 조선 후기 지리학/역사서/화성 축성 같은 커뮤니티를 억지로 넣지 마세요.
- 작은 커뮤니티는 독립 방보다 관련 방의 하위구역으로 넣되, 시대/주제가 어긋나면 새 방이나 다른 방을 선택하세요.
- entity_id는 기존 GraphRAG ID를 유지하세요.
- 출력은 JSON만 하세요.

검증 실패 정보:
{json.dumps(validation, ensure_ascii=False, indent=2)}

원본 커뮤니티 전체 목록:
{json.dumps(community_summaries, ensure_ascii=False, indent=2)}

기존 설계안:
{json.dumps(bad_result, ensure_ascii=False, indent=2)}

출력 JSON 스키마:
{{
  "room_count_decision": {{
    "selected_room_count": 0,
    "reason": "방 개수 결정 이유"
  }},
  "rooms": [
    {{
      "room_no": 1,
      "title": "방 제목",
      "learning_flow": "학습 흐름",
      "design_reason": "커뮤니티를 이렇게 묶은 이유",
      "source_communities": [0],
      "subzones": [
        {{
          "title": "하위구역 제목",
          "source_communities": [0],
          "entity_ids": [1, 2, 3]
        }}
      ],
      "entities": [
        {{
          "entity_id": 1,
          "title": "엔티티명",
          "visibility": "core | supporting | search_only",
          "reason": "표시 등급 이유"
        }}
      ],
      "risk_flags": ["사용자 검토가 필요한 애매한 배치"]
    }}
  ],
  "ambiguous_items_for_user_review": [
    {{
      "item_type": "community | entity",
      "id": 0,
      "current_room_no": 1,
      "reason": "사용자 검토가 필요한 이유"
    }}
  ],
  "self_check": {{
    "all_communities_covered": true,
    "duplicate_community_ids": [],
    "missing_community_ids": [],
    "notes": "자체 점검"
  }}
}}
""".strip()


def sync_subzones_only(result: dict[str, Any], communities: list[Any]) -> dict[str, Any]:
    """Fix only internal subzone references. Do not assign missing communities."""
    fixed = json.loads(json.dumps(result, ensure_ascii=False))
    by_id = {community.cid: community for community in communities}
    for room in fixed.get("rooms", []):
        room_ids = {int(cid) for cid in room.get("source_communities", [])}
        new_subzones = []
        covered = set()
        for subzone in room.get("subzones", []):
            ids = [int(cid) for cid in subzone.get("source_communities", []) if int(cid) in room_ids]
            if not ids:
                continue
            subzone["source_communities"] = ids
            covered.update(ids)
            new_subzones.append(subzone)
        for cid in sorted(room_ids - covered):
            community = by_id.get(cid)
            if not community:
                continue
            new_subzones.append(
                {
                    "title": community.title,
                    "source_communities": [cid],
                    "entity_ids": sorted(community.entity_ids)[:12],
                }
            )
        room["subzones"] = new_subzones
    return fixed


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    load_dotenv(Path(".env"))
    config = load_config(args.config)

    communities, entities, relationships = load_inputs(args.source)
    payload, entities_by_id = build_payload(communities, entities, relationships)
    bad_result = json.loads(args.bad_json.read_text(encoding="utf-8"))
    bad_validation = bad_result.get("validation_before_repair") or validate_rooms(
        bad_result, {community.cid for community in communities}
    )

    prompt = make_repair_prompt(
        bad_result,
        bad_validation,
        communities,
        args.min_rooms,
        args.max_rooms,
    )
    prompt_record = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(args.source),
        "bad_json": str(args.bad_json),
        "prompt": prompt,
        "note": "Semantic repair prompt. No forced local assignment of missing communities.",
    }
    (args.output / "1차수정_LLM재검토_prompt.json").write_text(
        json.dumps(prompt_record, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    raw, usage = call_model(
        config,
        system=(
            "You are a careful Korean-history learning-room repair reviewer. "
            "Repair room-community assignments semantically. Preserve IDs. Output JSON only."
        ),
        user=prompt,
        max_tokens=12000,
    )
    (args.output / "1차수정_LLM재검토_raw.md").write_text(raw, encoding="utf-8")
    parsed = extract_json_object(raw)
    validation_before_local = validate_rooms(parsed, {community.cid for community in communities})
    synced = sync_subzones_only(parsed, communities)
    enriched = enrich_entities(synced, entities_by_id)
    enriched = remove_duplicate_entities(enriched)
    enriched = enrich_entities(enriched, entities_by_id)
    validation = validate_rooms(enriched, {community.cid for community in communities})

    result = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(args.source),
        "model": config["azure_openai"].get("model"),
        "deployment_name": config["azure_openai"].get("deployment_name"),
        "usage": usage.model_dump() if hasattr(usage, "model_dump") else str(usage),
        "repair_policy": "LLM semantic reassignment first; local validation only; no forced missing-community assignment.",
        "validation_before_local_sync": validation_before_local,
        "validation": validation,
        **enriched,
    }
    (args.output / "1차수정_LLM방재설계.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_markdown(result, validation, args.output / "1차수정_LLM방재설계.md")
    write_flow(
        args.output / "1차수정_플로우_정리.md",
        str(args.source),
        {"enabled": False},
    )
    generate_html(
        result,
        validation,
        args.output / "1차수정_방_엔티티_시각화.html",
        title="LLM+라그 1차(수정) 방 재설계",
    )
    print(f"Wrote: {args.output / '1차수정_LLM방재설계.md'}")
    print(f"Wrote: {args.output / '1차수정_방_엔티티_시각화.html'}")
    print(f"Validation: {validation}")
    print(f"Usage: {usage}")


if __name__ == "__main__":
    main()
