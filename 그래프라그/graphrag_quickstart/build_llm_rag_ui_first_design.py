from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from build_12_llm_room_design import (
    build_payload,
    call_model,
    compact_text,
    enrich_entities,
    extract_json_object,
    generate_html,
    load_config,
    load_dotenv,
    load_inputs,
    remove_duplicate_entities,
    tokenize,
    write_markdown,
)


DEFAULT_SOURCE = Path("output/그래프라그 방나누기/LLM+라그/1차/graphrag_root/output")
DEFAULT_OUTPUT = Path("output/그래프라그 방나누기/LLM+라그/1차(UI우선)")
DEFAULT_CONFIG = Path("output/그래프라그 방나누기/gpt4.1mini/NEW/settings_gpt5.4mini.yaml")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build UI-first rooms from GraphRAG evidence.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--min-rooms", type=int, default=4)
    parser.add_argument("--max-rooms", type=int, default=6)
    parser.add_argument("--max-core-share", type=float, default=0.30)
    parser.add_argument("--max-supporting-share", type=float, default=0.30)
    parser.add_argument("--supporting-review-threshold", type=int, default=12)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--top-p", type=float, default=None)
    parser.add_argument("--max-tokens", type=int, default=12000)
    parser.add_argument("--coverage-repair-attempts", type=int, default=2)
    return parser.parse_args()


def percentile_rank(value: float, values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(1 for item in values if item <= value) / len(values), 4)


def scale_hint(percentile: float) -> str:
    if percentile <= 0.25:
        return "small_background_candidate"
    if percentile >= 0.75:
        return "major_visible_candidate"
    return "normal_candidate"


def summarize_communities(communities: list[Any]) -> list[dict[str, Any]]:
    sizes = [float(community.size) for community in communities]
    return [
        {
            "community_id": community.cid,
            "title": community.title,
            "summary": compact_text(community.summary, 520),
            "size": community.size,
            "size_percentile": percentile_rank(float(community.size), sizes),
            "scale_hint": scale_hint(percentile_rank(float(community.size), sizes)),
            "rank": round(community.rank, 4),
            "entity_ids": sorted(community.entity_ids),
        }
        for community in communities
    ]


