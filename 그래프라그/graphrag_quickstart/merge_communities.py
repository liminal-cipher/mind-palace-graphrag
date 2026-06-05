from __future__ import annotations

import argparse
import json
import math
import re
from collections.abc import Iterable
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_OUTPUT_GLOB = "output/*/gpt4.1mini/10차_프롬프트/10차(수정)"
ALLOWED_ENTITY_TYPES = {"인물", "사건", "정책", "문물", "기관"}
GENERIC_ENTITY_NAMES = {
    "정부",
    "조선 정부",
    "국가",
    "사회",
    "백성",
    "농민",
    "양반",
    "임금",
    "왕",
    "신하",
    "부모",
    "아버지",
    "관리",
    "관직",
    "군대",
}
STOPWORDS = {
    "조선",
    "시대",
    "후기",
    "전기",
    "초기",
    "중기",
    "관련",
    "역할",
    "중심",
    "정책",
    "제도",
    "사회",
    "정치",
    "경제",
    "문화",
    "발전",
    "연구",
    "체계",
    "강화",
    "운동",
    "Data",
    "Entities",
    "Relationships",
    "Reports",
    "Sources",
    "claims",
}


@dataclass
class CommunityProfile:
    community: int
    title: str
    summary: str
    size: int
    entity_ids: set[str]
    entity_names: set[str]
    relationship_ids: set[str]
    text_unit_ids: set[str]
    type_counts: Counter[str]
    keywords: set[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GraphRAG community merge/split/anomaly candidate analyzer."
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=None,
        help="GraphRAG output folder containing communities.parquet.",
    )
    parser.add_argument(
        "--target-rooms",
        type=int,
        default=10,
        help="Desired rough room count. Used only for stricter reporting, not forced merging.",
    )
    parser.add_argument("--top-pairs", type=int, default=30)
    parser.add_argument("--small-threshold", type=int, default=None)
    parser.add_argument("--large-threshold", type=int, default=None)
    return parser.parse_args()


def find_default_base() -> Path:
    matches = sorted(Path(".").glob(DEFAULT_OUTPUT_GLOB))
    if not matches:
        raise FileNotFoundError(
            f"Could not find GraphRAG output folder with glob: {DEFAULT_OUTPUT_GLOB}"
        )
    return matches[-1]


def as_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, float) and math.isnan(value):
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, Iterable):
        return {str(item) for item in value if item is not None}
    return {str(value)}


def tokenize(text: str) -> set[str]:
    tokens = set()
    for token in re.findall(r"[가-힣A-Za-z0-9]+", text or ""):
        if len(token) < 2:
            continue
        if token in STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def cosine_counts(left: Counter[str], right: Counter[str]) -> float:
    keys = set(left) | set(right)
    if not keys:
        return 0.0
    numerator = sum(left[key] * right[key] for key in keys)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def load_frames(base: Path) -> dict[str, pd.DataFrame]:
    return {
        "communities": pd.read_parquet(base / "communities.parquet"),
        "reports": pd.read_parquet(base / "community_reports.parquet"),
        "entities": pd.read_parquet(base / "entities.parquet"),
        "relationships": pd.read_parquet(base / "relationships.parquet"),
        "text_units": pd.read_parquet(base / "text_units.parquet"),
    }


def build_profiles(frames: dict[str, pd.DataFrame]) -> dict[int, CommunityProfile]:
    communities = frames["communities"].copy()
    reports = frames["reports"].copy()
    entities = frames["entities"].copy()

    report_by_community = {
        int(row.community): row for row in reports.itertuples(index=False)
    }
    entity_by_id = {str(row.id): row for row in entities.itertuples(index=False)}

    profiles: dict[int, CommunityProfile] = {}
    for row in communities.itertuples(index=False):
        community = int(row.community)
        report = report_by_community.get(community)
        title = getattr(report, "title", f"Community {community}")
        summary = getattr(report, "summary", "")
        entity_ids = as_set(row.entity_ids)
        relationship_ids = as_set(row.relationship_ids)
        text_unit_ids = as_set(row.text_unit_ids)

        entity_names: set[str] = set()
        type_counts: Counter[str] = Counter()
        entity_text = []
        for entity_id in entity_ids:
            entity = entity_by_id.get(entity_id)
            if entity is None:
                continue
            name = str(entity.title)
            entity_names.add(name)
            type_counts[str(entity.type)] += 1
            entity_text.append(name)
            entity_text.append(str(entity.description or ""))

        keywords = tokenize(" ".join([str(title), str(summary), *entity_text]))
        profiles[community] = CommunityProfile(
            community=community,
            title=str(title),
            summary=str(summary or ""),
            size=int(row.size),
            entity_ids=entity_ids,
            entity_names=entity_names,
            relationship_ids=relationship_ids,
            text_unit_ids=text_unit_ids,
            type_counts=type_counts,
            keywords=keywords,
        )
    return profiles


