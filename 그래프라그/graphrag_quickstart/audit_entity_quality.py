from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_BASE = Path(
    "output/그래프라그 방나누기/gpt4.1mini/10차_프롬프트/10차(수정)"
)
DEFAULT_OUTPUT = Path(
    "output/그래프라그 방나누기/gpt4.1mini/11차/entity_quality_audit.md"
)

ALIASES = {
    "세종대왕": "세종",
    "태종이방원": "태종",
    "이방원": "태종",
    "방원": "태종",
    "명나라": "명",
    "유정사명대사": "유정",
    "사명대사유정": "유정",
    "백성들": "백성",
    "철포": "조총",
}

GENERIC_WORDS = {
    "조선",
    "정부",
    "국가",
    "사회",
    "정치",
    "경제",
    "백성",
    "백성들",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only audit for duplicate entities, type inconsistencies, and orphan entities."
    )
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def normalize_title(title: str) -> str:
    text = re.sub(r"\s+", "", title)
    text = re.sub(r"[()·ㆍ⋅,./:;'\"]", "", text)
    return ALIASES.get(text, text)


def normalize_type(entity_type: str) -> str:
    return re.sub(r"[\s,/_·ㆍ⋅]+", "|", str(entity_type).strip())


def token_set(entity_type: str) -> set[str]:
    return {token for token in re.split(r"[\s,/_·ㆍ⋅|]+", str(entity_type)) if token}


def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_title(left), normalize_title(right)).ratio()


