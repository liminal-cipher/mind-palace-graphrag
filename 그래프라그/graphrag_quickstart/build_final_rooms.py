from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_BASE_GLOB = "output/*/gpt4.1mini/10차_프롬프트/10차(수정)"

def find_base() -> Path:
    matches = sorted(Path(".").glob(DEFAULT_BASE_GLOB))
    if not matches:
        raise FileNotFoundError(DEFAULT_BASE_GLOB)
    return matches[-1]


def parse_final_rooms(judgement_text: str) -> list[dict[str, Any]]:
    marker = "## 6. 최종 3D 기억방 구성안"
    if marker not in judgement_text:
        raise ValueError("Could not find final room section in judgement file.")
    section = judgement_text.split(marker, 1)[1]
    room_blocks = re.split(r"\n(?=\d+\.\s+)", section.strip())

    rooms = []
    for block in room_blocks:
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        match = re.match(r"(\d+)\.\s+(.+)", lines[0].strip())
        if not match:
            continue
        room_no = int(match.group(1))
        room = {
            "room_no": room_no,
            "title": clean_text(match.group(2)),
            "period_order": "",
            "core_content": "",
            "main_entities": [],
            "subzones": [],
            "source_communities": [],
        }
        current_key = None
        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("- 시대/순서:"):
                current_key = "period_order"
                room[current_key] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("- 핵심 내용:"):
                current_key = "core_content"
                room[current_key] = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("- 주요 엔티티:"):
                current_key = "main_entities"
                values = stripped.split(":", 1)[1].strip()
                room[current_key] = split_csv(values)
            elif stripped.startswith("- 하위 구역:"):
                current_key = "subzones"
                inline = stripped.split(":", 1)[1].strip()
                if inline:
                    room["subzones"] = split_csv(inline)
            elif stripped.startswith("- 원본 커뮤니티:"):
                current_key = "source_communities"
                inline = stripped.split(":", 1)[1].strip()
                if inline:
                    room["source_communities"] = extract_ids(inline)
            elif stripped.startswith("- ") and current_key == "subzones":
                room["subzones"].append(stripped[2:].strip())
            elif stripped.startswith("- ") and current_key == "source_communities":
                room["source_communities"].extend(extract_ids(stripped))
        room["source_communities"] = sorted(set(room["source_communities"]))
        rooms.append(room)
    return rooms