def build_entity_community_map(
    profiles: dict[int, CommunityProfile],
) -> tuple[dict[str, int], dict[str, int]]:
    id_to_community: dict[str, int] = {}
    name_to_community: dict[str, int] = {}
    for community, profile in profiles.items():
        for entity_id in profile.entity_ids:
            id_to_community[entity_id] = community
        for name in profile.entity_names:
            name_to_community[name] = community
    return id_to_community, name_to_community


def relationship_bridge_scores(
    relationships: pd.DataFrame, name_to_community: dict[str, int]
) -> dict[tuple[int, int], dict[str, Any]]:
    bridges: dict[tuple[int, int], dict[str, Any]] = defaultdict(
        lambda: {"edge_count": 0, "weight_sum": 0.0, "examples": []}
    )
    for row in relationships.itertuples(index=False):
        source = str(row.source)
        target = str(row.target)
        source_community = name_to_community.get(source)
        target_community = name_to_community.get(target)
        if source_community is None or target_community is None:
            continue
        if source_community == target_community:
            continue
        pair = tuple(sorted((source_community, target_community)))
        bridge = bridges[pair]
        bridge["edge_count"] += 1
        bridge["weight_sum"] += float(row.weight or 0)
        if len(bridge["examples"]) < 5:
            bridge["examples"].append(
                {
                    "source": source,
                    "target": target,
                    "weight": float(row.weight or 0),
                    "description": str(row.description or "")[:180],
                }
            )
    return bridges


def score_merge_pair(
    left: CommunityProfile,
    right: CommunityProfile,
    bridge: dict[str, Any] | None,
    avg_size: float,
) -> dict[str, Any]:
    bridge = bridge or {"edge_count": 0, "weight_sum": 0.0, "examples": []}
    edge_count = int(bridge["edge_count"])
    weight_sum = float(bridge["weight_sum"])

    graph_score = min(1.0, (edge_count / 3.0) * 0.6 + (weight_sum / 25.0) * 0.4)
    text_score = jaccard(left.keywords, right.keywords)
    source_score = jaccard(left.text_unit_ids, right.text_unit_ids)
    type_score = cosine_counts(left.type_counts, right.type_counts)
    small_bonus = 0.15 if min(left.size, right.size) <= max(3, avg_size * 0.35) else 0.0

    final_score = (
        graph_score * 0.42
        + text_score * 0.24
        + source_score * 0.18
        + type_score * 0.11
        + small_bonus
    )
    return {
        "left": left.community,
        "right": right.community,
        "left_title": left.title,
        "right_title": right.title,
        "left_size": left.size,
        "right_size": right.size,
        "score": round(final_score, 4),
        "graph_score": round(graph_score, 4),
        "text_score": round(text_score, 4),
        "source_score": round(source_score, 4),
        "type_score": round(type_score, 4),
        "small_bonus": round(small_bonus, 4),
        "bridge_edges": edge_count,
        "bridge_weight": round(weight_sum, 2),
        "shared_keywords": sorted(left.keywords & right.keywords)[:12],
        "relationship_examples": bridge["examples"],
    }


