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


SOURCE_BASE = Path(
    "output/그래프라그 방나누기/gpt4.1mini/10차_프롬프트/10차(수정)"
)
OUTPUT_DIR = Path(
    "output/그래프라그 방나누기/gpt4.1mini/11차"
)
DEFAULT_CONFIG = Path(
    "output/그래프라그 방나누기/gpt4.1mini/NEW/settings_gpt5.4mini.yaml"
)
DEFAULT_QUALITY_PATCH = Path(
    "output/그래프라그 방나누기/gpt4.1mini/11차/entity_quality_algorithmic_patch.json"
)

STOPWORDS = {
    "Data",
    "Entities",
    "Relationships",
    "Relationship",
    "Entity",
    "조선",
    "시대",
    "역할",
    "중심",
    "관련",
    "학습",
    "방",
    "내용",
    "정리",
    "이해",
    "중요",
    "영향",
    "발전",
    "과정",
    "체계",
    "형성",
    "기반",
    "주요",
    "연구",
    "중심으로",
    "중요한",
    "하였으며",
    "하였다",
    "이는",
}

TYPE_WEIGHTS = {
    "사건": 1.0,
    "정책": 0.95,
    "인물": 0.9,
    "기관": 0.75,
    # In history learning, books and cultural artifacts can be central concepts.
    "문물": 0.8,
    "서적": 0.8,
    "장소": 0.6,
}


@dataclass
class Community:
    cid: int
    title: str
    summary: str
    size: int
    rank: float
    entity_ids: set[int]
    keywords: set[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build 11th-pass <=5 rooms and classify entity visibility."
    )
    parser.add_argument("--source", type=Path, default=SOURCE_BASE)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--max-rooms", type=int, default=5)
    parser.add_argument("--min-rooms", type=int, default=3)
    parser.add_argument("--quality-patch", type=Path, default=DEFAULT_QUALITY_PATCH)
    parser.add_argument("--no-quality-patch", action="store_true")
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
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return expand_env(raw)


def tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[가-힣A-Za-z0-9]{2,}", text or "")
    return {token for token in tokens if token not in STOPWORDS}


def parse_data_ids(text: str, label: str) -> set[int]:
    ids: set[int] = set()
    for match in re.finditer(rf"{label}\s*\(([^)]*)\)", text or ""):
        for item in re.findall(r"\d+", match.group(1)):
            ids.add(int(item))
    return ids


def load_inputs(base: Path) -> tuple[list[Community], pd.DataFrame, pd.DataFrame]:
    reports = pd.read_parquet(base / "community_reports.parquet")
    entities = pd.read_parquet(base / "entities.parquet")
    relationships = pd.read_parquet(base / "relationships.parquet")

    communities: list[Community] = []
    for row in reports.sort_values("community").itertuples(index=False):
        full_text = f"{row.title}\n{row.summary}\n{row.full_content}"
        communities.append(
            Community(
                cid=int(row.community),
                title=str(row.title),
                summary=str(row.summary),
                size=int(row.size),
                rank=float(row.rank),
                entity_ids=parse_data_ids(str(row.full_content), "Entities"),
                keywords=tokenize(full_text),
            )
        )
    return communities, entities, relationships


