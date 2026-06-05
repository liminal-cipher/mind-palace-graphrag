from __future__ import annotations

import json
from pathlib import Path

from build_12_llm_room_design import (
    build_payload,
    enrich_entities,
    generate_html,
    load_inputs,
    remove_duplicate_entities,
    tokenize,
    write_markdown,
)
from build_llm_rag_ui_first_design import (
    semantic_alignment_report,
    validate_ui_first,
    write_ui_flow,
)


SOURCE = Path("output/그래프라그 방나누기/LLM+라그/1차/graphrag_root/output")
OUTPUT = Path("output/그래프라그 방나누기/LLM+라그/1차(UI우선)")
JSON_PATH = OUTPUT / "UI우선_방설계.json"
MAX_CORE_SHARE = 0.30
MAX_SUPPORTING_SHARE = 0.30

MISSING_PLACEMENTS: dict[int, int] = {}


def share_limit(total: int, share: float) -> int:
    if total <= 0:
        return 0
    return max(1, int(total * share))


def cap_core_entities(result: dict, max_core_share: float = MAX_CORE_SHARE) -> dict:
    total_core = sum(
        1
        for room in result.get("rooms", [])
        for entity in room.get("entities", [])
        if entity.get("visibility") == "core"
    )
    max_core = share_limit(total_core, max_core_share)
    for room in result.get("rooms", []):
        core = [entity for entity in room.get("entities", []) if entity.get("visibility") == "core"]
        if len(core) <= max_core:
            continue
        keep = {
            int(entity["entity_id"])
            for entity in sorted(
                core,
                key=lambda entity: (
                    int(entity.get("degree", 0) or 0),
                    int(entity.get("frequency", 0) or 0),
                ),
                reverse=True,
            )[:max_core]
        }
        demoted = []
        for entity in room.get("entities", []):
            if entity.get("visibility") == "core" and int(entity["entity_id"]) not in keep:
                entity["visibility"] = "supporting"
                entity["reason"] = (
                    str(entity.get("reason", ""))
                    + " / UI 우선 정책: core 과밀로 supporting 처리"
                ).strip(" /")
                demoted.append(int(entity["entity_id"]))
        if demoted:
            room.setdefault("risk_flags", []).append(
                f"UI core 밀도 조정: 전체 core 대비 {max_core_share:.0%} 초과로 core {len(demoted)}개를 supporting으로 낮춤"
            )
    return result


def cap_supporting_entities(
    result: dict, max_supporting_share: float = MAX_SUPPORTING_SHARE
) -> dict:
    total_supporting = sum(
        1
        for room in result.get("rooms", [])
        for entity in room.get("entities", [])
        if entity.get("visibility") == "supporting"
    )
    max_supporting = share_limit(total_supporting, max_supporting_share)
    for room in result.get("rooms", []):
        supporting = [
            entity for entity in room.get("entities", []) if entity.get("visibility") == "supporting"
        ]
        if len(supporting) <= max_supporting:
            continue
        keep = {
            int(entity["entity_id"])
            for entity in sorted(
                supporting,
                key=lambda entity: (
                    int(entity.get("degree", 0) or 0),
                    int(entity.get("frequency", 0) or 0),
                ),
                reverse=True,
            )[:max_supporting]
        }
        demoted = []
        for entity in room.get("entities", []):
            if entity.get("visibility") == "supporting" and int(entity["entity_id"]) not in keep:
                entity["visibility"] = "search_only"
                entity["reason"] = (
                    str(entity.get("reason", ""))
                    + " / UI 우선 정책: supporting 과밀로 search_only 처리"
                ).strip(" /")
                demoted.append(int(entity["entity_id"]))
        if demoted:
            room.setdefault("risk_flags", []).append(
                f"UI supporting 밀도 조정: 전체 supporting 대비 {max_supporting_share:.0%} 초과로 supporting {len(demoted)}개를 search_only로 낮춤"
            )
    return result


def normalize_coverage(result: dict, communities: list) -> dict:
    all_ids = {community.cid for community in communities}
    owner: dict[int, int] = {}
    for room in result.get("rooms", []):
        room_no = int(room["room_no"])
        normalized = []
        for cid in room.get("source_communities", []):
            cid = int(cid)
            if cid not in all_ids:
                continue
            if cid in owner:
                continue
            owner[cid] = room_no
            normalized.append(cid)
        room["source_communities"] = normalized

    by_cid = {community.cid: community for community in communities}

    def best_room_for(community) -> dict:
        community_tokens = tokenize(f"{community.title} {community.summary}")
        best = None
        best_score = -1.0
        for room in result.get("rooms", []):
            room_tokens = tokenize(
                " ".join(
                    [
                        str(room.get("title", "")),
                        str(room.get("learning_flow", "")),
                        str(room.get("ui_design_reason", "")),
                    ]
                )
            )
            union = community_tokens | room_tokens
            score = len(community_tokens & room_tokens) / len(union) if union else 0.0
            if score > best_score:
                best = room
                best_score = score
        return best or result["rooms"][0]

    missing_ids = sorted(all_ids - set(owner))
    for cid in missing_ids:
        if cid in owner:
            continue
        room = best_room_for(by_cid[cid])
        room.setdefault("source_communities", []).append(cid)
        room.setdefault("background_communities", []).append(
            {
                "community_id": cid,
                "reason": "누락 방지를 위해 방 제목/학습 흐름과의 상대 유사도가 가장 높은 방에 GraphRAG 답변/검색용 background 자료로 보존",
            }
        )
        community = by_cid[cid]
        room.setdefault("subzones", []).append(
            {
                "title": community.title,
                "source_communities": [cid],
                "entity_ids": sorted(community.entity_ids),
            }
        )
        room.setdefault("risk_flags", []).append(
            f"backend coverage 보정: 누락 커뮤니티 {cid}를 상대 유사도 기준 background로 배치함"
        )
    return result


def main() -> None:
    communities, entities, relationships = load_inputs(SOURCE)
    _, entities_by_id = build_payload(communities, entities, relationships)
    result = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    result = normalize_coverage(result, communities)
    result = enrich_entities(result, entities_by_id)
    result = cap_core_entities(result, MAX_CORE_SHARE)
    result = cap_supporting_entities(result, MAX_SUPPORTING_SHARE)
    result = remove_duplicate_entities(result)
    result = enrich_entities(result, entities_by_id)
    validation = validate_ui_first(
        result,
        {community.cid for community in communities},
        max_core_share=MAX_CORE_SHARE,
        max_supporting_share=MAX_SUPPORTING_SHARE,
    )
    alignment = semantic_alignment_report(result, communities)
    result["validation"] = validation
    result["semantic_alignment"] = alignment
    result["ui_first_local_repair"] = {
        "policy": "Keep UI rooms clean; repair only backend community coverage and ratio-based visible density.",
        "missing_placements": MISSING_PLACEMENTS,
        "max_core_share": MAX_CORE_SHARE,
        "max_supporting_share": MAX_SUPPORTING_SHARE,
    }
    JSON_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(result, validation, OUTPUT / "UI우선_방설계.md")
    write_ui_flow(OUTPUT / "UI우선_플로우_정리.md", str(SOURCE))
    generate_html(
        result,
        validation,
        OUTPUT / "UI우선_방_엔티티_시각화.html",
        title="LLM+라그 UI 우선 방 설계",
    )
    print(f"Validation: {validation}")


if __name__ == "__main__":
    main()