def reconcile_source_communities(
    rooms: list[dict[str, Any]], original: dict[int, dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Assign every original community to exactly one final room.

    The LLM is allowed to propose mappings, but this verifier prevents duplicate
    or missing community IDs by re-scoring all original communities against all
    final rooms.
    """
    proposed = {
        cid: room["room_no"]
        for room in rooms
        for cid in room.get("source_communities", [])
        if cid in original
    }
    assignments: dict[int, int] = {}
    scores: dict[int, float] = {}
    for cid, info in original.items():
        best_room_no = None
        best_score = -1.0
        for room in rooms:
            score = community_room_score(info, room)
            if proposed.get(cid) == room["room_no"]:
                score += 0.08
            if score > best_score:
                best_score = score
                best_room_no = room["room_no"]
        if best_room_no is not None:
            assignments[cid] = best_room_no
            scores[cid] = round(best_score, 4)

    by_room: dict[int, list[int]] = {room["room_no"]: [] for room in rooms}
    for cid, room_no in assignments.items():
        by_room.setdefault(room_no, []).append(cid)
    for room in rooms:
        room["source_communities"] = sorted(by_room.get(room["room_no"], []))

    assigned_ids = sorted(assignments)
    diagnostics = {
        "method": "lexical verifier with small LLM-proposal bonus",
        "assigned_count": len(assigned_ids),
        "missing_after_reconcile": sorted(set(original) - set(assigned_ids)),
        "duplicate_after_reconcile": [],
        "assignment_scores": scores,
    }
    return rooms, diagnostics


def community_room_score(info: dict[str, Any], room: dict[str, Any]) -> float:
    community_text = " ".join(
        [info.get("title", ""), info.get("summary", "")]
    )
    room_text = " ".join(
        [
            room.get("title", ""),
            room.get("period_order", ""),
            room.get("core_content", ""),
            " ".join(room.get("main_entities", [])),
            " ".join(room.get("subzones", [])),
        ]
    )
    left = tokenize(community_text)
    right = tokenize(room_text)
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    return (overlap / len(left | right)) + (overlap / max(1, len(left))) * 0.35


def tokenize(text: str) -> set[str]:
    stopwords = {
        "조선",
        "시대",
        "전기",
        "후기",
        "중기",
        "초기",
        "관련",
        "중심",
        "역할",
        "정책",
        "제도",
        "체계",
        "사회",
        "정치",
        "경제",
        "문화",
        "학습",
    }
    return {
        token
        for token in re.findall(r"[가-힣A-Za-z0-9]+", text or "")
        if len(token) >= 2 and token not in stopwords
    }


def split_csv(value: str) -> list[str]:
    if not value:
        return []
    return [clean_text(item) for item in value.split(",") if item.strip()]


def clean_text(value: str) -> str:
    return value.strip().strip("*").strip()


def extract_ids(value: str) -> list[int]:
    ids = []
    for token in re.findall(r"\b\d+\b", value):
        ids.append(int(token))
    return ids


def load_original_communities(base: Path) -> dict[int, dict[str, Any]]:
    reports = pd.read_parquet(base / "community_reports.parquet")
    result = {}
    for row in reports.sort_values("community").itertuples(index=False):
        result[int(row.community)] = {
            "community": int(row.community),
            "title": str(row.title),
            "size": int(row.size),
            "summary": str(row.summary or ""),
        }
    return result


def extract_anomaly_section(judgement_text: str) -> str:
    if "## 5. 이상 엔티티 처리" not in judgement_text:
        return ""
    section = judgement_text.split("## 5. 이상 엔티티 처리", 1)[1]
    if "## 6. 최종 3D 기억방 구성안" in section:
        section = section.split("## 6. 최종 3D 기억방 구성안", 1)[0]
    return section.strip()


def build_final_markdown(
    rooms: list[dict[str, Any]],
    original: dict[int, dict[str, Any]],
    anomaly_section: str,
    diagnostics: dict[str, Any],
) -> str:
    lines = [
        "# 최종 방 구성안 - GPT-5.4 Mini 후처리 반영본",
        "",
        "이 파일은 원본 GraphRAG 결과를 직접 수정한 것이 아니라, `merge_judgement_gpt5.4mini.md`의 판단을 반영해 별도로 정리한 최종 후보본입니다.",
        "",
        "## 요약",
        "",
        f"- 원본 커뮤니티: {len(original)}개",
        f"- 최종 방 후보: {len(rooms)}개",
        "- 원본 parquet/txt 파일: 수정하지 않음",
        f"- 원본 커뮤니티 자동 배치 검증: {diagnostics['assigned_count']}/{len(original)}개 배치",
        f"- 검증 후 누락 ID: {diagnostics['missing_after_reconcile'] or '없음'}",
        f"- 검증 후 중복 ID: {diagnostics['duplicate_after_reconcile'] or '없음'}",
        "",
        "## 최종 3D 기억방",
    ]
    for room in rooms:
        source_items = [
            f"{cid}: {original[cid]['title']} ({original[cid]['size']})"
            for cid in room["source_communities"]
            if cid in original
        ]
        lines.extend(
            [
                "",
                f"### 방 {room['room_no']}: {room['title']}",
                f"- 시대/순서: {room['period_order']}",
                f"- 핵심 내용: {room['core_content']}",
                f"- 주요 엔티티: {', '.join(room['main_entities'])}",
                f"- 하위 구역: {', '.join(room['subzones'])}",
                "- 원본 커뮤니티:",
            ]
        )
        for item in source_items:
            lines.append(f"  - {item}")

    lines.extend(["", "## 이상 엔티티 처리 지시"])
    if anomaly_section:
        lines.append("")
        lines.append(anomaly_section)
    else:
        lines.append("- 이상 엔티티 처리 섹션을 찾지 못했습니다.")
    return "\n".join(lines) + "\n"


def build_comparison_markdown(
    rooms: list[dict[str, Any]], original: dict[int, dict[str, Any]]
) -> str:
    community_to_room = {}
    for room in rooms:
        for cid in room["source_communities"]:
            community_to_room[cid] = room

    lines = [
        "# 원본 GraphRAG vs 최종 후처리본 비교",
        "",
        "## 변화 요약",
        "",
        f"- 원본 GraphRAG 커뮤니티: {len(original)}개",
        f"- 최종 방 후보: {len(rooms)}개",
        "- 처리 방식: 원본은 보존하고, 최종 방 구성 파일을 별도 생성",
        "",
        "## 원본 커뮤니티별 최종 배치",
        "",
        "| 원본 ID | 원본 제목 | 엔티티 수 | 최종 방 | 처리 성격 |",
        "|---:|---|---:|---|---|",
    ]
    for cid, info in sorted(original.items()):
        room = community_to_room.get(cid)
        if room is None:
            final_room = "미배치"
            action = "검토 필요"
        else:
            final_room = f"방 {room['room_no']}: {room['title']}"
            action = classify_action(cid, room, original)
        lines.append(
            f"| {cid} | {info['title']} | {info['size']} | {final_room} | {action} |"
        )

    lines.extend(["", "## 최종 방별 원본 커뮤니티 묶음"])
    for room in rooms:
        titles = [
            f"{cid}: {original[cid]['title']}"
            for cid in room["source_communities"]
            if cid in original
        ]
        lines.extend(
            [
                "",
                f"### 방 {room['room_no']}: {room['title']}",
                f"- 원본 커뮤니티 수: {len(titles)}",
            ]
        )
        for title in titles:
            lines.append(f"- {title}")
    return "\n".join(lines) + "\n"


def classify_action(cid: int, room: dict[str, Any], original: dict[int, dict[str, Any]]) -> str:
    sources = room["source_communities"]
    if len(sources) == 1:
        return "유지"
    if original[cid]["size"] <= 4:
        return "작은 커뮤니티 병합"
    if cid in {0, 3, 5, 16}:
        return "큰 커뮤니티 분할/하위구역"
    return "주제별 재배치"


def main() -> None:
    base = find_base()
    judgement_path = base / "merge_judgement_gpt5.4mini.md"
    judgement_text = judgement_path.read_text(encoding="utf-8")
    original = load_original_communities(base)
    rooms = parse_final_rooms(judgement_text)
    rooms, diagnostics = reconcile_source_communities(rooms, original)
    anomaly_section = extract_anomaly_section(judgement_text)

    final_payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_judgement": str(judgement_path),
        "original_community_count": len(original),
        "final_room_count": len(rooms),
        "rooms": rooms,
        "diagnostics": diagnostics,
        "anomaly_section": anomaly_section,
    }

    final_md_path = base / "final_rooms_gpt5.4mini.md"
    final_json_path = base / "final_rooms_gpt5.4mini.json"
    comparison_path = base / "comparison_original_vs_final.md"

    final_md_path.write_text(
        build_final_markdown(rooms, original, anomaly_section, diagnostics),
        encoding="utf-8",
    )
    final_json_path.write_text(
        json.dumps(final_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    comparison_path.write_text(
        build_comparison_markdown(rooms, original), encoding="utf-8"
    )

    print(f"Wrote: {final_md_path}")
    print(f"Wrote: {final_json_path}")
    print(f"Wrote: {comparison_path}")


if __name__ == "__main__":
    main()