def make_prompt(
    payload: dict[str, Any],
    communities: list[Any],
    min_rooms: int,
    max_rooms: int,
) -> str:
    return f"""
[범용 UI 설계 지침]
- 이 프롬프트는 특정 과목 전용이 아닙니다. 문서 내용에서 도메인과 학습 목적을 추론하세요.
- 고정 개수 기준으로 방/엔티티를 자르지 말고, 이 문서 안에서의 상대적 중요도와 규모를 보세요.
- community의 size_percentile과 scale_hint를 참고하세요.
- major_visible_candidate는 UI에 직접 보일 가능성이 큰 후보입니다.
- small_background_candidate는 background/search_only 후보입니다.
- 단, 작더라도 문서의 핵심 개념이면 visible/core로 올릴 수 있습니다. 이 경우 이유를 적으세요.
- 방 제목과 visible_communities는 직접적으로 맞아야 합니다.
- visible에 넣으면 방 제목이 흐려지는 항목은 background로 보내세요.
- background는 버리는 것이 아니라 GraphRAG 답변/검색용 근거로 보존하는 것입니다.
- 방끼리 주제가 겹치면 제목이나 learning_flow로 차이를 분명히 하세요.

아래는 GraphRAG가 만든 원본 지식망 근거입니다.
이번 목표는 "정확한 분류표"가 아니라 "사용자가 보기 좋은 3D 학습방 UI"를 만드는 것입니다.

중요한 역할 분리:
- GraphRAG는 답변용 지식망입니다.
- 3D 방은 사용자가 보는 학습 UI입니다.
- 따라서 방은 깔끔함, 시대 흐름, 핵심 항목 노출을 우선합니다.
- 방 배치가 GraphRAG 커뮤니티 경계와 1:1로 일치할 필요는 없습니다.
- 다만 모든 community_id/entity_id는 내부 근거로 유지해야 합니다.

방 설계 원칙:
- 방 개수는 {min_rooms}~{max_rooms}개 사이에서 고르세요.
- 방을 줄이는 것이 목적이 아니라, 사용자가 이해하기 쉬운 구조가 목적입니다.
- 특정 방에 core 엔티티가 과도하게 몰리지 않게 하세요.
- 특정 방에 supporting 엔티티가 과도하게 몰리지 않게 하세요.
- 기준은 고정 개수가 아니라 전체 표시 엔티티 대비 비율입니다.
- UI에 어울리지 않는 작은 주제는 억지로 눈에 띄게 넣지 말고 background/search_only로 보존하세요.
- 조운, 화성/거중기, 동국지도, 동사강목 같은 작은 주제는 독립 방이 아니라 관련 큰 방의 background 자료가 될 수 있습니다.
- 단, background로 보낸 이유를 적으세요.
- 방 제목은 학습자가 바로 이해할 수 있는 이름이어야 합니다.
- 모든 원본 커뮤니티 0~{len(communities)-1}은 정확히 한 번 coverage에 포함되어야 합니다.

출력은 JSON만 하세요. 마크다운 금지.

Visibility quality gate:
- Do not create search_only just to satisfy a quota.
- Every supporting entity must earn its place in the learner-facing UI.
- Keep an entity as supporting only when it directly explains the room learning_flow, deepens a core entity, or is a meaningful clickable concept for the learner.
- Demote to search_only when the entity is mostly a passing textbook mention, a small example, a low-salience facility/component, a duplicated context item, or only weakly related to the room title.
- Be stricter when a room has many supporting entities. The supporting panel should stay compact and clear; weak but useful evidence belongs in search_only.
- In each entity reason, briefly explain why it is core, supporting, or search_only.

JSON 스키마:
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
      "ui_design_reason": "사용자에게 이 구조가 깔끔한 이유",
      "visible_communities": [0],
      "background_communities": [
        {{
          "community_id": 3,
          "reason": "UI에서는 숨기고 GraphRAG 답변 근거로 보존하는 이유"
        }}
      ],
      "source_communities": [0, 3],
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
          "title": "원본 엔티티명",
          "visibility": "core | supporting | search_only",
          "reason": "UI 표시 등급 이유"
        }}
      ],
      "risk_flags": ["사용자에게 표시할 애매한 배치"]
    }}
  ],
  "backend_only_communities": [
    {{
      "community_id": 3,
      "assigned_room_no": 2,
      "reason": "답변용 근거로만 보존하는 이유"
    }}
  ],
  "ambiguous_items_for_user_review": [
    {{
      "item_type": "community | entity",
      "id": 0,
      "current_room_no": 1,
      "reason": "UI에서 사용자 검토 표시가 필요한 이유"
    }}
  ],
  "self_check": {{
    "all_communities_covered": true,
    "duplicate_community_ids": [],
    "missing_community_ids": [],
    "notes": "자체 점검"
  }}
}}

원본 커뮤니티 목록:
{json.dumps(summarize_communities(communities), ensure_ascii=False, indent=2)}

GraphRAG 근거:
{json.dumps(payload, ensure_ascii=False)}
""".strip()


