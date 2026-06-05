from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path(
    "output/그래프라그 방나누기/gpt4.1mini/11차/11차_최종방_엔티티분류.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair 11th output room/subzone consistency without LLM."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def validate(rooms: list[dict[str, Any]], community_ids: set[int]) -> dict[str, Any]:
    assigned = []
    subzone_out = []
    for room in rooms:
        room_no = room.get("room_no")
        room_sources = {int(cid) for cid in room.get("source_communities", [])}
        assigned.extend(room_sources)
        for subzone in room.get("subzones", []):
            for cid in [int(item) for item in subzone.get("source_communities", [])]:
                if cid not in room_sources:
                    subzone_out.append(
                        {
                            "room_no": room_no,
                            "subzone_title": subzone.get("title", ""),
                            "community": cid,
                        }
                    )
    counts = Counter(assigned)
    return {
        "missing": sorted(community_ids - set(assigned)),
        "duplicates": sorted(cid for cid, count in counts.items() if count > 1),
        "unknown": sorted(set(assigned) - community_ids),
        "subzone_out_of_room_ids": subzone_out,
        "valid": not (
            sorted(community_ids - set(assigned))
            or sorted(cid for cid, count in counts.items() if count > 1)
            or sorted(set(assigned) - community_ids)
            or subzone_out
        ),
    }


def repair_subzones(rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions = []
    for room in rooms:
        room_no = room.get("room_no")
        room_sources = {int(cid) for cid in room.get("source_communities", [])}
        new_subzones = []
        represented = set()
        for subzone in room.get("subzones", []):
            original = [int(cid) for cid in subzone.get("source_communities", [])]
            cleaned = sorted({cid for cid in original if cid in room_sources})
            removed = sorted(set(original) - set(cleaned))
            if removed:
                actions.append(
                    {
                        "action": "remove_subzone_out_of_room_ids",
                        "room_no": room_no,
                        "subzone_title": subzone.get("title", ""),
                        "removed_communities": removed,
                    }
                )
            if not cleaned:
                actions.append(
                    {
                        "action": "drop_empty_subzone_after_sync",
                        "room_no": room_no,
                        "subzone_title": subzone.get("title", ""),
                    }
                )
                continue
            subzone["source_communities"] = cleaned
            represented.update(cleaned)
            new_subzones.append(subzone)
        for cid in sorted(room_sources - represented):
            new_subzones.append(
                {
                    "title": f"커뮤니티 {cid}",
                    "source_communities": [cid],
                    "purpose": "방 source_communities에는 있으나 하위구역에 없어 로직으로 추가",
                }
            )
            actions.append(
                {
                    "action": "add_missing_subzone_for_room_source",
                    "room_no": room_no,
                    "community": cid,
                }
            )
        room["subzones"] = new_subzones
    return actions


def write_markdown(payload: dict[str, Any], md_path: Path) -> None:
    rooms = payload["rooms"]
    validation = payload.get("no_llm_repair_validation_after", {})
    repair_actions = payload.get("no_llm_repair_actions", [])
    lines = [
        "# 11차: 5개 이내 상위 방 구성 및 엔티티 우선순위",
        "",
        "## 1. 방 구성 결과",
        "",
        f"- 최종 방 수: {len(rooms)}",
        f"- 누락 커뮤니티: {validation.get('missing', [])}",
        f"- 중복 커뮤니티: {validation.get('duplicates', [])}",
        f"- 알 수 없는 커뮤니티: {validation.get('unknown', [])}",
        f"- 하위구역 방 외부 ID: {validation.get('subzone_out_of_room_ids', [])}",
        f"- LLM 없이 하위구역 정합성 보정: {len(repair_actions)}건",
        "",
    ]
    for room in rooms:
        lines.extend(
            [
                f"### 방 {room['room_no']}: {room['title']}",
                f"- 학습 흐름: {room.get('learning_flow', '')}",
                f"- 원본 커뮤니티: {room.get('source_communities', [])}",
                f"- 엔티티 수: {room.get('entity_count', 0)}",
                f"- 표시 등급 요약: {room.get('visibility_summary', {})}",
                "- 하위 구역:",
            ]
        )
        for subzone in room.get("subzones", []):
            lines.append(
                f"  - {subzone.get('title')} / communities={subzone.get('source_communities', [])}"
            )
        for level in ["core", "supporting", "search_only"]:
            selected = [
                item["title"]
                for item in room.get("entities", [])
                if item.get("visibility") == level
            ][:25]
            lines.append(f"- {level}: {', '.join(selected)}")
        lines.append("")
    lines.extend(["## 2. LLM 없이 수행한 정합성 보정", ""])
    if repair_actions:
        for action in repair_actions:
            lines.append(f"- {action}")
    else:
        lines.append("- 보정 없음")
    lines.extend(["", "## 3. 주의", ""])
    lines.append(
        "- 이 파일은 기존 11차 LLM 결과를 재판단하지 않고, 방/하위구역 ID 정합성만 LLM 없이 보정한 결과입니다."
    )
    lines.append(
        "- 방 구성 자체를 다시 평가하려면 weak edge를 방 병합에서 제외한 새 실행이 필요합니다."
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    rooms = payload["rooms"]
    community_ids = set(range(30))
    before = validate(rooms, community_ids)
    actions = repair_subzones(rooms)
    after = validate(rooms, community_ids)
    payload["no_llm_repaired_at"] = datetime.now().isoformat(timespec="seconds")
    payload["no_llm_repair_validation_before"] = before
    payload["no_llm_repair_validation_after"] = after
    payload["no_llm_repair_actions"] = actions

    if args.overwrite:
        json_path = args.input
        md_path = args.input.with_suffix(".md")
    else:
        json_path = args.input.with_name("11차_최종방_엔티티분류_repaired_no_llm.json")
        md_path = args.input.with_name("11차_최종방_엔티티분류_repaired_no_llm.md")

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_markdown(payload, md_path)
    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")
    print(f"Before: {before}")
    print(f"After: {after}")
    print(f"Actions: {actions}")


if __name__ == "__main__":
    main()
