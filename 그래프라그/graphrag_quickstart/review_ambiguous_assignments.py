from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openai import AzureOpenAI

from run_merge_judgement import DEFAULT_CONFIG, load_config, load_dotenv
from build_final_rooms import build_comparison_markdown, build_final_markdown, extract_anomaly_section


DEFAULT_BASE_GLOB = "output/*/gpt4.1mini/10차_프롬프트/10차(수정)"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Review low-confidence final room assignments with GPT-5.4 mini."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--threshold", type=float, default=0.09)
    parser.add_argument("--max-candidates", type=int, default=8)
    return parser.parse_args()


def find_base() -> Path:
    matches = sorted(Path(".").glob(DEFAULT_BASE_GLOB))
    if not matches:
        raise FileNotFoundError(DEFAULT_BASE_GLOB)
    return matches[-1]


def load_original_communities(base: Path) -> dict[int, dict[str, Any]]:
    reports = pd.read_parquet(base / "community_reports.parquet")
    return {
        int(row.community): {
            "community": int(row.community),
            "title": str(row.title),
            "size": int(row.size),
            "summary": str(row.summary or ""),
        }
        for row in reports.sort_values("community").itertuples(index=False)
    }


def select_candidates(final_data: dict[str, Any], threshold: float, max_candidates: int) -> list[dict[str, Any]]:
    scores = {
        int(cid): float(score)
        for cid, score in final_data.get("diagnostics", {})
        .get("assignment_scores", {})
        .items()
    }
    rows = []
    for room in final_data["rooms"]:
        for cid in room.get("source_communities", []):
            score = scores.get(int(cid), 1.0)
            if score <= threshold:
                rows.append(
                    {
                        "community": int(cid),
                        "current_room_no": room["room_no"],
                        "current_room_title": room["title"],
                        "assignment_score": score,
                    }
                )
    rows.sort(key=lambda item: item["assignment_score"])
    return rows[:max_candidates]