def load_quality_patch(path: Path, disabled: bool) -> dict[str, Any] | None:
    if disabled or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def apply_quality_patch(
    communities: list[Community],
    entities: pd.DataFrame,
    relationships: pd.DataFrame,
    patch: dict[str, Any] | None,
) -> tuple[list[Community], pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if not patch:
        return communities, entities, relationships, relationships, {"enabled": False}

    id_to_canonical: dict[int, int] = {}
    title_to_canonical: dict[str, str] = {}
    canonical_groups = patch.get("safe_entity_resolution_groups", [])
    for group in canonical_groups:
        canonical_id = int(group["canonical_entity_id"])
        canonical_title = str(group["canonical_title"])
        for entity_id, title in zip(group["merged_entity_ids"], group["merged_titles"]):
            id_to_canonical[int(entity_id)] = canonical_id
            title_to_canonical[str(title)] = canonical_title

    communities = [
        Community(
            cid=community.cid,
            title=community.title,
            summary=community.summary,
            size=community.size,
            rank=community.rank,
            entity_ids={
                id_to_canonical.get(entity_id, entity_id)
                for entity_id in community.entity_ids
            },
            keywords=community.keywords,
        )
        for community in communities
    ]

    entities = canonicalize_entities(entities, canonical_groups)
    room_relationships = canonicalize_relationship_frame(
        relationships, title_to_canonical, []
    )
    entity_relationships = canonicalize_relationship_frame(
        relationships, title_to_canonical, patch.get("weak_edges_for_orphans", [])
    )
    entities = recompute_entity_degrees(entities, entity_relationships)
    report = {
        "enabled": True,
        "safe_resolution_group_count": len(canonical_groups),
        "weak_edge_count": len(patch.get("weak_edges_for_orphans", [])),
        "entity_count_after_patch": len(entities),
        "room_relationship_count_after_patch": len(room_relationships),
        "entity_relationship_count_after_patch": len(entity_relationships),
        "weak_edges_used_for": "entity_importance_only",
    }
    return communities, entities, room_relationships, entity_relationships, report


def canonicalize_entities(
    entities: pd.DataFrame, groups: list[dict[str, Any]]
) -> pd.DataFrame:
    if not groups:
        return entities
    by_id = {
        int(row.human_readable_id): row
        for row in entities.itertuples(index=False)
    }
    remove_ids: set[int] = set()
    replacement_records: dict[int, dict[str, Any]] = {}

    for group in groups:
        canonical_id = int(group["canonical_entity_id"])
        merged_ids = [int(entity_id) for entity_id in group["merged_entity_ids"]]
        rows = [by_id[entity_id] for entity_id in merged_ids if entity_id in by_id]
        if not rows:
            continue
        canonical_row = by_id.get(canonical_id, rows[0])
        descriptions = []
        text_units = []
        for row in rows:
            description = str(row.description).strip()
            if description and description not in descriptions:
                descriptions.append(description)
            text_units.extend(list(row.text_unit_ids))
        record = {
            "id": canonical_row.id,
            "human_readable_id": canonical_id,
            "title": group["canonical_title"],
            "type": canonical_row.type,
            "description": " ".join(descriptions),
            "text_unit_ids": sorted(set(text_units)),
            "frequency": int(group.get("frequency_sum", sum(int(row.frequency) for row in rows))),
            "degree": int(group.get("degree_sum_before_dedup", sum(int(row.degree) for row in rows))),
        }
        replacement_records[canonical_id] = record
        remove_ids.update(entity_id for entity_id in merged_ids if entity_id != canonical_id)

    records = []
    for row in entities.itertuples(index=False):
        entity_id = int(row.human_readable_id)
        if entity_id in remove_ids:
            continue
        if entity_id in replacement_records:
            records.append(replacement_records[entity_id])
        else:
            records.append(row._asdict())
    return pd.DataFrame(records, columns=list(entities.columns))


def canonicalize_relationship_frame(
    relationships: pd.DataFrame,
    title_to_canonical: dict[str, str],
    weak_edges: list[dict[str, Any]],
) -> pd.DataFrame:
    records_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    next_human_id = int(relationships["human_readable_id"].max()) + 1

    for row in relationships.itertuples(index=False):
        source = title_to_canonical.get(str(row.source), str(row.source))
        target = title_to_canonical.get(str(row.target), str(row.target))
        if source == target:
            continue
        key = tuple(sorted((source, target)))
        record = records_by_pair.setdefault(
            key,
            {
                "id": str(row.id),
                "human_readable_id": int(row.human_readable_id),
                "source": key[0],
                "target": key[1],
                "description": "",
                "weight": 0.0,
                "combined_degree": 0,
                "text_unit_ids": [],
            },
        )
        record["weight"] += float(row.weight)
        record["combined_degree"] = max(
            int(record["combined_degree"]), int(row.combined_degree)
        )
        record["text_unit_ids"] = sorted(
            set(record["text_unit_ids"]) | set(list(row.text_unit_ids))
        )
        if len(record["description"]) < 600:
            record["description"] = (
                (record["description"] + " " + str(row.description)).strip()
            )

    for edge in weak_edges:
        source = title_to_canonical.get(str(edge["source"]), str(edge["source"]))
        target = title_to_canonical.get(str(edge["target"]), str(edge["target"]))
        if source == target:
            continue
        key = tuple(sorted((source, target)))
        if key in records_by_pair:
            records_by_pair[key]["weight"] += float(edge["weight"])
            continue
        records_by_pair[key] = {
            "id": f"weak-{source}-{target}",
            "human_readable_id": next_human_id,
            "source": key[0],
            "target": key[1],
            "description": "공출현 기반 weak edge",
            "weight": float(edge["weight"]),
            "combined_degree": 0,
            "text_unit_ids": [],
        }
        next_human_id += 1

    records = list(records_by_pair.values())
    records.sort(key=lambda item: item["human_readable_id"])
    return pd.DataFrame(records, columns=list(relationships.columns))


def recompute_entity_degrees(
    entities: pd.DataFrame, relationships: pd.DataFrame
) -> pd.DataFrame:
    degree_by_title = Counter()
    for row in relationships.itertuples(index=False):
        degree_by_title[str(row.source)] += 1
        degree_by_title[str(row.target)] += 1
    records = []
    for row in entities.itertuples(index=False):
        record = row._asdict()
        record["degree"] = degree_by_title.get(str(row.title), 0)
        records.append(record)
    return pd.DataFrame(records, columns=list(entities.columns))


def build_entity_community_map(communities: list[Community]) -> dict[int, set[int]]:
    mapping: dict[int, set[int]] = defaultdict(set)
    for community in communities:
        for entity_id in community.entity_ids:
            mapping[entity_id].add(community.cid)
    return mapping


def relationship_edges_by_community(
    communities: list[Community], entities: pd.DataFrame, relationships: pd.DataFrame
) -> dict[tuple[int, int], float]:
    title_to_eid = {
        str(row.title): int(row.human_readable_id)
        for row in entities.itertuples(index=False)
    }
    entity_to_communities = build_entity_community_map(communities)
    edges: dict[tuple[int, int], float] = defaultdict(float)

    for row in relationships.itertuples(index=False):
        source_id = title_to_eid.get(str(row.source))
        target_id = title_to_eid.get(str(row.target))
        if source_id is None or target_id is None:
            continue
        source_comms = entity_to_communities.get(source_id, set())
        target_comms = entity_to_communities.get(target_id, set())
        for a in source_comms:
            for b in target_comms:
                if a == b:
                    continue
                key = tuple(sorted((a, b)))
                edges[key] += float(row.weight)
    return edges


def jaccard(a: set[Any], b: set[Any]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def community_similarity(
    a: Community,
    b: Community,
    rel_edges: dict[tuple[int, int], float],
    max_rel_weight: float,
) -> float:
    text_score = jaccard(a.keywords, b.keywords)
    entity_score = jaccard(a.entity_ids, b.entity_ids)
    rel_weight = rel_edges.get(tuple(sorted((a.cid, b.cid))), 0.0)
    graph_score = rel_weight / max_rel_weight if max_rel_weight else 0.0
    return 0.45 * graph_score + 0.35 * text_score + 0.20 * entity_score


def build_algorithmic_seed_rooms(
    communities: list[Community],
    entities: pd.DataFrame,
    relationships: pd.DataFrame,
    max_rooms: int,
    min_rooms: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rel_edges = relationship_edges_by_community(communities, entities, relationships)
    max_rel_weight = max(rel_edges.values(), default=0.0)
    by_id = {community.cid: community for community in communities}
    groups: list[set[int]] = [{community.cid} for community in communities]

    def group_similarity(left: set[int], right: set[int]) -> float:
        scores = []
        for a in left:
            for b in right:
                scores.append(
                    community_similarity(
                        by_id[a], by_id[b], rel_edges, max_rel_weight
                    )
                )
        if not scores:
            return 0.0
        avg_score = sum(scores) / len(scores)
        max_score = max(scores)
        merged_size = len(left) + len(right)
        imbalance = abs(len(left) - len(right)) / max(1, merged_size)
        projected_ratio = merged_size / max(1, len(communities))
        giant_penalty = 0.0
        if projected_ratio > 0.45:
            giant_penalty += 0.25 * (projected_ratio - 0.45)
        if merged_size > (len(communities) / max(1, max_rooms)) * 1.8:
            giant_penalty += 0.04
        # Average linkage avoids one strong edge pulling unrelated topics into a giant room.
        return 0.70 * avg_score + 0.30 * max_score - 0.03 * imbalance - giant_penalty

    merge_trace = []
    seed_options: list[dict[str, Any]] = []

    def render_seed_rooms(current_groups: list[set[int]]) -> list[dict[str, Any]]:
        seed_rooms = []
        for idx, group in enumerate(current_groups, start=1):
            comms = [by_id[cid] for cid in sorted(group)]
            keywords = Counter()
            for comm in comms:
                keywords.update(comm.keywords)
            seed_rooms.append(
                {
                    "seed_room_no": idx,
                    "algorithm_title_hint": make_title_hint(comms, keywords),
                    "source_communities": sorted(group),
                    "community_count": len(group),
                    "entity_count_sum": sum(comm.size for comm in comms),
                    "community_titles": [
                        {"id": comm.cid, "title": comm.title, "size": comm.size}
                        for comm in comms
                    ],
                    "top_keywords": [kw for kw, _ in keywords.most_common(12)],
                    "avg_rank": round(
                        sum(comm.rank for comm in comms) / max(1, len(comms)), 2
                    ),
                }
            )
        return seed_rooms

    while len(groups) > min_rooms:
        best: tuple[float, int, int] | None = None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                score = group_similarity(groups[i], groups[j])
                if best is None or score > best[0]:
                    best = (score, i, j)
        if best is None:
            break
        score, i, j = best
        groups[i] = groups[i] | groups[j]
        removed = groups.pop(j)
        merge_trace.append(
            {
                "score": round(score, 4),
                "merged_into": sorted(groups[i]),
                "removed": sorted(removed),
            }
        )
        if min_rooms <= len(groups) <= max_rooms:
            seed_options.append(
                {
                    "room_count": len(groups),
                    "seed_rooms": render_seed_rooms(groups),
                }
            )

    diagnostics = {
        "algorithm": "greedy agglomerative clustering",
        "max_rooms": max_rooms,
        "min_rooms": min_rooms,
        "similarity_formula": "0.45*graph_weight + 0.35*keyword_jaccard + 0.20*entity_overlap",
        "merge_trace": merge_trace,
        "relationship_pair_count": len(rel_edges),
    }
    preferred = next(
        (option["seed_rooms"] for option in seed_options if option["room_count"] == max_rooms),
        seed_options[0]["seed_rooms"] if seed_options else render_seed_rooms(groups),
    )
    diagnostics["seed_option_counts"] = [option["room_count"] for option in seed_options]
    for option in seed_options:
        option["quality_metrics"] = score_seed_option(option["seed_rooms"], len(communities))
    return preferred, {**diagnostics, "seed_options": seed_options}


def score_seed_option(seed_rooms: list[dict[str, Any]], total_communities: int) -> dict[str, Any]:
    counts = [int(room["community_count"]) for room in seed_rooms]
    entity_counts = [int(room["entity_count_sum"]) for room in seed_rooms]
    largest_ratio = max(counts) / max(1, total_communities)
    avg = sum(counts) / max(1, len(counts))
    variance = sum((count - avg) ** 2 for count in counts) / max(1, len(counts))
    balance_penalty = math.sqrt(variance) / max(1, avg)
    tiny_rooms = sum(1 for count in counts if count == 1)
    giant_rooms = sum(1 for count in counts if count / max(1, total_communities) > 0.45)
    avg_room_count = total_communities / max(1, len(seed_rooms))
    oversized_rooms = sum(1 for count in counts if count > avg_room_count * 1.8)
    return {
        "largest_room_community_ratio": round(largest_ratio, 4),
        "community_count_balance_penalty": round(balance_penalty, 4),
        "tiny_single_community_rooms": tiny_rooms,
        "giant_rooms_over_45_percent": giant_rooms,
        "oversized_rooms_over_1_8x_average": oversized_rooms,
        "room_community_counts": counts,
        "room_entity_count_sums": entity_counts,
        "note": (
            "낮을수록 좋은 지표: largest_room_community_ratio, "
            "community_count_balance_penalty, tiny_single_community_rooms, "
            "giant_rooms_over_45_percent, oversized_rooms_over_1_8x_average"
        ),
    }


def make_title_hint(comms: list[Community], keywords: Counter[str]) -> str:
    joined_titles = " / ".join(comm.title for comm in comms[:3])
    top = ", ".join(kw for kw, _ in keywords.most_common(5))
    return f"{joined_titles} | 키워드: {top}"


def call_model(config: dict[str, Any], system: str, user: str, max_tokens: int = 8000) -> tuple[str, Any]:
    azure = config["azure_openai"]
    client = AzureOpenAI(
        azure_endpoint=azure["endpoint"],
        api_key=azure["api_key"],
        api_version=azure["api_version"],
    )
    try:
        response = client.chat.completions.create(
            model=azure["deployment_name"],
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=float(azure.get("temperature", 0.0)),
            max_completion_tokens=max_tokens,
        )
    except TypeError:
        response = client.chat.completions.create(
            model=azure["deployment_name"],
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=float(azure.get("temperature", 0.0)),
            max_tokens=max_tokens,
        )
    return response.choices[0].message.content or "", response.usage


def extract_json_object(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    if fenced:
        return json.loads(fenced.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response.")
    return json.loads(text[start : end + 1])


def build_room_review_prompt(
    communities: list[Community],
    seed_rooms: list[dict[str, Any]],
    seed_options: list[dict[str, Any]],
    max_rooms: int,
    min_rooms: int,
) -> str:
    community_lines = []
    for comm in communities:
        community_lines.append(
            {
                "id": comm.cid,
                "title": comm.title,
                "size": comm.size,
                "rank": comm.rank,
                "summary": truncate(comm.summary, 520),
            }
        )
    payload = {
        "task": (
            "아래 GraphRAG 원본 커뮤니티 30개를 3D 기억방용 상위 학습방으로 "
            f"{min_rooms}~{max_rooms}개 범위에서 자연스러운 개수로 재구성하세요. "
            "3개안, 4개안, 5개안을 비교 평가한 뒤 품질이 가장 좋은 방 수를 선택하세요. "
            "학습 흐름상 부자연스러운 배치는 수정할 수 있습니다."
        ),
        "rules": [
            "원본 커뮤니티 id는 누락 없이 정확히 한 번씩만 배치합니다.",
            f"최종 방 개수는 {min_rooms}~{max_rooms}개입니다.",
            "3개, 4개, 5개 중 어느 개수도 우선하지 않습니다. 방 수보다 각 방의 의미 응집도와 학습 흐름을 우선합니다.",
            "방 수가 적다는 이유만으로 좋은 안으로 보지 마세요.",
            "한 방이 원본 커뮤니티의 45% 이상을 포함하면 과도한 압축으로 보고 강하게 감점하세요.",
            "한 방이 후보안 평균 방 크기의 1.8배를 넘으면 과도한 쏠림으로 보고 감점하세요.",
            "하나의 방 안에 서로 다른 시대·주제·학습 목적이 많이 섞이면 강하게 감점하세요.",
            "작은 단독 방이 있더라도 독립 학습 축이면 유지할 수 있습니다. 단, 세부 예시 하나뿐인 방은 감점하세요.",
            "방 수를 줄이기 위해 서로 다른 시대·주제·학습 목적의 커뮤니티를 억지로 섞지 마세요.",
            "반대로 세부 주제 하나만으로 독립 방을 만들 필요가 없으면 하위 구역으로 병합하세요.",
            "작은 커뮤니티라도 독립적인 학습 축이면 방으로 유지할 수 있고, 큰 방이라도 내부 주제가 너무 넓으면 방을 하나 더 늘릴 수 있습니다.",
            "방은 세부 사건 단위가 아니라 상위 학습 흐름 단위로 만듭니다.",
            "세부 내용은 subzones에 넣고, 방 자체는 넓게 묶습니다.",
            "PDF/GraphRAG에서 제공된 정보에 근거하세요. PDF에 없는 새 사실을 추가하지 마세요.",
            "다만 시대·주제 분류를 위한 일반 역사 상식은 보조적으로 사용할 수 있습니다.",
            "제목은 학습자가 이해하기 쉬운 한국어 명사구로 작성합니다.",
            "최종 JSON을 내기 전에 included_ids가 0부터 29까지 모두 포함되는지 자체 점검하고 missing_ids_before_submit을 비워야 합니다.",
        ],
        "algorithmic_seed_rooms_preferred": seed_rooms,
        "algorithmic_seed_options": seed_options,
        "original_communities": community_lines,
        "required_json_schema": {
            "option_evaluations": [
                {
                    "room_count": 3,
                    "strength": "장점",
                    "weakness": "한계",
                    "quality_score_0_to_10": 7,
                    "decision": "reject|select|modify",
                }
            ],
            "selected_room_count_reason": "선택한 방 개수의 이유",
            "rooms": [
                {
                    "room_no": 1,
                    "title": "상위 방 제목",
                    "learning_flow": "시대/학습 흐름 설명",
                    "source_communities": [0, 1],
                    "subzones": [
                        {
                            "title": "하위 구역 제목",
                            "source_communities": [0],
                            "purpose": "이 하위 구역의 학습 역할",
                        }
                    ],
                    "reason": "알고리즘 초안을 유지/수정한 이유",
                    "confidence": "high|medium|low",
                }
            ],
            "review_notes": ["애매한 배치나 주의점"],
            "coverage_check": {
                "all_original_ids_0_to_29_included_once": True,
                "included_ids": [0, 1, 2],
                "missing_ids_before_submit": [],
            },
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def truncate(text: str, max_len: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def validate_rooms(room_payload: dict[str, Any], community_ids: set[int], max_rooms: int) -> dict[str, Any]:
    rooms = room_payload.get("rooms", [])
    assigned: list[int] = []
    subzone_out_of_room_ids = []
    room_sources_by_no = {}
    for room in rooms:
        room_no = room.get("room_no")
        room_sources = {int(cid) for cid in room.get("source_communities", [])}
        room_sources_by_no[room_no] = room_sources
        assigned.extend(room_sources)
        for subzone in room.get("subzones", []):
            for cid in [int(item) for item in subzone.get("source_communities", [])]:
                if cid not in room_sources:
                    subzone_out_of_room_ids.append(
                        {
                            "room_no": room_no,
                            "subzone_title": subzone.get("title", ""),
                            "community": cid,
                        }
                    )
    counts = Counter(assigned)
    missing = sorted(community_ids - set(assigned))
    duplicates = sorted(cid for cid, count in counts.items() if count > 1)
    unknown = sorted(set(assigned) - community_ids)
    return {
        "room_count": len(rooms),
        "max_rooms": max_rooms,
        "missing_communities": missing,
        "duplicate_communities": duplicates,
        "unknown_communities": unknown,
        "subzone_out_of_room_ids": subzone_out_of_room_ids,
        "valid": (
            len(rooms) <= max_rooms
            and not missing
            and not duplicates
            and not unknown
            and not subzone_out_of_room_ids
        ),
    }


def repair_room_assignments(
    room_payload: dict[str, Any],
    communities: list[Community],
    validation: dict[str, Any],
) -> dict[str, Any]:
    rooms = room_payload.get("rooms", [])
    by_id = {community.cid: community for community in communities}
    actions = []

    if not validation["valid"]:
        for duplicate in validation.get("duplicate_communities", []):
            duplicate = int(duplicate)
            candidate_rooms = [
                room
                for room in rooms
                if duplicate in [int(cid) for cid in room.get("source_communities", [])]
            ]
            if len(candidate_rooms) <= 1:
                continue
            scored = [
                (score_community_to_room(by_id[duplicate], room), room)
                for room in candidate_rooms
            ]
            scored.sort(key=lambda item: item[0], reverse=True)
            keep_room = scored[0][1]
            for _, room in scored[1:]:
                room["source_communities"] = [
                    int(cid)
                    for cid in room.get("source_communities", [])
                    if int(cid) != duplicate
                ]
            actions.append(
                {
                    "action": "remove_duplicate",
                    "community": duplicate,
                    "kept_room_no": keep_room.get("room_no"),
                }
            )

        for missing in validation.get("missing_communities", []):
            missing = int(missing)
            community = by_id.get(missing)
            if community is None or not rooms:
                continue
            scored = [(score_community_to_room(community, room), room) for room in rooms]
            scored.sort(key=lambda item: item[0], reverse=True)
            best_score, best_room = scored[0]
            best_room.setdefault("source_communities", []).append(missing)
            best_room["source_communities"] = sorted(
                {int(cid) for cid in best_room.get("source_communities", [])}
            )
            best_room.setdefault("subzones", []).append(
                {
                    "title": community.title,
                    "source_communities": [missing],
                    "purpose": "LLM 응답 누락을 로직 검증으로 복구한 원본 커뮤니티",
                }
            )
            actions.append(
                {
                    "action": "assign_missing",
                    "community": missing,
                    "assigned_room_no": best_room.get("room_no"),
                    "assigned_room_title": best_room.get("title"),
                    "score": round(best_score, 4),
                }
            )

    subzone_report = sync_subzones_with_room_sources(rooms, by_id)
    actions.extend(subzone_report["actions"])

    return {"actions": actions, "room_payload": room_payload}


def sync_subzones_with_room_sources(
    rooms: list[dict[str, Any]], by_id: dict[int, Community]
) -> dict[str, Any]:
    actions = []
    for room in rooms:
        room_no = room.get("room_no")
        room_sources = {int(cid) for cid in room.get("source_communities", [])}
        subzones = room.setdefault("subzones", [])
        represented: set[int] = set()
        cleaned_subzones = []
        for subzone in subzones:
            original = [int(cid) for cid in subzone.get("source_communities", [])]
            cleaned = [cid for cid in original if cid in room_sources]
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
            subzone["source_communities"] = sorted(set(cleaned))
            represented.update(subzone["source_communities"])
            cleaned_subzones.append(subzone)
        missing_in_subzones = sorted(room_sources - represented)
        for community_id in missing_in_subzones:
            community = by_id.get(community_id)
            cleaned_subzones.append(
                {
                    "title": community.title if community else f"커뮤니티 {community_id}",
                    "source_communities": [community_id],
                    "purpose": "방 source_communities에는 있으나 하위구역에 없어서 로직으로 추가",
                }
            )
            actions.append(
                {
                    "action": "add_missing_subzone_for_room_source",
                    "room_no": room_no,
                    "community": community_id,
                }
            )
        room["subzones"] = cleaned_subzones
    return {"actions": actions}


def score_community_to_room(community: Community, room: dict[str, Any]) -> float:
    room_text = " ".join(
        [
            str(room.get("title", "")),
            str(room.get("learning_flow", "")),
            " ".join(str(subzone.get("title", "")) for subzone in room.get("subzones", [])),
        ]
    )
    room_keywords = tokenize(room_text)
    title_score = jaccard(tokenize(community.title), room_keywords)
    keyword_score = jaccard(community.keywords, room_keywords)
    return 0.55 * keyword_score + 0.45 * title_score


def build_entities_for_rooms(
    rooms: list[dict[str, Any]],
    communities: list[Community],
    entities: pd.DataFrame,
    relationships: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_comm = {comm.cid: comm for comm in communities}
    entities_by_id = {
        int(row.human_readable_id): row for row in entities.itertuples(index=False)
    }
    relationship_weight_by_title = defaultdict(float)
    for row in relationships.itertuples(index=False):
        relationship_weight_by_title[str(row.source)] += float(row.weight)
        relationship_weight_by_title[str(row.target)] += float(row.weight)

    enriched_rooms = []
    ambiguous_entities = []
    max_freq = max(float(row.frequency) for row in entities.itertuples(index=False))
    max_degree = max(float(row.degree) for row in entities.itertuples(index=False))
    max_rel = max(relationship_weight_by_title.values(), default=1.0)

    for room in rooms:
        source_ids = [int(cid) for cid in room.get("source_communities", [])]
        room_comms = [by_comm[cid] for cid in source_ids if cid in by_comm]
        room_keywords = tokenize(
            " ".join(
                [room.get("title", ""), room.get("learning_flow", "")]
                + [comm.title + " " + comm.summary for comm in room_comms]
            )
        )
        entity_ids = sorted(set().union(*(comm.entity_ids for comm in room_comms)))
        scored = []
        for entity_id in entity_ids:
            entity = entities_by_id.get(entity_id)
            if entity is None:
                continue
            score, signals = score_entity(
                entity,
                room_keywords,
                max_freq=max_freq,
                max_degree=max_degree,
                max_rel=max_rel,
                relationship_weight=relationship_weight_by_title[str(entity.title)],
            )
            visibility = classify_visibility(score)
            item = {
                "entity_id": entity_id,
                "title": str(entity.title),
                "type": str(entity.type),
                "score": round(score, 4),
                "visibility": visibility,
                "signals": signals,
                "description": truncate(str(entity.description), 260),
            }
            scored.append(item)
            if visibility == "review":
                ambiguous_entities.append(
                    {
                        "room_no": room.get("room_no"),
                        "room_title": room.get("title"),
                        **item,
                    }
                )

        scored.sort(key=lambda item: item["score"], reverse=True)
        enriched = dict(room)
        enriched["entity_count"] = len(scored)
        enriched["entities"] = scored
        ensure_minimum_core(enriched)
        enriched["visibility_summary"] = dict(Counter(item["visibility"] for item in scored))
        enriched_rooms.append(enriched)
    return enriched_rooms, ambiguous_entities


def ensure_minimum_core(room: dict[str, Any]) -> None:
    entities = room.get("entities", [])
    if not entities:
        return
    core_count = sum(1 for item in entities if item.get("visibility") == "core")
    if core_count > 0:
        return
    candidates = [
        item
        for item in entities
        if item.get("visibility") in {"supporting", "review", "search_only"}
    ]
    if not candidates:
        return
    candidates.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    top = candidates[0]
    top["visibility"] = "core"
    top["low_confidence_core"] = float(top.get("score", 0.0)) < 0.48
    top["auto_core_reason"] = "방 전면 표시를 위해 방 내 최고 점수 엔티티를 최소 core로 보장"


def score_entity(
    entity: Any,
    room_keywords: set[str],
    max_freq: float,
    max_degree: float,
    max_rel: float,
    relationship_weight: float,
) -> tuple[float, dict[str, float]]:
    title = str(entity.title)
    description = str(entity.description)
    entity_keywords = tokenize(title + " " + description)
    title_overlap = jaccard(tokenize(title), room_keywords)
    description_overlap = jaccard(entity_keywords, room_keywords)
    freq_score = min(1.0, float(entity.frequency) / max(1.0, max_freq))
    degree_score = min(1.0, float(entity.degree) / max(1.0, max_degree))
    rel_score = min(1.0, relationship_weight / max(1.0, max_rel))
    type_score = TYPE_WEIGHTS.get(str(entity.type), 0.55)
    long_description = min(1.0, len(description) / 420)
    score = (
        0.22 * freq_score
        + 0.22 * degree_score
        + 0.16 * rel_score
        + 0.16 * description_overlap
        + 0.10 * title_overlap
        + 0.10 * type_score
        + 0.04 * long_description
    )
    signals = {
        "frequency": round(freq_score, 4),
        "degree": round(degree_score, 4),
        "relationship_weight": round(rel_score, 4),
        "description_overlap": round(description_overlap, 4),
        "title_overlap": round(title_overlap, 4),
        "type_weight": round(type_score, 4),
        "description_length": round(long_description, 4),
    }
    return score, signals


def classify_visibility(score: float) -> str:
    if score >= 0.48:
        return "core"
    if score >= 0.28:
        return "supporting"
    if score >= 0.18:
        return "review"
    return "search_only"


def build_entity_review_prompt(enriched_rooms: list[dict[str, Any]], ambiguous: list[dict[str, Any]]) -> str:
    compact_rooms = []
    for room in enriched_rooms:
        compact_rooms.append(
            {
                "room_no": room["room_no"],
                "title": room["title"],
                "source_communities": room.get("source_communities", []),
                "current_core": [
                    item["title"] for item in room["entities"] if item["visibility"] == "core"
                ][:12],
                "current_supporting": [
                    item["title"]
                    for item in room["entities"]
                    if item["visibility"] == "supporting"
                ][:16],
            }
        )
    payload = {
        "task": (
            "알고리즘이 애매하다고 표시한 엔티티만 검토해 visibility를 "
            "core/supporting/search_only 중 하나로 보정하세요."
        ),
        "rules": [
            "모든 엔티티를 다시 판단하지 말고 review_entities에 있는 항목만 판단합니다.",
            "core는 방 전면에 보여줄 핵심 항목입니다. 너무 많이 승격하지 마세요.",
            "supporting은 하위 구역/상세보기에서 보일 항목입니다.",
            "search_only는 방에는 직접 표시하지 않고 챗봇/RAG용으로 보존할 항목입니다.",
            "한 번만 나오더라도 학습상 방 이해에 필수적이면 supporting 이상으로 올릴 수 있습니다.",
            "PDF/GraphRAG 근거 밖의 새 사실을 추가하지 마세요.",
            "다만 시대·주제 분류를 위한 일반 역사 상식은 보조적으로 사용할 수 있습니다.",
        ],
        "rooms_context": compact_rooms,
        "review_entities": ambiguous[:120],
        "required_json_schema": {
            "entity_overrides": [
                {
                    "room_no": 1,
                    "entity_id": 0,
                    "title": "엔티티명",
                    "visibility": "core|supporting|search_only",
                    "reason": "짧은 판단 근거",
                }
            ],
            "review_notes": ["주의점"],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def apply_entity_overrides(
    enriched_rooms: list[dict[str, Any]], overrides_payload: dict[str, Any]
) -> dict[str, Any]:
    applied = []
    rejected = []
    valid_levels = {"core", "supporting", "search_only"}
    index = {}
    for room in enriched_rooms:
        for entity in room["entities"]:
            index[(int(room["room_no"]), int(entity["entity_id"]))] = entity
    for override in overrides_payload.get("entity_overrides", []):
        key = (int(override.get("room_no", -1)), int(override.get("entity_id", -1)))
        level = str(override.get("visibility", ""))
        if key not in index or level not in valid_levels:
            rejected.append(override)
            continue
        index[key]["visibility"] = level
        index[key]["llm_reason"] = override.get("reason", "")
        applied.append(override)
    for room in enriched_rooms:
        ensure_minimum_core(room)
        room["visibility_summary"] = dict(Counter(item["visibility"] for item in room["entities"]))
    return {"applied": applied, "rejected": rejected}


def write_markdown(
    output_dir: Path,
    seed_rooms: list[dict[str, Any]],
    room_payload: dict[str, Any],
    validation: dict[str, Any],
    enriched_rooms: list[dict[str, Any]],
    entity_review_payload: dict[str, Any],
    entity_apply_report: dict[str, Any],
    room_repair_report: dict[str, Any],
    diagnostics: dict[str, Any],
) -> None:
    lines = [
        "# 11차: 5개 이내 상위 방 구성 및 엔티티 우선순위",
        "",
        "## 1. 방 구성 결과",
        "",
        f"- 최종 방 수: {validation['room_count']} / 최대 {validation['max_rooms']}",
        f"- 누락 커뮤니티: {validation['missing_communities']}",
        f"- 중복 커뮤니티: {validation['duplicate_communities']}",
        f"- 알 수 없는 커뮤니티: {validation['unknown_communities']}",
        f"- 하위구역 방 외부 ID: {validation.get('subzone_out_of_room_ids', [])}",
        f"- 로직 보정 조치: {len(room_repair_report.get('actions', []))}건",
        "",
    ]
    for room in enriched_rooms:
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
            selected = [item for item in room["entities"] if item["visibility"] == level]
            preview = ", ".join(item["title"] for item in selected[:25])
            lines.append(f"- {level}: {preview}")
        lines.append("")

    lines.extend(
        [
            "## 2. 알고리즘 초안",
            "",
            f"- 알고리즘: {diagnostics['algorithm']}",
            f"- 유사도 공식: {diagnostics['similarity_formula']}",
            "",
        ]
    )
    for seed in seed_rooms:
        lines.append(
            f"- seed {seed['seed_room_no']}: communities={seed['source_communities']} / {seed['algorithm_title_hint']}"
        )

    lines.extend(
        [
            "",
            "## 3. 방 배치 로직 보정",
            "",
        ]
    )
    if room_repair_report.get("actions"):
        for action in room_repair_report["actions"]:
            lines.append(f"- {action}")
    else:
        lines.append("- 보정 없음")

    lines.extend(
        [
            "",
            "## 4. 엔티티 LLM 보정",
            "",
            f"- 적용된 override: {len(entity_apply_report['applied'])}",
            f"- 거부된 override: {len(entity_apply_report['rejected'])}",
            "",
            "## 5. LLM 검토 메모",
            "",
        ]
    )
    if room_repair_report.get("actions"):
        lines.append(
            "- 주의: 아래 방 구성 메모는 LLM 원문 메모입니다. "
            "최종 배치는 위 로직 보정 결과가 우선합니다."
        )
    for note in room_payload.get("review_notes", []):
        lines.append(f"- 방 구성: {note}")
    for note in entity_review_payload.get("review_notes", []):
        lines.append(f"- 엔티티: {note}")
    (output_dir / "11차_최종방_엔티티분류.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def write_flow_doc(output_dir: Path) -> None:
    text = """# 11차 플로우: 알고리즘, LLM, 프롬프트 사용 정리

## 목표

10차(수정)의 GraphRAG 원본 커뮤니티 30개를 중간 10개 방을 거치지 않고, 바로 3~5개 범위의 상위 학습방으로 재구성했다. 이후 각 방 안의 엔티티를 `core`, `supporting`, `search_only`로 분류했다.

## 1. 입력

- GraphRAG 원본 커뮤니티: `community_reports.parquet`
- 원본 엔티티: `entities.parquet`
- 원본 관계: `relationships.parquet`

이 단계는 새 GraphRAG 인덱싱을 다시 돌린 것이 아니라, 10차(수정) 산출물을 후처리한 것이다.

## 2. 알고리즘 1차 방 초안 생성

사용 로직:

- 커뮤니티 제목/요약/full_content에서 키워드 추출
- 커뮤니티별 엔티티 ID 추출
- 관계 파일에서 커뮤니티 간 연결 가중치 계산
- 커뮤니티 간 유사도 계산

유사도 공식:

```text
0.45 * 그래프 관계 가중치
+ 0.35 * 키워드 Jaccard 유사도
+ 0.20 * 엔티티 겹침
```

커뮤니티 그룹을 병합할 때는 한 쌍의 강한 관계만 보지 않고 평균 유사도를 함께 반영했다. 이 점수를 이용해 greedy agglomerative clustering으로 원본 커뮤니티 30개를 5개, 4개, 3개 후보안까지 단계적으로 묶었다.

각 후보안에는 다음 품질 지표도 함께 붙였다.

- 가장 큰 방이 전체 커뮤니티에서 차지하는 비율
- 방별 커뮤니티 수 균형 패널티
- 단일 커뮤니티 방 개수
- 전체의 45% 이상을 차지하는 거대 방 개수
- 평균 방 크기의 1.8배를 넘는 과대 방 개수

따라서 방 개수는 딱 5개로 하드코딩하지 않고, LLM이 3/4/5개 후보안을 비교 평가한 뒤 학습 품질이 가장 좋은 안을 선택하게 했다.

## 3. LLM 1차 방 검토

사용 모델:

- Azure OpenAI `gpt-5.4-mini`

프롬프트 역할:

- 알고리즘 초안을 검토한다.
- 3개안, 4개안, 5개안을 각각 평가한다.
- 가장 적은 방이 아니라 학습 품질이 가장 좋은 방 개수를 선택한다.
- 세부 사건/제도/인물은 방이 아니라 하위 구역으로 넣는다.
- 원본 커뮤니티 ID를 누락/중복 없이 정확히 한 번씩 배치한다.
- 방 제목과 학습 흐름 설명을 생성한다.

중요한 제한:

- PDF에 없는 새 사실은 추가하지 않는다.
- 제공된 GraphRAG 커뮤니티 제목/요약/알고리즘 초안을 주 근거로 판단한다.
- 시대·주제 분류를 위한 일반 역사 상식은 보조적으로 사용할 수 있다.

## 4. 로직 검증

사용 로직:

- 최종 방 개수 검증
- 원본 커뮤니티 ID 누락 검사
- 원본 커뮤니티 ID 중복 검사
- 존재하지 않는 커뮤니티 ID 검사

이 단계는 LLM이 숫자와 ID를 실수하지 않았는지 확인하는 사후 안전장치다.

## 5. 알고리즘 엔티티 우선순위 계산

각 최종 방에 속한 원본 커뮤니티의 엔티티를 모아 점수를 계산했다.

사용 신호:

- 엔티티 등장 빈도
- 그래프 degree
- 관계 가중치
- 방 키워드와 엔티티 설명의 유사도
- 방 키워드와 엔티티 제목의 유사도
- 엔티티 타입 가중치
- 엔티티 설명 길이
- 방별 최소 core 보장: core가 하나도 없는 방은 최고 점수 엔티티 1개를 `low_confidence_core`로 승격

초기 등급:

```text
core: score >= 0.48
supporting: score >= 0.28
review: score >= 0.18
search_only: 나머지
```

`review`는 알고리즘만으로 판단하기 애매한 엔티티를 의미한다.

## 6. LLM 엔티티 보정

사용 모델:

- Azure OpenAI `gpt-5.4-mini`

프롬프트 역할:

- 모든 엔티티를 다시 판단하지 않는다.
- 알고리즘이 `review`로 표시한 엔티티만 검토한다.
- 각 엔티티를 `core`, `supporting`, `search_only` 중 하나로 보정한다.
- 한 번만 나왔더라도 방 이해에 필수적이면 `supporting` 이상으로 올릴 수 있다.
- 방 전면에 보여줄 `core`는 과도하게 늘리지 않는다.

## 7. 최종 산출

- `11차_최종방_엔티티분류.md`
- `11차_최종방_엔티티분류.json`
- `11차_방구성_llm_raw.md`
- `11차_엔티티분류_llm_raw.md`
- `11차_플로우_정리.md`

## 핵심 구조

```text
GraphRAG 원본 30개 커뮤니티
→ 알고리즘이 5개/4개/3개 방 초안 후보 생성
→ LLM이 초안 검토 및 방 제목/하위 구역 생성
→ 로직이 누락/중복 검증
→ 알고리즘이 엔티티 중요도 계산
→ 애매한 엔티티만 LLM이 보정
→ 최종 방 + 엔티티 표시 등급 산출
```
"""
    (output_dir / "11차_플로우_정리.md").write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    load_dotenv(Path(".env"))
    config = load_config(args.config)
    args.output.mkdir(parents=True, exist_ok=True)

    communities, entities, relationships = load_inputs(args.source)
    quality_patch = load_quality_patch(args.quality_patch, args.no_quality_patch)
    (
        communities,
        entities,
        room_relationships,
        entity_relationships,
        quality_patch_report,
    ) = apply_quality_patch(
        communities, entities, relationships, quality_patch
    )
    seed_rooms, diagnostics = build_algorithmic_seed_rooms(
        communities, entities, room_relationships, args.max_rooms, args.min_rooms
    )
    community_ids = {community.cid for community in communities}

    room_prompt = build_room_review_prompt(
        communities,
        seed_rooms,
        diagnostics.get("seed_options", []),
        args.max_rooms,
        args.min_rooms,
    )
    (args.output / "11차_방구성_prompt.json").write_text(room_prompt, encoding="utf-8")

    if args.dry_run:
        print("Dry run complete. Wrote prompt only.")
        return

    room_raw, room_usage = call_model(
        config,
        system=(
            "You are a conservative Korean-history learning-room architect. "
            "Review algorithmic groupings, keep all IDs exactly once, and output JSON only."
        ),
        user=room_prompt,
        max_tokens=8000,
    )
    (args.output / "11차_방구성_llm_raw.md").write_text(room_raw, encoding="utf-8")
    room_payload = extract_json_object(room_raw)
    validation = validate_rooms(room_payload, community_ids, args.max_rooms)
    room_repair_report = repair_room_assignments(
        room_payload, communities, validation
    )
    room_payload = room_repair_report["room_payload"]
    post_repair_validation = validate_rooms(room_payload, community_ids, args.max_rooms)

    enriched_rooms, ambiguous_entities = build_entities_for_rooms(
        room_payload.get("rooms", []), communities, entities, entity_relationships
    )
    entity_prompt = build_entity_review_prompt(enriched_rooms, ambiguous_entities)
    (args.output / "11차_엔티티분류_prompt.json").write_text(
        entity_prompt, encoding="utf-8"
    )
    entity_raw, entity_usage = call_model(
        config,
        system=(
            "You are a careful entity-visibility reviewer for a learning UI. "
            "Only review entities supplied in review_entities and output JSON only."
        ),
        user=entity_prompt,
        max_tokens=8000,
    )
    (args.output / "11차_엔티티분류_llm_raw.md").write_text(
        entity_raw, encoding="utf-8"
    )
    entity_review_payload = extract_json_object(entity_raw)
    entity_apply_report = apply_entity_overrides(
        enriched_rooms, entity_review_payload
    )

    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(args.source),
        "max_rooms": args.max_rooms,
        "quality_patch": quality_patch_report,
        "model": config["azure_openai"]["model"],
        "deployment_name": config["azure_openai"]["deployment_name"],
        "algorithmic_seed_rooms": seed_rooms,
        "diagnostics": diagnostics,
        "room_llm_usage": room_usage.model_dump()
        if hasattr(room_usage, "model_dump")
        else str(room_usage),
        "entity_llm_usage": entity_usage.model_dump()
        if hasattr(entity_usage, "model_dump")
        else str(entity_usage),
        "room_validation_before_repair": validation,
        "room_repair_report": room_repair_report,
        "room_validation": post_repair_validation,
        "entity_review_apply_report": entity_apply_report,
        "rooms": enriched_rooms,
        "review_notes": {
            "room": room_payload.get("review_notes", []),
            "entity": entity_review_payload.get("review_notes", []),
        },
    }
    (args.output / "11차_최종방_엔티티분류.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_markdown(
        args.output,
        seed_rooms,
        room_payload,
        post_repair_validation,
        enriched_rooms,
        entity_review_payload,
        entity_apply_report,
        room_repair_report,
        diagnostics,
    )
    write_flow_doc(args.output)

    print(f"Wrote outputs to: {args.output}")
    print(f"Quality patch: {quality_patch_report}")
    print(f"Room validation before repair: {validation}")
    print(f"Room repair: {room_repair_report['actions']}")
    print(f"Room validation: {post_repair_validation}")
    print(f"Ambiguous entities reviewed: {len(ambiguous_entities)}")
    print(f"Entity overrides applied: {len(entity_apply_report['applied'])}")
    print(f"Room usage: {room_usage}")
    print(f"Entity usage: {entity_usage}")


if __name__ == "__main__":
    main()