def validate_ui_first(
    result: dict[str, Any],
    community_ids: set[int],
    max_core_share: float = 0.30,
    max_supporting_share: float = 0.30,
) -> dict[str, Any]:
    seen: list[int] = []
    for room in result.get("rooms", []):
        ids = room.get("source_communities", [])
        if not ids:
            visible = [int(cid) for cid in room.get("visible_communities", [])]
            background = [
                int(item["community_id"])
                for item in room.get("background_communities", [])
                if "community_id" in item
            ]
            ids = visible + background
            room["source_communities"] = ids
        seen.extend(int(cid) for cid in ids)

    duplicate = sorted([cid for cid, count in Counter(seen).items() if count > 1])
    missing = sorted(community_ids - set(seen))
    unknown = sorted(set(seen) - community_ids)
    entity_seen: list[int] = []
    for room in result.get("rooms", []):
        for entity in room.get("entities", []):
            if "entity_id" in entity:
                entity_seen.append(int(entity["entity_id"]))
    duplicate_entities = sorted(
        [eid for eid, count in Counter(entity_seen).items() if count > 1]
    )
    room_counts = [
        {
            "room_no": room.get("room_no"),
            "title": room.get("title"),
            "core_count": sum(1 for e in room.get("entities", []) if e.get("visibility") == "core"),
            "supporting_count": sum(1 for e in room.get("entities", []) if e.get("visibility") == "supporting"),
            "search_only_count": sum(1 for e in room.get("entities", []) if e.get("visibility") == "search_only"),
            "visible_community_count": len(room.get("visible_communities", [])),
            "background_community_count": len(room.get("background_communities", [])),
        }
        for room in result.get("rooms", [])
    ]
    total_core = sum(item["core_count"] for item in room_counts)
    total_supporting = sum(item["supporting_count"] for item in room_counts)
    overloaded_ui_rooms = [
        {
            **item,
            "core_share": round(item["core_count"] / total_core, 4)
            if total_core
            else 0,
            "supporting_share": round(item["supporting_count"] / total_supporting, 4)
            if total_supporting
            else 0,
        }
        for item in room_counts
        if (total_core and item["core_count"] / total_core > max_core_share)
        or (
            total_supporting
            and item["supporting_count"] / total_supporting > max_supporting_share
        )
    ]
    return {
        "valid": not (missing or duplicate or unknown or duplicate_entities),
        "missing_community_ids": missing,
        "duplicate_community_ids": duplicate,
        "unknown_community_ids": unknown,
        "duplicate_entity_ids": duplicate_entities,
        "room_counts": room_counts,
        "overloaded_ui_rooms": overloaded_ui_rooms,
        "density_policy": {
            "max_core_share": max_core_share,
            "max_supporting_share": max_supporting_share,
        },
    }


def coverage_repair_prompt(
    result: dict[str, Any],
    validation: dict[str, Any],
    communities: list[Any],
) -> str:
    community_summaries = summarize_communities(communities)
    compact_rooms = [
        {
            "room_no": room.get("room_no"),
            "title": room.get("title"),
            "learning_flow": room.get("learning_flow"),
            "visible_communities": room.get("visible_communities", []),
            "background_communities": room.get("background_communities", []),
            "source_communities": room.get("source_communities", []),
        }
        for room in result.get("rooms", [])
    ]
    return f"""
You are repairing a UI-first GraphRAG room JSON after deterministic validation.

Repair only community coverage by making a single assignment table:
- Assign every original community_id to exactly one room_no.
- Choose exposure as "visible" only when the community directly defines the room title/learning_flow.
- Choose exposure as "background" when it is useful GraphRAG evidence but should not be learner-facing.
- Do not invent community IDs.
- Do not omit community IDs.
- Do not assign one community_id to multiple rooms.
- Return only the compact assignment JSON below. Do not return the full room JSON.
- No markdown.

Required output schema:
{{
  "assignments": [
    {{
      "community_id": 0,
      "room_no": 1,
      "exposure": "visible | background",
      "reason": "why this is the best single room placement"
    }}
  ],
  "repair_notes": "short explanation"
}}

Validation failure:
{json.dumps(validation, ensure_ascii=False, indent=2)}

Original communities:
{json.dumps(community_summaries, ensure_ascii=False, indent=2)}

Current JSON to repair:
{json.dumps({"rooms": compact_rooms}, ensure_ascii=False)}
""".strip()


