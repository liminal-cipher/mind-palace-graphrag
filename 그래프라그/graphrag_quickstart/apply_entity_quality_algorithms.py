from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_BASE = Path(
    "output/그래프라그 방나누기/gpt4.1mini/10차_프롬프트/10차(수정)"
)
DEFAULT_OUTPUT_DIR = Path(
    "output/그래프라그 방나누기/gpt4.1mini/11차"
)

ALIASES = {
    "세종대왕": "세종",
    "태종이방원": "태종",
    "이방원": "태종",
    "방원": "태종",
    "흥선대원군": "흥선 대원군",
    "사명대사유정": "유정",
    "유정사명대사": "유정",
    "노비문서": "노비 문서",
    "중상학파": "중상 학파",
}

RISKY_CANONICALS = {
    "명",
    "일본",
    "유정",
}

SAFE_TYPE_FAMILIES = [
    {"인물"},
    {"사건"},
    {"정책"},
    {"기관"},
    {"문물", "서적"},
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Algorithm-only entity resolution and orphan weak-edge patch."
    )
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-weak-edges-per-orphan", type=int, default=3)
    parser.add_argument("--min-co-mentions", type=int, default=1)
    return parser.parse_args()


def normalize_title(title: str) -> str:
    compact = re.sub(r"\s+", "", str(title))
    compact = re.sub(r"[()·ㆍ⋅,./:;'\"]", "", compact)
    return ALIASES.get(compact, str(title).strip())


def type_family(entity_type: str) -> str:
    raw = str(entity_type).strip()
    for family in SAFE_TYPE_FAMILIES:
        if raw in family:
            return "|".join(sorted(family))
    return raw