def find_merge_candidates(
    profiles: dict[int, CommunityProfile],
    relationships: pd.DataFrame,
    top_pairs: int,
) -> list[dict[str, Any]]:
    _, name_to_community = build_entity_community_map(profiles)
    bridges = relationship_bridge_scores(relationships, name_to_community)
    communities = sorted(profiles)
    avg_size = sum(profile.size for profile in profiles.values()) / len(profiles)

    candidates = []
    for idx, left_id in enumerate(communities):
        for right_id in communities[idx + 1 :]:
            pair = (left_id, right_id)
            scored = score_merge_pair(
                profiles[left_id],
                profiles[right_id],
                bridges.get(pair),
                avg_size,
            )
            if scored["score"] >= 0.18 or scored["bridge_edges"] > 0:
                candidates.append(scored)

    candidates.sort(
        key=lambda item: (
            item["score"],
            item["bridge_edges"],
            item["source_score"],
            -max(item["left_size"], item["right_size"]),
        ),
        reverse=True,
    )
    return candidates[:top_pairs]


def connected_components(names: set[str], relationships: pd.DataFrame) -> list[list[str]]:
    adjacency: dict[str, set[str]] = {name: set() for name in names}
    for row in relationships.itertuples(index=False):
        source = str(row.source)
        target = str(row.target)
        if source in names and target in names:
            adjacency[source].add(target)
            adjacency[target].add(source)

    seen: set[str] = set()
    components: list[list[str]] = []
    for name in sorted(names):
        if name in seen:
            continue
        queue = deque([name])
        seen.add(name)
        component = []
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        components.append(sorted(component))
    components.sort(key=len, reverse=True)
    return components


def extract_section_title(text: str) -> str:
    headings = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                headings.append(title)
    if not headings:
        return "소제목 없음"
    return " > ".join(headings[-3:])


def build_text_unit_sections(text_units: pd.DataFrame) -> dict[str, str]:
    return {
        str(row.id): extract_section_title(str(row.text or ""))
        for row in text_units.itertuples(index=False)
    }


def section_groups_for_profile(
    profile: CommunityProfile,
    entities: pd.DataFrame,
    text_unit_sections: dict[str, str],
) -> list[dict[str, Any]]:
    entity_by_name = {str(row.title): row for row in entities.itertuples(index=False)}
    groups: dict[str, set[str]] = defaultdict(set)
    for name in profile.entity_names:
        entity = entity_by_name.get(name)
        if entity is None:
            continue
        for text_unit_id in as_set(entity.text_unit_ids):
            section = text_unit_sections.get(text_unit_id)
            if section:
                groups[section].add(name)

    result = [
        {"section": section, "entity_count": len(names), "entities": sorted(names)[:30]}
        for section, names in groups.items()
    ]
    result.sort(key=lambda item: item["entity_count"], reverse=True)
    return result[:10]


