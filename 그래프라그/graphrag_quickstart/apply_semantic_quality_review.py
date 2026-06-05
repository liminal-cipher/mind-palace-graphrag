from __future__ import annotations

import json
from pathlib import Path

from build_final_rooms import (
    build_comparison_markdown,
    build_final_markdown,
    extract_anomaly_section,
    load_original_communities,
)


DEFAULT_BASE_GLOB = "output/*/gpt4.1mini/10차_프롬프트/10차(수정)"


def find_base() -> Path:
    matches = sorted(Path(".").glob(DEFAULT_BASE_GLOB))
    if not matches:
        raise FileNotFoundError(DEFAULT_BASE_GLOB)
    return matches[-1]


def move_community(rooms: list[dict], community_id: int, target_room_no: int) -> bool:
    target = None
    moved = False
    for room in rooms:
        room["source_communities"] = [
            int(cid)
            for cid in room.get("source_communities", [])
            if int(cid) != community_id
        ]
        if int(room["room_no"]) == target_room_no:
            target = room
    if target is None:
        return False
    target.setdefault("source_communities", []).append(community_id)
    moved = True
    for room in rooms:
        room["source_communities"] = sorted(set(map(int, room.get("source_communities", []))))
    return moved


def apply_review_actions(final_data: dict, review: dict) -> dict:
    applied = []
    skipped = []
    for room_review in review.get("room_reviews", []):
        for action in room_review.get("recommended_actions", []):
            community = action.get("community")
            target_room_no = action.get("target_room_no")
            action_type = action.get("action")
            if community is None:
                skipped.append({**action, "reason_skipped": "missing community"})
                continue
            if action_type in {"move", "split_out"}:
                if target_room_no is None:
                    skipped.append({**action, "reason_skipped": "missing target_room_no"})
                    continue
                ok = move_community(
                    final_data["rooms"], int(community), int(target_room_no)
                )
                if ok:
                    applied.append(action)
                else:
                    skipped.append({**action, "reason_skipped": "target room not found"})
            elif action_type == "keep":
                applied.append(action)
            else:
                skipped.append({**action, "reason_skipped": "unsupported action"})

    final_data["semantic_quality_review_applied"] = {
        "applied_actions": applied,
        "skipped_actions": skipped,
    }
    return final_data


def validate_ids(final_data: dict) -> dict:
    ids = [
        int(cid)
        for room in final_data["rooms"]
        for cid in room.get("source_communities", [])
    ]
    return {
        "missing": sorted(set(range(30)) - set(ids)),
        "duplicates": sorted({cid for cid in ids if ids.count(cid) > 1}),
    }


def main() -> None:
    base = find_base()
    final_json_path = base / "final_rooms_gpt5.4mini.json"
    final_md_path = base / "final_rooms_gpt5.4mini.md"
    comparison_path = base / "comparison_original_vs_final.md"
    review_json_path = base / "semantic_quality_review_gpt5.4mini.json"
    judgement_path = base / "merge_judgement_gpt5.4mini.md"

    final_data = json.loads(final_json_path.read_text(encoding="utf-8"))
    review_payload = json.loads(review_json_path.read_text(encoding="utf-8"))
    review = review_payload.get("review", {})
    original = load_original_communities(base)

    final_data = apply_review_actions(final_data, review)
    final_data["semantic_quality_review_applied"]["id_validation"] = validate_ids(final_data)

    anomaly_section = extract_anomaly_section(judgement_path.read_text(encoding="utf-8"))
    final_json_path.write_text(
        json.dumps(final_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    final_md_path.write_text(
        build_final_markdown(
            final_data["rooms"],
            original,
            anomaly_section,
            final_data.get("diagnostics", {}),
        ),
        encoding="utf-8",
    )
    comparison_path.write_text(
        build_comparison_markdown(final_data["rooms"], original), encoding="utf-8"
    )

    print(f"Updated: {final_json_path}")
    print(f"Updated: {final_md_path}")
    print(f"Updated: {comparison_path}")
    print(final_data["semantic_quality_review_applied"])


if __name__ == "__main__":
    main()