def read_frames(base: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (
        pd.read_parquet(base / "entities.parquet"),
        pd.read_parquet(base / "relationships.parquet"),
        pd.read_parquet(base / "text_units.parquet"),
    )


def build_safe_resolution_groups(entities: pd.DataFrame) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for row in entities.itertuples(index=False):
        canonical = normalize_title(str(row.title))
        grouped[(canonical, type_family(str(row.type)))].append(row)

    groups = []
    for (canonical, family), rows in grouped.items():
        if len(rows) < 2:
            continue
        if canonical in RISKY_CANONICALS:
            continue
        canonical_row = max(
            rows,
            key=lambda row: (
                int(row.degree),
                int(row.frequency),
                len(str(row.description)),
            ),
        )
        groups.append(
            {
                "canonical_title": str(canonical_row.title),
                "canonical_entity_id": int(canonical_row.human_readable_id),
                "canonical_type": str(canonical_row.type),
                "merged_entity_ids": [
                    int(row.human_readable_id) for row in rows
                ],
                "merged_titles": [str(row.title) for row in rows],
                "type_family": family,
                "frequency_sum": sum(int(row.frequency) for row in rows),
                "degree_sum_before_dedup": sum(int(row.degree) for row in rows),
                "rule": "same canonical normalized title and compatible type family",
            }
        )
    groups.sort(key=lambda item: (-len(item["merged_entity_ids"]), item["canonical_title"]))
    return groups


def build_alias_lookup(groups: list[dict[str, Any]], entities: pd.DataFrame) -> dict[str, str]:
    id_to_title = {
        int(row.human_readable_id): str(row.title)
        for row in entities.itertuples(index=False)
    }
    lookup = {}
    for group in groups:
        canonical_title = group["canonical_title"]
        for entity_id in group["merged_entity_ids"]:
            title = id_to_title.get(entity_id)
            if title:
                lookup[title] = canonical_title
    return lookup


def canonicalize_relationships(
    relationships: pd.DataFrame, alias_lookup: dict[str, str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    changed_count = 0
    for row in relationships.itertuples(index=False):
        source = alias_lookup.get(str(row.source), str(row.source))
        target = alias_lookup.get(str(row.target), str(row.target))
        if source == target:
            changed_count += 1
            continue
        if source != str(row.source) or target != str(row.target):
            changed_count += 1
        key = tuple(sorted((source, target)))
        item = merged.setdefault(
            key,
            {
                "source": key[0],
                "target": key[1],
                "weight": 0.0,
                "relationship_count": 0,
                "descriptions": [],
                "kind": "canonicalized_existing",
            },
        )
        item["weight"] += float(row.weight)
        item["relationship_count"] += 1
        if len(item["descriptions"]) < 3:
            item["descriptions"].append(str(row.description))
    return list(merged.values()), {
        "original_relationship_count": len(relationships),
        "canonical_relationship_count": len(merged),
        "changed_or_collapsed_relationships": changed_count,
    }


def build_weak_edges_for_orphans(
    entities: pd.DataFrame,
    relationships: pd.DataFrame,
    text_units: pd.DataFrame,
    alias_lookup: dict[str, str],
    max_edges_per_orphan: int,
    min_co_mentions: int,
) -> list[dict[str, Any]]:
    titles_with_edges = set(relationships["source"].astype(str)) | set(
        relationships["target"].astype(str)
    )
    entity_by_uuid = {
        str(row.id): row for row in entities.itertuples(index=False)
    }
    uuid_by_title = {
        str(row.title): str(row.id) for row in entities.itertuples(index=False)
    }
    text_unit_entities = {
        str(row.id): [str(entity_id) for entity_id in row.entity_ids]
        for row in text_units.itertuples(index=False)
    }

    weak_edges = []
    for row in entities.itertuples(index=False):
        title = str(row.title)
        canonical_title = alias_lookup.get(title, title)
        if int(row.degree) != 0 and title in titles_with_edges:
            continue
        co_mentions: Counter[str] = Counter()
        for text_unit_id in [str(item) for item in row.text_unit_ids]:
            for other_uuid in text_unit_entities.get(text_unit_id, []):
                other = entity_by_uuid.get(other_uuid)
                if other is None:
                    continue
                other_title = str(other.title)
                other_canonical = alias_lookup.get(other_title, other_title)
                if other_canonical == canonical_title:
                    continue
                co_mentions[other_canonical] += 1

        for target, count in co_mentions.most_common(max_edges_per_orphan):
            if count < min_co_mentions:
                continue
            target_uuid = uuid_by_title.get(target)
            target_row = entity_by_uuid.get(target_uuid) if target_uuid else None
            target_degree = int(target_row.degree) if target_row is not None else 0
            weight = weak_edge_weight(count=count, target_degree=target_degree)
            weak_edges.append(
                {
                    "source": canonical_title,
                    "target": target,
                    "weight": weight,
                    "kind": "weak_co_mention",
                    "co_text_units": count,
                    "source_entity_id": int(row.human_readable_id),
                    "source_type": str(row.type),
                    "source_frequency": int(row.frequency),
                    "target_degree": target_degree,
                    "rule": "degree-zero entity co-mentioned in the same text unit",
                }
            )
    return weak_edges


def weak_edge_weight(count: int, target_degree: int) -> float:
    base = 0.6 + min(2, count) * 0.4
    hub_penalty = 0.75 if target_degree >= 10 else 1.0
    return round(base * hub_penalty, 3)


def summarize_effects(
    entities: pd.DataFrame,
    groups: list[dict[str, Any]],
    canonical_relationships: list[dict[str, Any]],
    weak_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    merged_ids = {
        entity_id
        for group in groups
        for entity_id in group["merged_entity_ids"]
    }
    entity_count_after_resolution = len(entities) - sum(
        max(0, len(group["merged_entity_ids"]) - 1) for group in groups
    )
    weak_sources = {edge["source_entity_id"] for edge in weak_edges}
    return {
        "entity_count_before": len(entities),
        "safe_resolution_group_count": len(groups),
        "entities_in_resolution_groups": len(merged_ids),
        "entity_count_after_safe_resolution": entity_count_after_resolution,
        "canonical_relationship_count": len(canonical_relationships),
        "weak_edge_count": len(weak_edges),
        "orphan_entities_with_weak_edges": len(weak_sources),
    }


def write_outputs(
    output_dir: Path,
    payload: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "entity_quality_algorithmic_patch.json"
    md_path = output_dir / "entity_quality_algorithmic_patch.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# Entity Quality Algorithmic Patch",
        "",
        "LLM 없이 생성한 안전 병합/약한 관계 보강안입니다. 원본 parquet은 수정하지 않았습니다.",
        "",
        "## Summary",
        "",
    ]
    for key, value in payload["summary"].items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## 1. Safe Entity Resolution Groups", ""])
    for group in payload["safe_entity_resolution_groups"]:
        lines.append(
            f"- {group['canonical_title']}#{group['canonical_entity_id']} "
            f"<= {group['merged_titles']} / ids={group['merged_entity_ids']} "
            f"/ freq_sum={group['frequency_sum']} / degree_sum={group['degree_sum_before_dedup']}"
        )

    lines.extend(["", "## 2. Weak Edges For Orphans", ""])
    for edge in payload["weak_edges_for_orphans"][:160]:
        lines.append(
            f"- {edge['source']} -> {edge['target']} "
            f"w={edge['weight']} co={edge['co_text_units']} "
            f"source_id={edge['source_entity_id']} source_type={edge['source_type']}"
        )

    lines.extend(["", "## 3. Notes", ""])
    lines.append("- safe entity resolution은 동일 정규화명 + 호환 타입인 경우만 자동 병합 후보로 잡았습니다.")
    lines.append("- substring 유사 후보는 오탐 위험이 커서 자동 병합하지 않았습니다.")
    lines.append("- orphan 보강은 같은 text_unit 공출현만 낮은 weight의 weak edge로 추가합니다.")
    lines.append("- 이 결과를 실제 GraphRAG 원본에 반영하려면 별도 검증 후 canonical graph를 만들어야 합니다.")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {md_path}")
    print(f"Wrote: {json_path}")


def main() -> None:
    args = parse_args()
    entities, relationships, text_units = read_frames(args.base)
    groups = build_safe_resolution_groups(entities)
    alias_lookup = build_alias_lookup(groups, entities)
    canonical_relationships, relationship_summary = canonicalize_relationships(
        relationships, alias_lookup
    )
    weak_edges = build_weak_edges_for_orphans(
        entities,
        relationships,
        text_units,
        alias_lookup,
        max_edges_per_orphan=args.max_weak_edges_per_orphan,
        min_co_mentions=args.min_co_mentions,
    )
    summary = summarize_effects(
        entities, groups, canonical_relationships, weak_edges
    )
    summary.update(relationship_summary)
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "base": str(args.base),
        "summary": summary,
        "safe_entity_resolution_groups": groups,
        "canonical_relationships": canonical_relationships,
        "weak_edges_for_orphans": weak_edges,
    }
    write_outputs(args.output_dir, payload)
    print(summary)


if __name__ == "__main__":
    main()