def find_size_flags(
    profiles: dict[int, CommunityProfile],
    small_threshold: int | None,
    large_threshold: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sizes = [profile.size for profile in profiles.values()]
    avg_size = sum(sizes) / len(sizes)
    if small_threshold is None:
        small_threshold = max(3, int(avg_size * 0.35))
    if large_threshold is None:
        large_threshold = max(25, int(avg_size * 1.8))

    small = []
    large = []
    for profile in sorted(profiles.values(), key=lambda item: item.size):
        item = {
            "community": profile.community,
            "title": profile.title,
            "size": profile.size,
            "top_entities": sorted(profile.entity_names)[:15],
        }
        if profile.size <= small_threshold:
            small.append(item)
        if profile.size >= large_threshold:
            large.append(item)
    return small, large


def find_split_candidates(
    profiles: dict[int, CommunityProfile],
    relationships: pd.DataFrame,
    entities: pd.DataFrame,
    text_units: pd.DataFrame,
    large_flags: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    text_unit_sections = build_text_unit_sections(text_units)
    split_candidates = []
    for flag in large_flags:
        profile = profiles[int(flag["community"])]
        components = connected_components(profile.entity_names, relationships)
        useful_components = [component for component in components if len(component) >= 2]
        isolated = [component[0] for component in components if len(component) == 1]
        split_candidates.append(
            {
                "community": profile.community,
                "title": profile.title,
                "size": profile.size,
                "component_count": len(components),
                "large_components": useful_components[:8],
                "isolated_entities": isolated[:20],
                "source_section_groups": section_groups_for_profile(
                    profile, entities, text_unit_sections
                ),
                "reason": "큰 커뮤니티는 그래프 연결 성분과 원문 소제목 단위 엔티티 묶음을 함께 보고 분할 후보로 검토합니다.",
            }
        )
    return split_candidates


def find_anomalies(
    profiles: dict[int, CommunityProfile], entities: pd.DataFrame
) -> list[dict[str, Any]]:
    _, name_to_community = build_entity_community_map(profiles)
    entities_by_name = {str(row.title): row for row in entities.itertuples(index=False)}
    names = sorted(entities_by_name)

    anomalies = []
    for name in names:
        entity = entities_by_name[name]
        community = name_to_community.get(name)
        entity_type = str(entity.type)
        reasons = []
        candidates = []

        if entity_type not in ALLOWED_ENTITY_TYPES:
            reasons.append("허용 목록 밖 entity_type")
        if name in GENERIC_ENTITY_NAMES:
            reasons.append("너무 일반적인 엔티티명")
        if len(name) <= 1:
            reasons.append("1글자 엔티티명")
        if entity_type == "인물" and len(name) <= 2:
            reasons.append("짧은 인명")
        if int(getattr(entity, "degree", 0) or 0) <= 0:
            reasons.append("관계 degree 0")

        for other in names:
            if other == name:
                continue
            if len(other) <= len(name):
                continue
            if name in other:
                other_entity = entities_by_name[other]
                source_overlap = jaccard(
                    as_set(entity.text_unit_ids), as_set(other_entity.text_unit_ids)
                )
                desc_score = jaccard(
                    tokenize(str(entity.description or "")),
                    tokenize(str(other_entity.description or "")),
                )
                same_type = entity_type == str(other_entity.type)
                other_community = name_to_community.get(other)
                same_community = community is not None and community == other_community
                if same_type or desc_score >= 0.08:
                    confidence = (
                        (0.45 if same_community else 0.0)
                        + source_overlap * 0.35
                        + desc_score * 0.15
                        + (0.05 if same_type else 0.0)
                    )
                    candidates.append(
                        {
                            "candidate": other,
                            "community": other_community,
                            "type": str(other_entity.type),
                            "same_community": same_community,
                            "source_overlap": round(source_overlap, 4),
                            "description_overlap": round(desc_score, 4),
                            "alias_confidence": round(confidence, 4),
                        }
                    )
        candidates.sort(
            key=lambda item: (
                item["same_community"],
                item["source_overlap"],
                item["description_overlap"],
                item["alias_confidence"],
            ),
            reverse=True,
        )
        if candidates:
            reasons.append("더 긴 엔티티명의 일부일 가능성")

        if reasons:
            anomalies.append(
                {
                    "entity": name,
                    "type": entity_type,
                    "community": community,
                    "degree": int(getattr(entity, "degree", 0) or 0),
                    "frequency": int(getattr(entity, "frequency", 0) or 0),
                    "reasons": reasons,
                    "alias_or_move_candidates": candidates[:5],
                    "description": str(entity.description or "")[:240],
                }
            )
    anomalies.sort(
        key=lambda item: (
            "1글자 엔티티명" not in item["reasons"],
            "허용 목록 밖 entity_type" not in item["reasons"],
            item["degree"],
            item["entity"],
        )
    )
    return anomalies


def build_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# GraphRAG 커뮤니티 병합 후보 분석",
        "",
        f"- 기준 폴더: `{result['base']}`",
        f"- 커뮤니티 수: {result['stats']['community_count']}",
        f"- 평균 엔티티 수: {result['stats']['avg_size']:.2f}",
        f"- 목표 방 수 참고값: {result['target_rooms']}개",
        "",
        "## 1. 우선 병합 후보",
    ]
    for item in result["merge_candidates"][:15]:
        lines.extend(
            [
                "",
                f"### {item['left']} + {item['right']} | score {item['score']}",
                f"- {item['left_title']} ({item['left_size']})",
                f"- {item['right_title']} ({item['right_size']})",
                f"- 그래프/텍스트/섹션/타입: {item['graph_score']} / {item['text_score']} / {item['source_score']} / {item['type_score']}",
                f"- 관계 엣지/가중치: {item['bridge_edges']} / {item['bridge_weight']}",
                f"- 공유 키워드: {', '.join(item['shared_keywords']) or '-'}",
            ]
        )
        for example in item["relationship_examples"][:3]:
            lines.append(
                f"- 관계 예시: {example['source']} -> {example['target']} "
                f"(w={example['weight']})"
            )

    lines.extend(["", "## 2. 작은 커뮤니티"])
    for item in result["small_communities"]:
        lines.append(f"- {item['community']}: {item['title']} ({item['size']})")

    lines.extend(["", "## 3. 큰 커뮤니티/분할 후보"])
    for item in result["split_candidates"]:
        lines.extend(
            [
                "",
                f"### {item['community']}: {item['title']} ({item['size']})",
                f"- 내부 연결 성분 수: {item['component_count']}",
            ]
        )
        for component in item["large_components"][:5]:
            lines.append(f"- 성분: {', '.join(component[:12])}")
        if item["isolated_entities"]:
            lines.append(f"- 고립 후보: {', '.join(item['isolated_entities'][:12])}")
        if item["source_section_groups"]:
            lines.append("- 원문 소제목별 묶음:")
            for group in item["source_section_groups"][:5]:
                lines.append(
                    f"  - {group['section']} ({group['entity_count']}): "
                    f"{', '.join(group['entities'][:12])}"
                )

    lines.extend(["", "## 4. 이상 엔티티 후보"])
    for item in result["anomalies"][:40]:
        reasons = ", ".join(item["reasons"])
        lines.append(
            f"- {item['entity']} [{item['type']}] community={item['community']} "
            f"degree={item['degree']} | {reasons}"
        )
        if item["alias_or_move_candidates"]:
            aliases = ", ".join(
                f"{candidate['candidate']}(c={candidate['community']}, "
                f"same={candidate.get('same_community')}, "
                f"src={candidate.get('source_overlap')}, "
                f"conf={candidate.get('alias_confidence')})"
                for candidate in item["alias_or_move_candidates"]
            )
            lines.append(f"  - 후보: {aliases}")

    lines.extend(
        [
            "",
            "## 사용법",
            "- 이 결과는 확정 병합표가 아니라 LLM/사람이 검토할 후보 목록입니다.",
            "- 2단계에서는 score가 높은 병합 후보와 작은 커뮤니티를 먼저 보고, 큰 커뮤니티는 내부 연결 성분 기준으로 분할 후보를 검토합니다.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    base = args.base or find_default_base()
    frames = load_frames(base)
    profiles = build_profiles(frames)
    sizes = [profile.size for profile in profiles.values()]
    avg_size = sum(sizes) / len(sizes)

    small_flags, large_flags = find_size_flags(
        profiles, args.small_threshold, args.large_threshold
    )
    result = {
        "base": str(base),
        "target_rooms": args.target_rooms,
        "stats": {
            "community_count": len(profiles),
            "entity_count": int(len(frames["entities"])),
            "relationship_count": int(len(frames["relationships"])),
            "avg_size": avg_size,
            "min_size": min(sizes),
            "max_size": max(sizes),
        },
        "small_communities": small_flags,
        "large_communities": large_flags,
        "merge_candidates": find_merge_candidates(
            profiles, frames["relationships"], args.top_pairs
        ),
        "split_candidates": find_split_candidates(
            profiles,
            frames["relationships"],
            frames["entities"],
            frames["text_units"],
            large_flags,
        ),
        "anomalies": find_anomalies(profiles, frames["entities"]),
    }

    json_path = base / "merge_analysis.json"
    md_path = base / "merge_analysis.md"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(build_markdown(result), encoding="utf-8")

    print(f"Base: {base}")
    print(f"Communities: {result['stats']['community_count']}")
    print(f"Merge candidates: {len(result['merge_candidates'])}")
    print(f"Small communities: {len(result['small_communities'])}")
    print(f"Large communities: {len(result['large_communities'])}")
    print(f"Anomalies: {len(result['anomalies'])}")
    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")


if __name__ == "__main__":
    main()