def read_frames(base: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    entities = pd.read_parquet(base / "entities.parquet")
    relationships = pd.read_parquet(base / "relationships.parquet")
    text_units = pd.read_parquet(base / "text_units.parquet")
    return entities, relationships, text_units


def find_duplicate_candidates(entities: pd.DataFrame) -> list[dict[str, Any]]:
    rows = list(entities.itertuples(index=False))
    by_norm: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        by_norm[normalize_title(str(row.title))].append(row)

    candidates: list[dict[str, Any]] = []
    for norm, group in by_norm.items():
        if len(group) > 1:
            candidates.append(make_duplicate_payload("same_normalized_title", norm, group))

    for i, left in enumerate(rows):
        left_title = str(left.title)
        if len(left_title) < 2 or left_title in GENERIC_WORDS:
            continue
        for right in rows[i + 1 :]:
            right_title = str(right.title)
            if len(right_title) < 2 or right_title in GENERIC_WORDS:
                continue
            n_left = normalize_title(left_title)
            n_right = normalize_title(right_title)
            if n_left == n_right:
                continue
            contains = n_left in n_right or n_right in n_left
            similar = title_similarity(left_title, right_title) >= 0.86
            if contains or similar:
                candidates.append(
                    make_duplicate_payload(
                        "substring_or_high_similarity", f"{n_left}~{n_right}", [left, right]
                    )
                )

    seen = set()
    unique = []
    for item in candidates:
        key = tuple(sorted(entity["id"] for entity in item["entities"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique.sort(
        key=lambda item: (
            -sum(entity["degree"] for entity in item["entities"]),
            item["reason"],
        )
    )
    return unique


def make_duplicate_payload(reason: str, normalized: str, group: list[Any]) -> dict[str, Any]:
    return {
        "reason": reason,
        "normalized": normalized,
        "entities": [
            {
                "id": int(row.human_readable_id),
                "title": str(row.title),
                "type": str(row.type),
                "frequency": int(row.frequency),
                "degree": int(row.degree),
            }
            for row in group
        ],
    }


def find_type_inconsistencies(entities: pd.DataFrame) -> list[dict[str, Any]]:
    groups: dict[str, list[Any]] = defaultdict(list)
    for row in entities.itertuples(index=False):
        raw = str(row.type)
        if normalize_type(raw) != raw or len(token_set(raw)) > 1:
            groups[normalize_type(raw)].append(row)

    items = []
    for normalized, rows in groups.items():
        raw_types = sorted({str(row.type) for row in rows})
        items.append(
            {
                "normalized_suggestion": normalized,
                "raw_types": raw_types,
                "count": len(rows),
                "examples": [
                    {
                        "id": int(row.human_readable_id),
                        "title": str(row.title),
                        "type": str(row.type),
                    }
                    for row in rows[:12]
                ],
            }
        )
    items.sort(key=lambda item: (-item["count"], item["normalized_suggestion"]))
    return items


def find_orphans(
    entities: pd.DataFrame, relationships: pd.DataFrame, text_units: pd.DataFrame
) -> list[dict[str, Any]]:
    titles_with_edges = set(relationships["source"].astype(str)) | set(
        relationships["target"].astype(str)
    )
    orphan_rows = [
        row
        for row in entities.itertuples(index=False)
        if int(row.degree) == 0 or str(row.title) not in titles_with_edges
    ]
    title_to_row = {str(row.title): row for row in entities.itertuples(index=False)}
    text_entity_ids = {
        str(row.id): [str(eid) for eid in row.entity_ids]
        for row in text_units.itertuples(index=False)
    }
    entity_id_to_title = {
        str(row.id): str(row.title) for row in entities.itertuples(index=False)
    }

    results = []
    for row in orphan_rows:
        text_ids = [str(item) for item in row.text_unit_ids]
        co_mentions = defaultdict(int)
        for text_id in text_ids:
            for entity_uuid in text_entity_ids.get(text_id, []):
                title = entity_id_to_title.get(entity_uuid)
                if title and title != str(row.title) and title in title_to_row:
                    co_mentions[title] += 1
        candidates = []
        for title, count in sorted(co_mentions.items(), key=lambda item: -item[1])[:8]:
            other = title_to_row[title]
            candidates.append(
                {
                    "title": title,
                    "type": str(other.type),
                    "degree": int(other.degree),
                    "co_text_units": count,
                }
            )
        results.append(
            {
                "id": int(row.human_readable_id),
                "title": str(row.title),
                "type": str(row.type),
                "frequency": int(row.frequency),
                "degree": int(row.degree),
                "co_mention_candidates": candidates,
                "description": truncate(str(row.description), 220),
            }
        )
    results.sort(key=lambda item: (-item["frequency"], item["title"]))
    return results


def truncate(text: str, max_len: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def write_markdown(
    output: Path,
    duplicates: list[dict[str, Any]],
    type_issues: list[dict[str, Any]],
    orphans: list[dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    lines = [
        "# Entity Quality Audit",
        "",
        "읽기 전용 점검 결과입니다. 이 파일은 엔티티/관계를 수정하지 않고 후보만 나열합니다.",
        "",
        "## Summary",
        "",
        f"- duplicate candidates: {len(duplicates)}",
        f"- type notation issues: {len(type_issues)}",
        f"- orphan/degree-zero candidates: {len(orphans)}",
        "",
        "## 1. 중복 엔티티 후보",
        "",
    ]
    for item in duplicates[:80]:
        names = ", ".join(
            f"{entity['title']}#{entity['id']}(deg={entity['degree']}, freq={entity['frequency']}, type={entity['type']})"
            for entity in item["entities"]
        )
        lines.append(f"- [{item['reason']}] {item['normalized']}: {names}")

    lines.extend(["", "## 2. Type 표기 불일치 후보", ""])
    for item in type_issues:
        raw = ", ".join(item["raw_types"])
        examples = ", ".join(
            f"{example['title']}#{example['id']}:{example['type']}"
            for example in item["examples"][:8]
        )
        lines.append(
            f"- `{item['normalized_suggestion']}` count={item['count']} raw=[{raw}] examples={examples}"
        )

    lines.extend(["", "## 3. Orphan / Degree 0 후보", ""])
    for item in orphans[:120]:
        co = ", ".join(
            f"{candidate['title']}(co={candidate['co_text_units']}, deg={candidate['degree']})"
            for candidate in item["co_mention_candidates"][:5]
        )
        lines.append(
            f"- {item['title']}#{item['id']} type={item['type']} freq={item['frequency']} degree={item['degree']} | co_mentions: {co}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    output.with_suffix(".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    args = parse_args()
    entities, relationships, text_units = read_frames(args.base)
    duplicates = find_duplicate_candidates(entities)
    type_issues = find_type_inconsistencies(entities)
    orphans = find_orphans(entities, relationships, text_units)
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "base": str(args.base),
        "summary": {
            "duplicate_candidates": len(duplicates),
            "type_notation_issues": len(type_issues),
            "orphan_candidates": len(orphans),
        },
        "duplicates": duplicates,
        "type_issues": type_issues,
        "orphans": orphans,
    }
    write_markdown(args.output, duplicates, type_issues, orphans, payload)
    print(f"Wrote: {args.output}")
    print(f"Wrote: {args.output.with_suffix('.json')}")
    print(payload["summary"])


if __name__ == "__main__":
    main()
