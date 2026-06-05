from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from openai import AzureOpenAI


SOURCE_BASE = Path("output/그래프라그 방나누기/gpt4.1mini/10차_프롬프트/10차(수정)")
OUTPUT_DIR = Path("output/그래프라그 방나누기/gpt4.1mini/12차")
DEFAULT_CONFIG = Path("output/그래프라그 방나누기/gpt4.1mini/NEW/settings_gpt5.4mini.yaml")
DEFAULT_QUALITY_PATCH = Path(
    "output/그래프라그 방나누기/gpt4.1mini/11차/entity_quality_algorithmic_patch.json"
)

STOPWORDS = {
    "조선",
    "관련",
    "중심",
    "내용",
    "학습",
    "중요",
    "설명",
    "영향",
    "관계",
    "시대",
    "역할",
    "과정",
    "체계",
    "발전",
    "배경",
    "주요",
    "Data",
    "Entities",
    "Relationships",
}

TYPE_WEIGHTS = {
    "사건": 1.0,
    "정책": 0.95,
    "인물": 0.9,
    "기관": 0.75,
    "문물": 0.8,
    "서적": 0.8,
    "장소": 0.6,
}


@dataclass
class Community:
    cid: int
    title: str
    summary: str
    full_content: str
    rank: float
    size: int
    entity_ids: set[int]
    keywords: set[str]