def build_prompt(
    rooms: list[dict[str, Any]],
    original: dict[int, dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> str:
    room_lines = []
    for room in rooms:
        room_lines.append(
            {
                "room_no": room["room_no"],
                "title": room["title"],
                "period_order": room.get("period_order", ""),
                "core_content": room.get("core_content", ""),
                "main_entities": room.get("main_entities", []),
                "subzones": room.get("subzones", []),
                "source_communities": room.get("source_communities", []),
            }
        )
    candidate_lines = []
    for item in candidates:
        info = original[item["community"]]
        candidate_lines.append(
            {
                **item,
                "community_title": info["title"],
                "community_size": info["size"],
                "community_summary": info["summary"],
            }
        )

    return f"""
당신은 한국사 GraphRAG 후처리 결과의 애매한 커뮤니티 배치를 재검토하는 검토자입니다.

아래에는 최종 방 목록과, 로컬 검증기가 낮은 유사도 점수로 강제 배치한 원본 커뮤니티 후보가 있습니다.
전체 방 구조를 새로 만들지 말고, 주어진 후보 커뮤니티만 재검토하십시오.

판단 원칙:
- 현재 방이 의미상 자연스러우면 keep.
- 더 적절한 기존 방이 있으면 move와 target_room_no를 제시.
- 기존 방 어디에도 자연스럽지 않으면 new_room_needed.
- 형식 검증을 위해 각 원본 커뮤니티는 최종적으로 하나의 방에만 있어야 합니다.
- 역사 학습 순서와 주제 일관성을 우선합니다.
- target_room_no는 반드시 아래 최종 방 목록에 있는 번호 중 하나여야 합니다.
- target_room_title은 반드시 해당 번호의 방 제목과 정확히 같아야 합니다.
- 이유(reason)가 target_room_no/target_room_title과 충돌하면 안 됩니다.

반드시 JSON만 출력하십시오.

출력 형식:
{{
  "decisions": [
    {{
      "community": 25,
      "decision": "keep|move|new_room_needed",
      "target_room_no": 6,
      "target_room_title": "기존 최종 방 제목 또는 새 방 제목",
      "confidence": 0.0,
      "reason": "짧은 이유"
    }}
  ]
}}

최종 방 목록:
{json.dumps(room_lines, ensure_ascii=False, indent=2)}

재검토 후보:
{json.dumps(candidate_lines, ensure_ascii=False, indent=2)}
""".strip()


def call_model(config: dict[str, Any], prompt: str) -> tuple[str, Any]:
    azure = config["azure_openai"]
    client = AzureOpenAI(
        azure_endpoint=azure["endpoint"],
        api_key=azure["api_key"],
        api_version=azure["api_version"],
    )
    response = client.chat.completions.create(
        model=azure["deployment_name"],
        messages=[
            {
                "role": "system",
                "content": "You make conservative Korean history learning-structure placement decisions and output strict JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=float(azure.get("temperature", 0.0)),
        max_completion_tokens=3000,
    )
    return response.choices[0].message.content or "", getattr(response, "usage", None)


def parse_json_response(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in model response.")
    return json.loads(match.group(0))


def validate_decisions(final_data: dict[str, Any], decisions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rooms_by_no = {int(room["room_no"]): room for room in final_data["rooms"]}
    valid = []
    unresolved = []
    for decision in decisions:
        item = dict(decision)
        action = item.get("decision")
        if action not in {"keep", "move", "new_room_needed"}:
            item["validation_error"] = "unknown decision label"
            unresolved.append(item)
            continue
        if action == "move":
            target_no = item.get("target_room_no")
            if target_no is None or int(target_no) not in rooms_by_no:
                item["validation_error"] = "target_room_no does not exist"
                unresolved.append(item)
                continue
            expected_title = rooms_by_no[int(target_no)]["title"]
            target_title = str(item.get("target_room_title") or "").strip()
            if target_title != expected_title:
                item["validation_error"] = (
                    f"target_room_title mismatch: expected '{expected_title}', got '{target_title}'"
                )
                unresolved.append(item)
                continue
        valid.append(item)
    return valid, unresolved


def apply_decisions(final_data: dict[str, Any], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    rooms_by_no = {int(room["room_no"]): room for room in final_data["rooms"]}
    for decision in decisions:
        cid = int(decision["community"])
        action = decision.get("decision")
        if action != "move":
            continue
        target = decision.get("target_room_no")
        if target is None or int(target) not in rooms_by_no:
            continue
        target_room = rooms_by_no[int(target)]
        for room in final_data["rooms"]:
            room["source_communities"] = [
                int(existing)
                for existing in room.get("source_communities", [])
                if int(existing) != cid
            ]
        target_room.setdefault("source_communities", []).append(cid)
    for room in final_data["rooms"]:
        room["source_communities"] = sorted(set(map(int, room.get("source_communities", []))))
    return final_data


def write_outputs(
    base: Path,
    final_data: dict[str, Any],
    original: dict[int, dict[str, Any]],
    review_payload: dict[str, Any],
    raw_response: str,
    usage: Any,
) -> None:
    review_md = base / "ambiguous_assignment_review_gpt5.4mini.md"
    review_json = base / "ambiguous_assignment_review_gpt5.4mini.json"
    final_json = base / "final_rooms_gpt5.4mini.json"
    final_md = base / "final_rooms_gpt5.4mini.md"
    comparison = base / "comparison_original_vs_final.md"
    judgement_text = (base / "merge_judgement_gpt5.4mini.md").read_text(encoding="utf-8")
    anomaly_section = extract_anomaly_section(judgement_text)

    review = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "usage": usage.model_dump() if hasattr(usage, "model_dump") else str(usage),
        "review": review_payload,
        "raw_response": raw_response,
    }
    review_json.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# 애매한 원본 커뮤니티 배치 재검토", ""]
    lines.append("## 검증 통과 결정")
    lines.append("")
    for item in review_payload.get("valid_decisions", []):
        lines.extend(
            [
                f"## 원본 커뮤니티 {item.get('community')}",
                f"- 판단: {item.get('decision')}",
                f"- 대상 방: {item.get('target_room_no')}",
                f"- 대상 방 제목: {item.get('target_room_title')}",
                f"- 신뢰도: {item.get('confidence')}",
                f"- 이유: {item.get('reason')}",
                "",
            ]
        )
    lines.append("## 미해결/검증 실패")
    lines.append("")
    unresolved = review_payload.get("unresolved_decisions", [])
    if not unresolved:
        lines.append("- 없음")
        lines.append("")
    for item in unresolved:
        lines.extend(
            [
                f"### 원본 커뮤니티 {item.get('community')}",
                f"- 판단: {item.get('decision')}",
                f"- 대상 방: {item.get('target_room_no')}",
                f"- 대상 방 제목: {item.get('target_room_title')}",
                f"- 검증 실패 사유: {item.get('validation_error')}",
                f"- 이유: {item.get('reason')}",
                "",
            ]
        )
    review_md.write_text("\n".join(lines), encoding="utf-8")

    final_data["reviewed_ambiguous_assignments"] = review_payload
    final_json.write_text(json.dumps(final_data, ensure_ascii=False, indent=2), encoding="utf-8")
    final_md.write_text(
        build_final_markdown(
            final_data["rooms"],
            original,
            anomaly_section,
            final_data.get("diagnostics", {}),
        ),
        encoding="utf-8",
    )
    comparison.write_text(
        build_comparison_markdown(final_data["rooms"], original), encoding="utf-8"
    )

    print(f"Wrote: {review_md}")
    print(f"Wrote: {review_json}")
    print(f"Updated: {final_md}")
    print(f"Updated: {final_json}")
    print(f"Updated: {comparison}")
    if usage:
        print(f"Usage: {usage}")


def main() -> None:
    args = parse_args()
    load_dotenv(Path(".env"))
    config = load_config(args.config)
    base = find_base()
    final_path = base / "final_rooms_gpt5.4mini.json"
    final_data = json.loads(final_path.read_text(encoding="utf-8"))
    original = load_original_communities(base)
    candidates = select_candidates(final_data, args.threshold, args.max_candidates)
    print(f"Review candidates: {[item['community'] for item in candidates]}")
    prompt = build_prompt(final_data["rooms"], original, candidates)
    raw_response, usage = call_model(config, prompt)
    review_payload = parse_json_response(raw_response)
    valid_decisions, unresolved_decisions = validate_decisions(
        final_data, review_payload.get("decisions", [])
    )
    review_payload = {
        **review_payload,
        "candidate_selection": {
            "threshold": args.threshold,
            "max_candidates": args.max_candidates,
            "candidates": candidates,
        },
        "valid_decisions": valid_decisions,
        "unresolved_decisions": unresolved_decisions,
    }
    final_data = apply_decisions(final_data, valid_decisions)
    write_outputs(base, final_data, original, review_payload, raw_response, usage)


if __name__ == "__main__":
    main()