def apply_coverage_repair_patch(
    result: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    fixed = json.loads(json.dumps(result, ensure_ascii=False))
    assignments_by_room: dict[int, dict[str, list[Any]]] = {}
    for item in patch.get("assignments", []):
        if "community_id" not in item or "room_no" not in item:
            continue
        room_no = int(item["room_no"])
        community_id = int(item["community_id"])
        exposure = str(item.get("exposure", "background")).strip().lower()
        reason = str(item.get("reason", "")).strip()
        bucket = assignments_by_room.setdefault(room_no, {"visible": [], "background": []})
        if exposure == "visible":
            bucket["visible"].append(community_id)
        else:
            bucket["background"].append({"community_id": community_id, "reason": reason})
    for room in fixed.get("rooms", []):
        room_no = int(room.get("room_no"))
        bucket = assignments_by_room.get(room_no, {"visible": [], "background": []})
        visible = bucket["visible"]
        background = bucket["background"]
        room["visible_communities"] = visible
        room["background_communities"] = background
        room["source_communities"] = visible + [item["community_id"] for item in background]
    fixed["coverage_repair_notes"] = patch.get("repair_notes", "")
    return fixed


def run_llm_coverage_repair(
    config: dict[str, Any],
    result: dict[str, Any],
    validation: dict[str, Any],
    communities: list[Any],
    entities_by_id: dict[int, Any],
    attempts: int,
    max_tokens: int,
    max_core_share: float,
    max_supporting_share: float,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    repair_logs: list[dict[str, Any]] = []
    community_ids = {community.cid for community in communities}
    repaired = result
    current_validation = validation
    for attempt_no in range(1, max(0, attempts) + 1):
        if current_validation.get("valid"):
            break
        if not (
            current_validation.get("missing_community_ids")
            or current_validation.get("duplicate_community_ids")
            or current_validation.get("unknown_community_ids")
        ):
            break
        prompt = coverage_repair_prompt(repaired, current_validation, communities)
        raw, usage = call_model(
            config,
            system=(
                "You repair GraphRAG UI room JSON coverage errors. "
                "Return corrected JSON only."
            ),
            user=prompt,
            max_tokens=max_tokens,
        )
        try:
            patch = extract_json_object(raw)
        except Exception as exc:
            repair_logs.append(
                {
                    "attempt": attempt_no,
                    "raw": raw,
                    "usage": usage.model_dump() if hasattr(usage, "model_dump") else str(usage),
                    "parse_error": str(exc),
                    "validation": current_validation,
                }
            )
            continue
        candidate = apply_coverage_repair_patch(repaired, patch)
        candidate = enrich_entities(candidate, entities_by_id)
        candidate = remove_duplicate_entities(candidate)
        candidate = enrich_entities(candidate, entities_by_id)
        candidate_validation = validate_ui_first(
            candidate,
            community_ids,
            max_core_share=max_core_share,
            max_supporting_share=max_supporting_share,
        )
        repair_logs.append(
            {
                "attempt": attempt_no,
                "raw": raw,
                "patch": patch,
                "usage": usage.model_dump() if hasattr(usage, "model_dump") else str(usage),
                "validation": candidate_validation,
            }
        )
        repaired = candidate
        current_validation = candidate_validation
    return repaired, current_validation, repair_logs


def semantic_alignment_report(result: dict[str, Any], communities: list[Any]) -> dict[str, Any]:
    by_id = {community.cid: community for community in communities}
    scores: list[dict[str, Any]] = []
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
        for cid in room.get("visible_communities", []):
            community = by_id.get(int(cid))
            if not community:
                continue
            community_tokens = tokenize(f"{community.title} {community.summary}")
            union = room_tokens | community_tokens
            score = len(room_tokens & community_tokens) / len(union) if union else 0.0
            scores.append(
                {
                    "room_no": room.get("room_no"),
                    "room_title": room.get("title"),
                    "community_id": int(cid),
                    "community_title": community.title,
                    "alignment_score": round(score, 4),
                }
            )
    if not scores:
        return {
            "policy": "No visible communities to score.",
            "low_alignment_candidates": [],
            "all_scores": [],
        }
    sorted_scores = sorted(item["alignment_score"] for item in scores)
    median = sorted_scores[len(sorted_scores) // 2]
    cutoff = median / 2 if median > 0 else 0
    low = [item for item in scores if item["alignment_score"] <= cutoff]
    return {
        "policy": "Relative title-visible-community alignment. Flags items at or below half the median token overlap.",
        "median_alignment_score": round(median, 4),
        "relative_cutoff": round(cutoff, 4),
        "low_alignment_candidates": low,
        "all_scores": scores,
    }


def share_limit(total: int, share: float) -> int:
    if total <= 0:
        return 0
    return max(1, int(total * share))


def enforce_ui_caps(
    result: dict[str, Any],
    max_core_share: float = 0.30,
    max_supporting_share: float = 0.30,
) -> dict[str, Any]:
    fixed = json.loads(json.dumps(result, ensure_ascii=False))
    total_core = sum(
        1
        for room in fixed.get("rooms", [])
        for entity in room.get("entities", [])
        if entity.get("visibility") == "core"
    )
    total_supporting = sum(
        1
        for room in fixed.get("rooms", [])
        for entity in room.get("entities", [])
        if entity.get("visibility") == "supporting"
    )
    max_core = share_limit(total_core, max_core_share)
    max_supporting = share_limit(total_supporting, max_supporting_share)
    for room in fixed.get("rooms", []):
        core = [e for e in room.get("entities", []) if e.get("visibility") == "core"]
        if len(core) > max_core:
            keep_ids = {
                int(e["entity_id"])
                for e in sorted(
                    core,
                    key=lambda e: (
                        int(e.get("degree", 0) or 0),
                        int(e.get("frequency", 0) or 0),
                    ),
                    reverse=True,
                )[:max_core]
            }
            demoted = []
            for entity in room.get("entities", []):
                if entity.get("visibility") == "core" and int(entity["entity_id"]) not in keep_ids:
                    entity["visibility"] = "supporting"
                    entity["reason"] = (
                        str(entity.get("reason", ""))
                        + " / UI 우선 표시 밀도 정책으로 supporting 처리"
                    ).strip(" /")
                    demoted.append(int(entity["entity_id"]))
            if demoted:
                room.setdefault("risk_flags", []).append(
                    f"UI 표시 밀도 조정: 전체 core 대비 비율 초과로 core {len(demoted)}개를 supporting으로 낮춤"
                )

        supporting = [e for e in room.get("entities", []) if e.get("visibility") == "supporting"]
        if len(supporting) <= max_supporting:
            continue
        keep_ids = {
            int(e["entity_id"])
            for e in sorted(
                supporting,
                key=lambda e: (int(e.get("degree", 0) or 0), int(e.get("frequency", 0) or 0)),
                reverse=True,
            )[:max_supporting]
        }
        demoted = []
        for entity in room.get("entities", []):
            if entity.get("visibility") == "supporting" and int(entity["entity_id"]) not in keep_ids:
                entity["visibility"] = "search_only"
                entity["reason"] = (
                    str(entity.get("reason", ""))
                    + " / UI 우선 표시 밀도 정책으로 search_only 처리"
                ).strip(" /")
                demoted.append(int(entity["entity_id"]))
        if demoted:
            room.setdefault("risk_flags", []).append(
                f"UI 표시 밀도 조정: 전체 supporting 대비 비율 초과로 supporting {len(demoted)}개를 search_only로 낮춤"
            )
    fixed["ui_density_policy"] = {
        "max_core_share": max_core_share,
        "max_supporting_share": max_supporting_share,
        "computed_max_core_per_room": max_core,
        "computed_max_supporting_per_room": max_supporting,
    }
    return fixed


def supporting_strength(room: dict[str, Any], entity: dict[str, Any]) -> tuple[int, list[str]]:
    room_text = " ".join(
        str(part)
        for part in [
            room.get("title", ""),
            room.get("learning_flow", ""),
            room.get("ui_design_reason", ""),
            room.get("design_reason", ""),
            " ".join(str(zone.get("title", "")) for zone in room.get("subzones", [])),
        ]
    )
    entity_text = " ".join(
        str(part)
        for part in [
            entity.get("title", ""),
            entity.get("type", ""),
            entity.get("reason", ""),
            entity.get("description", ""),
        ]
    )
    room_tokens = tokenize(room_text)
    entity_tokens = tokenize(entity_text)
    overlap = len(room_tokens & entity_tokens)
    degree = int(entity.get("degree", 0) or 0)
    frequency = int(entity.get("frequency", 0) or 0)
    reason = str(entity.get("reason", ""))

    score = 0
    signals: list[str] = []
    if overlap >= 2:
        score += 1
        signals.append("room-token-overlap")
    if degree >= 2:
        score += 1
        signals.append("degree>=2")
    if frequency >= 2:
        score += 1
        signals.append("frequency>=2")
    if any(word in reason.lower() for word in ["core", "direct", "important", "representative"]):
        score += 2
        signals.append("strong-reason")
    if any(word in reason for word in ["핵심", "직접", "중요", "대표", "연결"]):
        score += 2
        signals.append("strong-reason-ko")
    return score, signals


def enforce_supporting_quality_gate(
    result: dict[str, Any],
    review_threshold: int = 12,
) -> dict[str, Any]:
    fixed = json.loads(json.dumps(result, ensure_ascii=False))
    notes: list[dict[str, Any]] = []
    for room in fixed.get("rooms", []):
        supporting = [
            entity
            for entity in room.get("entities", [])
            if entity.get("visibility") == "supporting"
        ]
        if len(supporting) <= review_threshold:
            continue

        scored = []
        for entity in supporting:
            score, signals = supporting_strength(room, entity)
            scored.append((score, signals, entity))

        demoted: list[dict[str, Any]] = []
        for score, signals, entity in scored:
            if score >= 2:
                continue
            entity["visibility"] = "search_only"
            entity["reason"] = (
                str(entity.get("reason", ""))
                + " / supporting quality gate: weak learner-facing signal; preserved as search_only evidence"
            ).strip(" /")
            demoted.append(
                {
                    "entity_id": int(entity["entity_id"]),
                    "title": entity.get("title"),
                    "score": score,
                    "signals": signals,
                }
            )

        if demoted:
            notes.append(
                {
                    "room_no": room.get("room_no"),
                    "title": room.get("title"),
                    "review_threshold": review_threshold,
                    "demoted_supporting_to_search_only": demoted,
                }
            )
            room.setdefault("risk_flags", []).append(
                f"supporting quality gate: weak supporting {len(demoted)}개를 search_only로 낮춤"
            )

    fixed["supporting_quality_gate"] = {
        "policy": (
            "No search_only quota. Only overcrowded supporting panels are reviewed; "
            "weak learner-facing supporting items are preserved as search_only evidence."
        ),
        "review_threshold": review_threshold,
        "notes": notes,
    }
    return fixed


def write_ui_flow(path: Path, source: str) -> None:
    path.write_text(
        f"""# LLM+라그 UI 우선 방 설계 플로우

## 핵심 관점

답변은 GraphRAG 지식망을 사용하고, 방은 사용자가 보는 UI 구조로 사용한다.

## 단계

1. GraphRAG 원본 로드
- source: {source}
- 엔티티, 관계, 커뮤니티, 원문 근거 ID를 답변용 백엔드 지식망으로 유지한다.

2. LLM UI 방 설계
- GPT-5.4 mini 사용
- GraphRAG 커뮤니티를 그대로 방으로 쓰지 않는다.
- 사용자가 보기 좋은 시대/주제 흐름을 우선한다.
- 작은 주제는 background/search_only로 보존할 수 있다.

3. 로컬 검증
- 모든 community_id가 내부 coverage에 정확히 한 번 포함되는지 검사한다.
- 중복 entity_id를 제거한다.
- core/supporting이 전체 대비 일정 비율을 넘으면 supporting/search_only로 낮춘다.

4. 결과 해석
- visible/core/supporting은 UI 노출용이다.
- background/search_only는 GraphRAG 답변 근거로 유지된다.
- 따라서 UI가 깔끔해도 질문 답변은 GraphRAG 전체 구조를 사용할 수 있다.
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    load_dotenv(Path(".env"))
    config = load_config(args.config)
    if args.temperature is not None:
        config.setdefault("azure_openai", {})["temperature"] = args.temperature
    if args.top_p is not None:
        config.setdefault("azure_openai", {})["top_p"] = args.top_p
    communities, entities, relationships = load_inputs(args.source)
    payload, entities_by_id = build_payload(communities, entities, relationships)
    prompt = make_prompt(payload, communities, args.min_rooms, args.max_rooms)

    (args.output / "UI우선_prompt.json").write_text(
        json.dumps(
            {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source": str(args.source),
                "prompt": prompt,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    raw, usage = call_model(
        config,
        system=(
            "You are a UI-first learning-room architect. "
            "Use GraphRAG as backend evidence, but design clean learner-facing rooms. "
            "Output JSON only."
        ),
        user=prompt,
        max_tokens=args.max_tokens,
    )
    (args.output / "UI우선_raw.md").write_text(raw, encoding="utf-8")
    parsed = extract_json_object(raw)
    enriched = enrich_entities(parsed, entities_by_id)
    enriched = remove_duplicate_entities(enriched)
    enriched = enrich_entities(enriched, entities_by_id)
    enriched = enforce_ui_caps(
        enriched,
        max_core_share=args.max_core_share,
        max_supporting_share=args.max_supporting_share,
    )
    enriched = enforce_supporting_quality_gate(
        enriched,
        review_threshold=args.supporting_review_threshold,
    )
    enriched = enrich_entities(enriched, entities_by_id)
    validation = validate_ui_first(
        enriched,
        {community.cid for community in communities},
        max_core_share=args.max_core_share,
        max_supporting_share=args.max_supporting_share,
    )
    repair_logs: list[dict[str, Any]] = []
    if not validation.get("valid") and args.coverage_repair_attempts > 0:
        enriched, validation, repair_logs = run_llm_coverage_repair(
            config,
            enriched,
            validation,
            communities,
            entities_by_id,
            attempts=args.coverage_repair_attempts,
            max_tokens=args.max_tokens,
            max_core_share=args.max_core_share,
            max_supporting_share=args.max_supporting_share,
        )
    alignment = semantic_alignment_report(enriched, communities)

    result = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(args.source),
        "model": config["azure_openai"].get("model"),
        "deployment_name": config["azure_openai"].get("deployment_name"),
        "usage": usage.model_dump() if hasattr(usage, "model_dump") else str(usage),
        "policy": "UI-first rooms; GraphRAG remains backend answer evidence.",
        "validation": validation,
        "semantic_alignment": alignment,
        "coverage_repair": {
            "mode": "llm_repair_on_validation_failure",
            "attempt_limit": args.coverage_repair_attempts,
            "attempts": repair_logs,
        },
        **enriched,
    }
    (args.output / "UI우선_방설계.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_markdown(result, validation, args.output / "UI우선_방설계.md")
    write_ui_flow(args.output / "UI우선_플로우_정리.md", str(args.source))
    generate_html(
        result,
        validation,
        args.output / "UI우선_방_엔티티_시각화.html",
        title="LLM+라그 UI 우선 방 설계",
    )
    print(f"Wrote: {args.output / 'UI우선_방설계.md'}")
    print(f"Wrote: {args.output / 'UI우선_방_엔티티_시각화.html'}")
    print(f"Validation: {validation}")
    print(f"Usage: {usage}")


if __name__ == "__main__":
    main()