def numeric_entity_id(row: Any) -> int:
    return int(getattr(row, "human_readable_id"))


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, float) and math.isnan(value):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "tolist"):
        return value.tolist()
    return [value]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build 12th-pass LLM-designed learning rooms while preserving GraphRAG IDs."
    )
    parser.add_argument("--source", type=Path, default=SOURCE_BASE)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--quality-patch", type=Path, default=DEFAULT_QUALITY_PATCH)
    parser.add_argument("--no-quality-patch", action="store_true")
    parser.add_argument("--min-rooms", type=int, default=4)
    parser.add_argument("--max-rooms", type=int, default=7)
    parser.add_argument("--reuse-raw", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def expand_env(value: Any) -> Any:
    if isinstance(value, str):
        pattern = re.compile(r"\$\{([^}]+)\}")

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in os.environ:
                raise RuntimeError(f"Missing environment variable: {key}")
            return os.environ[key]

        return pattern.sub(replace, value)
    if isinstance(value, list):
        return [expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: expand_env(item) for key, item in value.items()}
    return value


def load_config(path: Path) -> dict[str, Any]:
    return expand_env(yaml.safe_load(path.read_text(encoding="utf-8")))


def tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[가-힣A-Za-z0-9]{2,}", text or "")
    return {token for token in tokens if token not in STOPWORDS}


def parse_data_ids(text: str, label: str) -> set[int]:
    ids: set[int] = set()
    for match in re.finditer(rf"{label}\s*\(([^)]*)\)", text or ""):
        ids.update(int(item) for item in re.findall(r"\d+", match.group(1)))
    return ids


def load_inputs(base: Path) -> tuple[list[Community], pd.DataFrame, pd.DataFrame]:
    reports = pd.read_parquet(base / "community_reports.parquet")
    entities = pd.read_parquet(base / "entities.parquet")
    relationships = pd.read_parquet(base / "relationships.parquet")
    communities: list[Community] = []
    for row in reports.sort_values("community").itertuples(index=False):
        full_content = str(row.full_content)
        full_text = f"{row.title}\n{row.summary}\n{full_content}"
        communities.append(
            Community(
                cid=int(row.community),
                title=str(row.title),
                summary=str(row.summary),
                full_content=full_content,
                rank=float(row.rank),
                size=int(row.size),
                entity_ids=parse_data_ids(full_content, "Entities"),
                keywords=tokenize(full_text),
            )
        )
    return communities, entities, relationships


def load_quality_patch(path: Path, disabled: bool = False) -> dict[str, Any] | None:
    if disabled or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_maps(patch: dict[str, Any] | None) -> tuple[dict[int, int], dict[str, str], list[dict[str, Any]]]:
    if not patch:
        return {}, {}, []
    id_to_canonical: dict[int, int] = {}
    title_to_canonical: dict[str, str] = {}
    groups = patch.get("safe_entity_resolution_groups", [])
    for group in groups:
        canonical_id = int(group["canonical_entity_id"])
        canonical_title = str(group["canonical_title"])
        for entity_id, title in zip(group["merged_entity_ids"], group["merged_titles"]):
            id_to_canonical[int(entity_id)] = canonical_id
            title_to_canonical[str(title)] = canonical_title
    return id_to_canonical, title_to_canonical, groups


def canonicalize_entities(
    entities: pd.DataFrame, groups: list[dict[str, Any]]
) -> pd.DataFrame:
    if not groups:
        return entities.copy()

    alias_to_canonical: dict[int, int] = {}
    canonical_titles: dict[int, str] = {}
    alias_titles: dict[int, list[str]] = defaultdict(list)
    for group in groups:
        canonical_id = int(group["canonical_entity_id"])
        canonical_titles[canonical_id] = str(group["canonical_title"])
        for entity_id, title in zip(group["merged_entity_ids"], group["merged_titles"]):
            alias_to_canonical[int(entity_id)] = canonical_id
            alias_titles[canonical_id].append(str(title))

    rows: dict[int, dict[str, Any]] = {}
    for row in entities.itertuples(index=False):
        entity_id = numeric_entity_id(row)
        canonical_id = alias_to_canonical.get(entity_id, entity_id)
        data = rows.setdefault(
            canonical_id,
            {
                "id": canonical_id,
                "human_readable_id": canonical_id,
                "title": canonical_titles.get(canonical_id, str(row.title)),
                "type": str(row.type),
                "description": "",
                "text_unit_ids": set(),
                "frequency": 0,
                "degree": 0,
                "aliases": set(alias_titles.get(canonical_id, [])),
            },
        )
        data["description"] = " ".join(
            part for part in [data["description"], str(row.description)] if part
        ).strip()
        data["text_unit_ids"].update(as_list(getattr(row, "text_unit_ids", [])))
        data["frequency"] += int(getattr(row, "frequency", 0) or 0)
        data["degree"] += int(getattr(row, "degree", 0) or 0)
        data["aliases"].add(str(row.title))

    normalized = []
    for data in rows.values():
        data["text_unit_ids"] = sorted(data["text_unit_ids"])
        data["aliases"] = sorted(alias for alias in data["aliases"] if alias != data["title"])
        normalized.append(data)
    return pd.DataFrame(normalized)


def canonicalize_relationships(
    relationships: pd.DataFrame, title_to_canonical: dict[str, str]
) -> pd.DataFrame:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in relationships.itertuples(index=False):
        source = title_to_canonical.get(str(row.source), str(row.source))
        target = title_to_canonical.get(str(row.target), str(row.target))
        if source == target:
            continue
        key = tuple(sorted((source, target)))
        item = grouped.setdefault(
            key,
            {
                "source": key[0],
                "target": key[1],
                "weight": 0.0,
                "description": [],
                "text_unit_ids": set(),
            },
        )
        item["weight"] += float(getattr(row, "weight", 0.0) or 0.0)
        if getattr(row, "description", None):
            item["description"].append(str(row.description))
        item["text_unit_ids"].update(as_list(getattr(row, "text_unit_ids", [])))
    rows = []
    for idx, item in enumerate(grouped.values()):
        rows.append(
            {
                "id": idx,
                "source": item["source"],
                "target": item["target"],
                "weight": round(item["weight"], 4),
                "description": " / ".join(item["description"][:3]),
                "text_unit_ids": sorted(item["text_unit_ids"]),
            }
        )
    return pd.DataFrame(rows)


def apply_quality_patch(
    communities: list[Community],
    entities: pd.DataFrame,
    relationships: pd.DataFrame,
    patch: dict[str, Any] | None,
) -> tuple[list[Community], pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    id_to_canonical, title_to_canonical, groups = canonical_maps(patch)
    patched_communities = [
        Community(
            cid=community.cid,
            title=community.title,
            summary=community.summary,
            full_content=community.full_content,
            rank=community.rank,
            size=community.size,
            entity_ids={id_to_canonical.get(entity_id, entity_id) for entity_id in community.entity_ids},
            keywords=community.keywords,
        )
        for community in communities
    ]
    patched_entities = canonicalize_entities(entities, groups)
    patched_relationships = canonicalize_relationships(relationships, title_to_canonical)
    report = {
        "enabled": patch is not None,
        "safe_entity_resolution_group_count": len(groups),
        "entity_count_before": len(entities),
        "entity_count_after": len(patched_entities),
        "relationship_count_before": len(relationships),
        "relationship_count_after": len(patched_relationships),
        "note": "Safe entity resolution only. Weak orphan edges are not used for room design.",
    }
    return patched_communities, patched_entities, patched_relationships, report


def build_community_entity_index(
    communities: list[Community], entities: pd.DataFrame
) -> dict[int, set[int]]:
    valid_ids = {numeric_entity_id(row) for row in entities.itertuples(index=False)}
    return {community.cid: {eid for eid in community.entity_ids if eid in valid_ids} for community in communities}


def build_entity_community_index(community_entities: dict[int, set[int]]) -> dict[int, set[int]]:
    result: dict[int, set[int]] = defaultdict(set)
    for cid, ids in community_entities.items():
        for entity_id in ids:
            result[entity_id].add(cid)
    return result


def relationship_scores(
    relationships: pd.DataFrame, entities: pd.DataFrame
) -> tuple[dict[str, float], dict[str, int]]:
    degree: dict[str, float] = defaultdict(float)
    edge_count: dict[str, int] = defaultdict(int)
    for row in relationships.itertuples(index=False):
        weight = float(getattr(row, "weight", 0.0) or 0.0)
        for title in [str(row.source), str(row.target)]:
            degree[title] += weight
            edge_count[title] += 1
    known_titles = {str(row.title) for row in entities.itertuples(index=False)}
    for title in known_titles:
        degree.setdefault(title, 0.0)
        edge_count.setdefault(title, 0)
    return degree, edge_count


def select_community_entities(
    community: Community,
    entities_by_id: dict[int, dict[str, Any]],
    degree_by_title: dict[str, float],
    limit: int = 14,
) -> list[dict[str, Any]]:
    selected = []
    for entity_id in community.entity_ids:
        entity = entities_by_id.get(entity_id)
        if not entity:
            continue
        type_weight = TYPE_WEIGHTS.get(str(entity.get("type", "")), 0.7)
        score = (
            math.log1p(float(entity.get("frequency", 0) or 0)) * 0.25
            + math.log1p(float(entity.get("degree", 0) or 0)) * 0.25
            + math.log1p(degree_by_title.get(str(entity["title"]), 0.0)) * 0.35
            + type_weight * 0.15
        )
        selected.append(
            {
                "entity_id": entity_id,
                "title": entity["title"],
                "type": entity.get("type", ""),
                "score": round(score, 4),
                "description": compact_text(str(entity.get("description", "")), 220),
            }
        )
    selected.sort(key=lambda item: item["score"], reverse=True)
    return selected[:limit]


def compact_text(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_payload(
    communities: list[Community], entities: pd.DataFrame, relationships: pd.DataFrame
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    entities_by_id = {
        numeric_entity_id(row): {
            "entity_id": numeric_entity_id(row),
            "title": str(row.title),
            "type": str(row.type),
            "description": str(row.description),
            "frequency": int(getattr(row, "frequency", 0) or 0),
            "degree": int(getattr(row, "degree", 0) or 0),
            "aliases": list(getattr(row, "aliases", []) or []),
        }
        for row in entities.itertuples(index=False)
    }
    degree_by_title, edge_count_by_title = relationship_scores(relationships, entities)
    community_summaries = []
    for community in communities:
        community_summaries.append(
            {
                "community_id": community.cid,
                "title": community.title,
                "summary": compact_text(community.summary, 520),
                "rank": round(community.rank, 4),
                "size": community.size,
                "entity_count": len(community.entity_ids),
                "key_entities": select_community_entities(
                    community, entities_by_id, degree_by_title, limit=14
                ),
            }
        )

    top_relationships = []
    for row in relationships.sort_values("weight", ascending=False).head(90).itertuples(index=False):
        top_relationships.append(
            {
                "source": str(row.source),
                "target": str(row.target),
                "weight": round(float(getattr(row, "weight", 0.0) or 0.0), 3),
                "description": compact_text(str(getattr(row, "description", "")), 220),
            }
        )

    all_entities = []
    for entity_id, entity in entities_by_id.items():
        all_entities.append(
            {
                "entity_id": entity_id,
                "title": entity["title"],
                "type": entity["type"],
                "frequency": entity["frequency"],
                "degree": entity["degree"],
                "relationship_weight": round(degree_by_title.get(entity["title"], 0.0), 3),
                "edge_count": edge_count_by_title.get(entity["title"], 0),
                "description": compact_text(entity["description"], 260),
                "aliases": entity.get("aliases", []),
            }
        )
    all_entities.sort(
        key=lambda item: (
            item["relationship_weight"],
            item["degree"],
            item["frequency"],
        ),
        reverse=True,
    )

    payload = {
        "source": str(SOURCE_BASE),
        "community_count": len(communities),
        "entity_count": len(all_entities),
        "relationship_count": len(relationships),
        "communities": community_summaries,
        "top_relationships": top_relationships,
        "all_entities": all_entities,
    }
    return payload, entities_by_id


def make_prompt(payload: dict[str, Any], min_rooms: int, max_rooms: int) -> str:
    return f"""
아래는 한국사 PDF에서 GraphRAG가 만든 원본 근거입니다.

이번 12차 목표는 GraphRAG 커뮤니티를 그대로 방으로 쓰는 것이 아닙니다.
GraphRAG는 엔티티, 관계, 원본 커뮤니티 근거를 제공하는 백엔드 지식망으로 유지하고,
당신은 학습자가 이해하기 좋은 3D 기억방 구조를 새로 설계합니다.

중요 원칙:
- 방은 {min_rooms}~{max_rooms}개 사이에서 품질 우선으로 선택하세요.
- 방을 줄일수록 좋다는 편향을 버리세요.
- 너무 작은 방은 만들지 마세요. 1~2개 엔티티만 있는 방은 하위구역으로 편입하세요.
- 너무 큰 방도 피하세요. 한 방이 전체 core 엔티티의 35%를 넘을 것 같으면 분리하거나 하위구역을 명확히 나누세요.
- 방 제목은 학습자가 이해할 수 있는 시대/주제 단위로 만드세요.
- GraphRAG 커뮤니티 ID를 최종 방에 모두 정확히 한 번씩 배치하세요.
- 엔티티는 반드시 기존 entity_id를 유지하세요.
- 방 구조는 학습자 친화적으로 자유롭게 재설계해도 되지만, GraphRAG 근거 ID를 끊으면 안 됩니다.
- 각 방마다 core/supporting/search_only 엔티티를 구분하세요.
- core는 3D 방에서 직접 보여줄 핵심 항목입니다.
- supporting은 하위 설명이나 확장 패널에서 보여줄 항목입니다.
- search_only는 방 UI에는 과하게 노출하지 않지만 질문 답변에는 남겨둘 항목입니다.
- entity_id를 누락해도 되지만, 주요 사건/정책/인물/문물은 search_only라도 방에 배정하세요.
- 근거 없는 내용을 새로 만들지 마세요.

출력은 JSON만 하세요. 마크다운 금지.

JSON 스키마:
{{
  "room_count_decision": {{
    "selected_room_count": 0,
    "reason": "왜 이 방 개수가 적절한지"
  }},
  "rooms": [
    {{
      "room_no": 1,
      "title": "방 제목",
      "learning_flow": "학습 순서/시대 흐름",
      "design_reason": "이 방으로 묶은 이유",
      "source_communities": [0, 1],
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
          "reason": "이 등급으로 둔 이유"
        }}
      ],
      "risk_flags": ["애매하거나 사용자 검토가 필요한 이유가 있으면 작성"]
    }}
  ],
  "ambiguous_items_for_user_review": [
    {{
      "item_type": "community | entity",
      "id": 0,
      "current_room_no": 1,
      "reason": "왜 사용자에게 보여줄지"
    }}
  ],
  "self_check": {{
    "all_communities_covered": true,
    "duplicate_community_ids": [],
    "missing_community_ids": [],
    "notes": "자체 점검"
  }}
}}

GraphRAG 근거:
{json.dumps(payload, ensure_ascii=False)}
""".strip()


def call_model(config: dict[str, Any], system: str, user: str, max_tokens: int = 12000) -> tuple[str, Any]:
    azure = config["azure_openai"]
    client = AzureOpenAI(
        azure_endpoint=azure["endpoint"],
        api_key=azure["api_key"],
        api_version=azure["api_version"],
    )
    sampling_args: dict[str, Any] = {
        "temperature": float(azure.get("temperature", 0.0)),
    }
    if azure.get("top_p") is not None:
        sampling_args["top_p"] = float(azure["top_p"])
    try:
        response = client.chat.completions.create(
            model=azure["deployment_name"],
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **sampling_args,
            max_completion_tokens=max_tokens,
        )
    except TypeError:
        response = client.chat.completions.create(
            model=azure["deployment_name"],
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **sampling_args,
            max_tokens=max_tokens,
        )
    return response.choices[0].message.content or "", response.usage


def extract_json_object(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.S)
    if fenced:
        return json.loads(fenced.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model output.")
    return json.loads(text[start : end + 1])


def validate_rooms(result: dict[str, Any], community_ids: set[int]) -> dict[str, Any]:
    seen: list[int] = []
    unknown: list[int] = []
    subzone_outside: list[dict[str, Any]] = []
    entity_duplicates: list[int] = []
    entity_seen: list[int] = []
    for room in result.get("rooms", []):
        room_ids = [int(cid) for cid in room.get("source_communities", [])]
        seen.extend(room_ids)
        unknown.extend(cid for cid in room_ids if cid not in community_ids)
        room_id_set = set(room_ids)
        for subzone in room.get("subzones", []):
            for cid in subzone.get("source_communities", []):
                cid = int(cid)
                if cid not in room_id_set:
                    subzone_outside.append(
                        {
                            "room_no": room.get("room_no"),
                            "subzone": subzone.get("title"),
                            "community_id": cid,
                        }
                    )
        for entity in room.get("entities", []):
            if "entity_id" in entity:
                entity_seen.append(int(entity["entity_id"]))

    duplicate_ids = sorted([cid for cid, count in Counter(seen).items() if count > 1])
    entity_duplicates = sorted([eid for eid, count in Counter(entity_seen).items() if count > 1])
    missing_ids = sorted(community_ids - set(seen))
    room_entity_counts = [
        {
            "room_no": room.get("room_no"),
            "title": room.get("title"),
            "entity_count": len(room.get("entities", [])),
            "core_count": sum(
                1
                for entity in room.get("entities", [])
                if entity.get("visibility") == "core"
            ),
        }
        for room in result.get("rooms", [])
    ]
    total_core = sum(item["core_count"] for item in room_entity_counts)
    oversized_core_rooms = []
    if total_core:
        oversized_core_rooms = [
            {
                **item,
                "core_share": round(item["core_count"] / total_core, 4),
            }
            for item in room_entity_counts
            if item["core_count"] / total_core > 0.35
        ]
    tiny_rooms = [
        item for item in room_entity_counts if item["entity_count"] <= 2 or item["core_count"] == 0
    ]
    return {
        "valid": not (
            missing_ids
            or duplicate_ids
            or unknown
            or subzone_outside
            or entity_duplicates
        ),
        "missing_community_ids": missing_ids,
        "duplicate_community_ids": duplicate_ids,
        "unknown_community_ids": sorted(set(unknown)),
        "subzone_out_of_room_ids": subzone_outside,
        "duplicate_entity_ids": entity_duplicates,
        "room_entity_counts": room_entity_counts,
        "tiny_rooms": tiny_rooms,
        "oversized_core_rooms": oversized_core_rooms,
    }


def remove_duplicate_entities(result: dict[str, Any]) -> dict[str, Any]:
    repaired = json.loads(json.dumps(result, ensure_ascii=False))
    visibility_rank = {"core": 3, "supporting": 2, "search_only": 1}
    placements: dict[int, list[tuple[int, int, dict[str, Any]]]] = defaultdict(list)
    for room_index, room in enumerate(repaired.get("rooms", [])):
        for entity_index, entity in enumerate(room.get("entities", [])):
            if "entity_id" in entity:
                placements[int(entity["entity_id"])].append((room_index, entity_index, entity))

    keep: set[tuple[int, int]] = set()
    duplicate_notes: dict[int, str] = {}
    for entity_id, items in placements.items():
        if len(items) == 1:
            keep.add((items[0][0], items[0][1]))
            continue
        chosen = max(
            items,
            key=lambda item: (
                visibility_rank.get(item[2].get("visibility", "search_only"), 0),
                len(str(item[2].get("reason", ""))),
                -item[0],
            ),
        )
        keep.add((chosen[0], chosen[1]))
        duplicate_notes[entity_id] = (
            f"중복 엔티티 {entity_id}는 visibility/설명 근거가 가장 강한 방 {repaired['rooms'][chosen[0]].get('room_no')}에만 남김"
        )

    for room_index, room in enumerate(repaired.get("rooms", [])):
        fixed = []
        removed = []
        for entity_index, entity in enumerate(room.get("entities", [])):
            entity_id = int(entity.get("entity_id")) if "entity_id" in entity else None
            if entity_id is None or (room_index, entity_index) in keep:
                fixed.append(entity)
            else:
                removed.append(entity_id)
        room["entities"] = fixed
        if removed:
            room.setdefault("risk_flags", []).append(
                f"로컬 검증기가 중복 엔티티 {removed}를 다른 주 방에 남기고 이 방에서는 제거함"
            )

    repaired["duplicate_entity_repair_notes"] = duplicate_notes
    return repaired


def enforce_visibility_caps(result: dict[str, Any], max_supporting: int = 24) -> dict[str, Any]:
    repaired = json.loads(json.dumps(result, ensure_ascii=False))
    notes: list[dict[str, Any]] = []
    for room in repaired.get("rooms", []):
        supporting = [
            entity
            for entity in room.get("entities", [])
            if entity.get("visibility") == "supporting"
        ]
        if len(supporting) <= max_supporting:
            continue
        supporting.sort(
            key=lambda entity: (
                int(entity.get("degree", 0) or 0),
                int(entity.get("frequency", 0) or 0),
                len(str(entity.get("description", ""))),
            ),
            reverse=True,
        )
        keep_ids = {int(entity["entity_id"]) for entity in supporting[:max_supporting]}
        demoted = []
        for entity in room.get("entities", []):
            if (
                entity.get("visibility") == "supporting"
                and int(entity["entity_id"]) not in keep_ids
            ):
                entity["visibility"] = "search_only"
                entity["reason"] = (
                    str(entity.get("reason", ""))
                    + " / 로컬 표시 정책: supporting 과밀 방에서 검색 전용으로 낮춤"
                ).strip(" /")
                demoted.append(int(entity["entity_id"]))
        if demoted:
            note = {
                "room_no": room.get("room_no"),
                "title": room.get("title"),
                "demoted_supporting_to_search_only": demoted,
            }
            notes.append(note)
            room.setdefault("risk_flags", []).append(
                f"표시 밀도 조정: supporting {len(demoted)}개를 search_only로 낮춤"
            )
    repaired["visibility_cap_notes"] = notes
    return repaired


def repair_rooms(result: dict[str, Any], communities: list[Community], entities_by_id: dict[int, dict[str, Any]]) -> dict[str, Any]:
    repaired = json.loads(json.dumps(result, ensure_ascii=False))
    community_ids = {community.cid for community in communities}
    cid_to_community = {community.cid: community for community in communities}
    rooms = repaired.setdefault("rooms", [])
    if not rooms:
        return repaired

    # Remove duplicate community IDs from later rooms.
    seen: set[int] = set()
    for room in rooms:
        unique = []
        for cid in room.get("source_communities", []):
            cid = int(cid)
            if cid in community_ids and cid not in seen:
                unique.append(cid)
                seen.add(cid)
        room["source_communities"] = unique

    # Assign missing communities to the room with the highest keyword overlap.
    for missing_id in sorted(community_ids - seen):
        community = cid_to_community[missing_id]
        best_room = max(
            rooms,
            key=lambda room: len(
                community.keywords
                & tokenize(
                    " ".join(
                        [
                            str(room.get("title", "")),
                            str(room.get("learning_flow", "")),
                            str(room.get("design_reason", "")),
                        ]
                    )
                )
            ),
        )
        best_room.setdefault("source_communities", []).append(missing_id)
        best_room.setdefault("risk_flags", []).append(
            f"로컬 검증기가 누락 커뮤니티 {missing_id}를 가장 가까운 방으로 보정함"
        )

    # Keep subzone IDs inside their room. If a room has no subzone for an ID, add a fallback subzone.
    for room in rooms:
        room_ids = set(int(cid) for cid in room.get("source_communities", []))
        fixed_subzones = []
        covered: set[int] = set()
        for subzone in room.get("subzones", []):
            ids = [int(cid) for cid in subzone.get("source_communities", []) if int(cid) in room_ids]
            if not ids:
                continue
            subzone["source_communities"] = ids
            covered.update(ids)
            fixed_subzones.append(subzone)
        for cid in sorted(room_ids - covered):
            fixed_subzones.append(
                {
                    "title": cid_to_community[cid].title,
                    "source_communities": [cid],
                    "entity_ids": sorted(
                        list(cid_to_community[cid].entity_ids),
                        key=lambda eid: entities_by_id.get(eid, {}).get("title", ""),
                    )[:10],
                }
            )
        room["subzones"] = fixed_subzones

    return repaired


def enrich_entities(
    result: dict[str, Any], entities_by_id: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    enriched = json.loads(json.dumps(result, ensure_ascii=False))
    for room in enriched.get("rooms", []):
        counts = Counter()
        entity_list = []
        seen: set[int] = set()
        for entity in room.get("entities", []):
            entity_id = int(entity.get("entity_id"))
            if entity_id in seen or entity_id not in entities_by_id:
                continue
            seen.add(entity_id)
            base = entities_by_id[entity_id]
            visibility = entity.get("visibility", "search_only")
            if visibility not in {"core", "supporting", "search_only"}:
                visibility = "search_only"
            counts[visibility] += 1
            entity_list.append(
                {
                    "entity_id": entity_id,
                    "title": base["title"],
                    "type": base["type"],
                    "visibility": visibility,
                    "reason": entity.get("reason", ""),
                    "frequency": base.get("frequency", 0),
                    "degree": base.get("degree", 0),
                    "description": base.get("description", ""),
                    "aliases": base.get("aliases", []),
                }
            )
        room["entities"] = entity_list
        room["visibility_summary"] = dict(counts)
        room["entity_count"] = len(entity_list)
    return enriched


def write_markdown(result: dict[str, Any], validation: dict[str, Any], path: Path) -> None:
    lines = [
        "# 12차 LLM 방 재설계 결과",
        "",
        "GraphRAG 커뮤니티를 방으로 그대로 쓰지 않고, GraphRAG ID를 유지한 상태에서 LLM이 학습자용 방을 재설계한 결과입니다.",
        "",
        "## 방 개수 결정",
        "",
        f"- 선택 방 개수: {result.get('room_count_decision', {}).get('selected_room_count')}",
        f"- 이유: {result.get('room_count_decision', {}).get('reason', '')}",
        "",
        "## 로컬 검증",
        "",
        f"- 검증 통과: {validation.get('valid')}",
        f"- 누락 커뮤니티: {validation.get('missing_community_ids')}",
        f"- 중복 커뮤니티: {validation.get('duplicate_community_ids')}",
        f"- 방 외부 하위구역 ID: {validation.get('subzone_out_of_room_ids')}",
        f"- 과대 core 방: {validation.get('oversized_core_rooms')}",
        f"- 작은 방/핵심 없음: {validation.get('tiny_rooms')}",
        "",
        "## 최종 방",
        "",
    ]
    for room in result.get("rooms", []):
        lines.extend(
            [
                f"### 방 {room.get('room_no')}. {room.get('title')}",
                "",
                f"- 학습 흐름: {room.get('learning_flow', '')}",
                f"- 설계 이유: {room.get('design_reason', '')}",
                f"- 원본 커뮤니티: {room.get('source_communities', [])}",
                f"- 엔티티 수: {room.get('entity_count', len(room.get('entities', [])))}",
                f"- 표시 요약: {room.get('visibility_summary', {})}",
                f"- 위험 플래그: {room.get('risk_flags', [])}",
                "",
                "#### 하위구역",
            ]
        )
        for subzone in room.get("subzones", []):
            lines.append(
                f"- {subzone.get('title')}: 커뮤니티 {subzone.get('source_communities', [])}, 엔티티 {subzone.get('entity_ids', [])[:12]}"
            )
        lines.extend(["", "#### Core 엔티티"])
        for entity in room.get("entities", []):
            if entity.get("visibility") == "core":
                lines.append(
                    f"- [{entity.get('type')}] {entity.get('title')} (id={entity.get('entity_id')}): {entity.get('reason', '')}"
                )
        lines.extend(["", "#### Supporting 엔티티"])
        for entity in room.get("entities", []):
            if entity.get("visibility") == "supporting":
                lines.append(
                    f"- [{entity.get('type')}] {entity.get('title')} (id={entity.get('entity_id')}): {entity.get('reason', '')}"
                )
        lines.extend(["", "#### Search-only 엔티티"])
        search_only = [
            entity
            for entity in room.get("entities", [])
            if entity.get("visibility") == "search_only"
        ]
        for entity in search_only[:30]:
            lines.append(f"- [{entity.get('type')}] {entity.get('title')} (id={entity.get('entity_id')})")
        if len(search_only) > 30:
            lines.append(f"- ... 외 {len(search_only) - 30}개")
        lines.append("")

    lines.extend(
        [
            "## 사용자 검토 후보",
            "",
        ]
    )
    for item in result.get("ambiguous_items_for_user_review", []):
        lines.append(
            f"- {item.get('item_type')} {item.get('id')} / 방 {item.get('current_room_no')}: {item.get('reason')}"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_flow(path: Path, source: str, patch_report: dict[str, Any]) -> None:
    patch_text = (
        "사용 안 함"
        if not patch_report.get("enabled")
        else f"safe entity resolution {patch_report.get('safe_entity_resolution_group_count', 0)}개 적용"
    )
    path.write_text(
        f"""# LLM 방 재설계 플로우 정리

## 목표

GraphRAG 커뮤니티를 방으로 그대로 쓰지 않고, GraphRAG가 만든 엔티티/관계/커뮤니티 ID를 근거망으로 유지한 채 LLM이 학습자용 방을 새로 설계한다.

## 단계

1. GraphRAG 원본 로드
- source: {source}
- community_reports/entities/relationships parquet 사용
- GraphRAG는 방 설계의 정답이 아니라 근거 재료로 사용

2. 알고리즘 보정
- entity quality patch: {patch_text}
- 다른 문서에서 만든 entity patch는 ID 충돌 위험이 있으므로 재사용하지 않는다.
- weak orphan edge는 방 설계에는 사용하지 않음

3. LLM 방 재설계
- GPT-5.4 mini 사용
- 방 개수는 4~7개 사이에서 품질 우선으로 선택
- 너무 작은 방과 너무 큰 방을 피하도록 지시
- GraphRAG community_id/entity_id를 반드시 유지하도록 지시

4. 로컬 검증 및 보정
- 원본 커뮤니티 누락/중복 검사
- 하위구역이 방 외부 커뮤니티를 참조하는지 검사
- 너무 작은 방, core 편중 방 탐지
- 누락 커뮤니티는 로컬 유사도 기준으로 임시 보정하고 위험 플래그 추가

5. 산출물
- 12차_LLM방재설계.json: 최종 구조 데이터
- 12차_LLM방재설계.md: 사람이 읽는 결과
- 12차_LLM방재설계_prompt.json: 입력 프롬프트와 근거
- 12차_LLM방재설계_raw.md: LLM 원문
- 12차_방_엔티티_시각화.html: 브라우저 시각화

## 의미

3D 방은 학습자용 UI 구조이고, GraphRAG는 질문 답변용 근거망이다. 둘은 entity_id/community_id로 연결된다.
""",
        encoding="utf-8",
    )


def generate_html(
    result: dict[str, Any], validation: dict[str, Any], path: Path, title: str = "12차 LLM 방 재설계"
) -> None:
    data = json.dumps({"result": result, "validation": validation}, ensure_ascii=False)
    html = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --bg:#f7f8fb; --panel:#ffffff; --ink:#1f2937; --muted:#6b7280;
      --line:#d8dee9; --core:#b42318; --support:#0b7285; --search:#5f6b7a;
      --accent:#2f5f8f; --warn:#a15c00;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Segoe UI, Pretendard, Arial, sans-serif; background:var(--bg); color:var(--ink); }}
    header {{ padding:24px 28px 16px; background:#ffffff; border-bottom:1px solid var(--line); position:sticky; top:0; z-index:5; }}
    h1 {{ margin:0 0 8px; font-size:24px; }}
    .meta {{ color:var(--muted); font-size:13px; display:flex; gap:14px; flex-wrap:wrap; }}
    .controls {{ margin-top:14px; display:flex; gap:10px; flex-wrap:wrap; }}
    input, select {{ border:1px solid var(--line); border-radius:6px; padding:9px 10px; font-size:14px; background:white; }}
    main {{ padding:20px 28px 40px; }}
    .summary {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; margin-bottom:18px; }}
    .metric {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }}
    .metric strong {{ display:block; font-size:22px; margin-top:6px; }}
    .room {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; margin:14px 0; overflow:hidden; }}
    .room-head {{ padding:16px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; gap:14px; align-items:flex-start; }}
    .room-title {{ font-size:19px; font-weight:700; }}
    .badges {{ display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end; }}
    .badge {{ border-radius:999px; padding:4px 8px; font-size:12px; background:#eef2f7; color:#334155; }}
    .core {{ color:var(--core); }}
    .supporting {{ color:var(--support); }}
    .search_only {{ color:var(--search); }}
    .room-body {{ padding:16px; }}
    .flow {{ color:var(--muted); margin-bottom:10px; }}
    .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
    @media (max-width:900px) {{ .grid {{ grid-template-columns:1fr; }} }}
    h3 {{ font-size:15px; margin:16px 0 8px; }}
    .subzone, .entity {{ border:1px solid var(--line); border-radius:6px; padding:10px; margin:8px 0; background:#fbfcfe; }}
    .entity {{ cursor:pointer; }}
    .entity-title {{ display:flex; justify-content:space-between; gap:10px; align-items:center; }}
    .entity small {{ color:var(--muted); }}
    .desc {{ display:none; color:#374151; margin-top:8px; line-height:1.45; font-size:13px; }}
    .entity.open .desc {{ display:block; }}
    .risk {{ color:var(--warn); font-size:13px; }}
    .hidden {{ display:none !important; }}
  </style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="meta">
    <span>GraphRAG ID 유지 + LLM 학습방 재설계</span>
    <span>검증 통과: <b id="valid"></b></span>
  </div>
  <div class="controls">
    <input id="search" placeholder="엔티티/방/하위구역 검색">
    <select id="visibility">
      <option value="all">전체 엔티티</option>
      <option value="core">core</option>
      <option value="supporting">supporting</option>
      <option value="search_only">search_only</option>
    </select>
  </div>
</header>
<main>
  <section class="summary" id="summary"></section>
  <section id="rooms"></section>
</main>
<script>
const DATA = {data};
const result = DATA.result;
const validation = DATA.validation;
document.getElementById('valid').textContent = validation.valid ? 'true' : 'false';

function countEntities(kind) {{
  return result.rooms.reduce((sum, room) => sum + room.entities.filter(e => kind === 'all' || e.visibility === kind).length, 0);
}}

document.getElementById('summary').innerHTML = [
  ['방 개수', result.rooms.length],
  ['Core', countEntities('core')],
  ['Supporting', countEntities('supporting')],
  ['Search-only', countEntities('search_only')],
  ['누락 커뮤니티', validation.missing_community_ids.length],
  ['중복 커뮤니티', validation.duplicate_community_ids.length],
].map(([k,v]) => `<div class="metric"><span>${{k}}</span><strong>${{v}}</strong></div>`).join('');

function render() {{
  const q = document.getElementById('search').value.trim().toLowerCase();
  const vis = document.getElementById('visibility').value;
  const rooms = result.rooms.map(room => {{
    const entities = room.entities.filter(e => vis === 'all' || e.visibility === vis);
    const text = JSON.stringify(room).toLowerCase();
    const matched = !q || text.includes(q);
    if (!matched) return '';
    const counts = room.visibility_summary || {{}};
    return `<article class="room">
      <div class="room-head">
        <div>
          <div class="room-title">방 ${{room.room_no}}. ${{room.title}}</div>
          <div class="flow">${{room.learning_flow || ''}}</div>
        </div>
        <div class="badges">
          <span class="badge">커뮤니티 ${{(room.source_communities || []).join(', ')}}</span>
          <span class="badge core">core ${{counts.core || 0}}</span>
          <span class="badge supporting">supporting ${{counts.supporting || 0}}</span>
          <span class="badge search_only">search ${{counts.search_only || 0}}</span>
        </div>
      </div>
      <div class="room-body">
        <p>${{room.design_reason || ''}}</p>
        ${{(room.risk_flags || []).length ? `<p class="risk">검토 후보: ${{room.risk_flags.join(' / ')}}</p>` : ''}}
        <div class="grid">
          <div>
            <h3>하위구역</h3>
            ${{(room.subzones || []).map(s => `<div class="subzone"><b>${{s.title}}</b><br><small>커뮤니티: ${{(s.source_communities || []).join(', ')}} / 엔티티: ${{(s.entity_ids || []).slice(0,14).join(', ')}}</small></div>`).join('')}}
          </div>
          <div>
            <h3>엔티티</h3>
            ${{entities.map(e => `<div class="entity" onclick="this.classList.toggle('open')">
              <div class="entity-title"><b class="${{e.visibility}}">${{e.title}}</b><small>${{e.type}} · id=${{e.entity_id}} · ${{e.visibility}}</small></div>
              <div class="desc">${{e.reason ? `<p><b>배치 이유</b>: ${{e.reason}}</p>` : ''}}<p>${{e.description || ''}}</p>${{(e.aliases || []).length ? `<p><b>alias</b>: ${{e.aliases.join(', ')}}</p>` : ''}}</div>
            </div>`).join('')}}
          </div>
        </div>
      </div>
    </article>`;
  }}).join('');
  document.getElementById('rooms').innerHTML = rooms;
}}
document.getElementById('search').addEventListener('input', render);
document.getElementById('visibility').addEventListener('change', render);
render();
</script>
</body>
</html>"""
    path.write_text(html, encoding="utf-8")


def main() -> None:
    args = parse_args()
    load_dotenv(Path(".env"))
    config = load_config(args.config)
    args.output.mkdir(parents=True, exist_ok=True)

    communities, entities, relationships = load_inputs(args.source)
    patch = load_quality_patch(args.quality_patch, args.no_quality_patch)
    communities, entities, relationships, patch_report = apply_quality_patch(
        communities, entities, relationships, patch
    )
    payload, entities_by_id = build_payload(communities, entities, relationships)
    prompt = make_prompt(payload, args.min_rooms, args.max_rooms)

    prompt_record = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(args.source),
        "config": str(args.config),
        "quality_patch": patch_report,
        "prompt": prompt,
    }
    (args.output / "12차_LLM방재설계_prompt.json").write_text(
        json.dumps(prompt_record, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if args.dry_run:
        print("Dry run. Prompt written.")
        return

    raw_path = args.output / "12차_LLM방재설계_raw.md"
    usage: Any = None
    if args.reuse_raw and raw_path.exists():
        raw = raw_path.read_text(encoding="utf-8")
    else:
        raw, usage = call_model(
            config,
            system=(
                "You are a conservative Korean-history learning-room architect. "
                "Design learner-friendly rooms from GraphRAG evidence while preserving all IDs. "
                "Output JSON only."
            ),
            user=prompt,
        )
        raw_path.write_text(raw, encoding="utf-8")
    parsed = extract_json_object(raw)
    validation_before = validate_rooms(parsed, {community.cid for community in communities})
    repaired = repair_rooms(parsed, communities, entities_by_id)
    enriched = enrich_entities(repaired, entities_by_id)
    enriched = remove_duplicate_entities(enriched)
    enriched = enrich_entities(enriched, entities_by_id)
    enriched = enforce_visibility_caps(enriched)
    enriched = enrich_entities(enriched, entities_by_id)
    validation_after = validate_rooms(enriched, {community.cid for community in communities})

    result = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(args.source),
        "model": config["azure_openai"].get("model"),
        "deployment_name": config["azure_openai"].get("deployment_name"),
        "quality_patch": patch_report,
        "usage": usage.model_dump()
        if hasattr(usage, "model_dump")
        else ("reused_raw_no_api_call" if usage is None else str(usage)),
        "validation_before_repair": validation_before,
        "validation": validation_after,
        **enriched,
    }

    (args.output / "12차_LLM방재설계.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_markdown(result, validation_after, args.output / "12차_LLM방재설계.md")
    write_flow(args.output / "12차_플로우_정리.md", str(args.source), patch_report)
    generate_html(
        result,
        validation_after,
        args.output / "12차_방_엔티티_시각화.html",
        title="LLM 방 재설계",
    )

    print(f"Wrote: {args.output / '12차_LLM방재설계.md'}")
    print(f"Wrote: {args.output / '12차_방_엔티티_시각화.html'}")
    print(f"Validation: {validation_after}")
    print(f"Usage: {usage}")


if __name__ == "__main__":
    main()
