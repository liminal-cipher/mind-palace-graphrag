from __future__ import annotations

import json
from pathlib import Path

from build_12_llm_room_design import (
    build_payload,
    enrich_entities,
    generate_html,
    load_inputs,
    remove_duplicate_entities,
    validate_rooms,
    write_markdown,
)


SOURCE = Path("output/그래프라그 방나누기/LLM+라그/1차/graphrag_root/output")
OUTPUT = Path("output/그래프라그 방나누기/LLM+라그/1차(수정)")
JSON_PATH = OUTPUT / "1차수정_LLM방재설계.json"

# These are not arbitrary catch-all placements.
# They are semantic placements for the small communities the LLM repeatedly omitted:
# 3: 조운/곡물 보관 -> 국가 운영/제도 방
# 5: 화성/거중기 -> 정조 개혁/후기 실학·기술 방
# 17: 정상기/동국지도 -> 후기 실학·지리학 방
PLACEMENTS = {
    3: 2,
    5: 6,
    17: 6,
}


def main() -> None:
    communities, entities, relationships = load_inputs(SOURCE)
    _, entities_by_id = build_payload(communities, entities, relationships)
    by_cid = {community.cid: community for community in communities}
    result = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    for cid, room_no in PLACEMENTS.items():
        community = by_cid[cid]
        room = next(room for room in result["rooms"] if int(room["room_no"]) == room_no)
        if cid not in [int(item) for item in room.get("source_communities", [])]:
            room.setdefault("source_communities", []).append(cid)
        room.setdefault("subzones", []).append(
            {
                "title": community.title,
                "source_communities": [cid],
                "entity_ids": sorted(community.entity_ids),
            }
        )
        room.setdefault("risk_flags", []).append(
            f"LLM이 2회 누락한 커뮤니티 {cid}를 제목/요약 의미 기준으로 이 방 하위구역에 배치함: {community.title}"
        )
        existing_ids = {int(entity["entity_id"]) for entity in room.get("entities", [])}
        for entity_id in sorted(community.entity_ids):
            if entity_id in existing_ids or entity_id not in entities_by_id:
                continue
            entity = entities_by_id[entity_id]
            room.setdefault("entities", []).append(
                {
                    "entity_id": entity_id,
                    "title": entity["title"],
                    "visibility": "search_only",
                    "reason": f"누락 커뮤니티 {cid} 보존용 검색 전용 엔티티",
                }
            )

    result = enrich_entities(result, entities_by_id)
    result = remove_duplicate_entities(result)
    result = enrich_entities(result, entities_by_id)
    validation = validate_rooms(result, {community.cid for community in communities})
    result["validation"] = validation
    result["missing_community_patch_policy"] = {
        "reason": "GPT-5.4 mini semantic repair omitted the same small communities twice. Applied deterministic semantic placement and marked risk flags.",
        "placements": PLACEMENTS,
    }
    JSON_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(result, validation, OUTPUT / "1차수정_LLM방재설계.md")
    generate_html(
        result,
        validation,
        OUTPUT / "1차수정_방_엔티티_시각화.html",
        title="LLM+라그 1차(수정) 방 재설계",
    )
    print(f"Validation: {validation}")


if __name__ == "__main__":
    main()
