from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openai import AzureOpenAI

from run_merge_judgement import DEFAULT_CONFIG, load_config, load_dotenv


DEFAULT_BASE_GLOB = "output/*/gpt4.1mini/10차_프롬프트/10차(수정)"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Review semantic quality of final GraphRAG memory rooms."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--coherence-threshold", type=float, default=0.08)
    parser.add_argument("--max-rooms", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true")
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


def tokenize(text: str) -> set[str]:
    stopwords = {
        "조선",
        "시대",
        "전기",
        "중기",
        "후기",
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
        "방어",
        "강화",
        "개혁",
    }
    return {
        token
        for token in re.findall(r"[가-힣A-Za-z0-9]+", text or "")
        if len(token) >= 2 and token not in stopwords
    }


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def room_text(room: dict[str, Any]) -> str:
    return " ".join(
        [
            str(room.get("title", "")),
            str(room.get("period_order", "")),
            str(room.get("core_content", "")),
            " ".join(room.get("main_entities", [])),
            " ".join(room.get("subzones", [])),
        ]
    )


def select_suspect_rooms(
    final_data: dict[str, Any],
    original: dict[int, dict[str, Any]],
    threshold: float,
    max_rooms: int,
) -> list[dict[str, Any]]:
    suspects = []
    assignment_scores = {
        int(cid): float(score)
        for cid, score in final_data.get("diagnostics", {})
        .get("assignment_scores", {})
        .items()
    }
    for room in final_data["rooms"]:
        r_tokens = tokenize(room_text(room))
        community_scores = []
        low_communities = []
        for cid in room.get("source_communities", []):
            cid = int(cid)
            info = original.get(cid)
            if not info:
                continue
            c_tokens = tokenize(info["title"] + " " + info["summary"])
            lexical_score = jaccard(r_tokens, c_tokens)
            assignment_score = assignment_scores.get(cid, lexical_score)
            combined = max(lexical_score, assignment_score)
            item = {
                "community": cid,
                "title": info["title"],
                "size": info["size"],
                "summary": info["summary"][:500],
                "lexical_score": round(lexical_score, 4),
                "assignment_score": round(assignment_score, 4),
                "combined_score": round(combined, 4),
            }
            community_scores.append(item)
            if combined < threshold:
                low_communities.append(item)

        avg_score = (
            sum(item["combined_score"] for item in community_scores)
            / len(community_scores)
            if community_scores
            else 0.0
        )
        reason_flags = []
        if low_communities:
            reason_flags.append("low_community_room_similarity")
        if len(room.get("source_communities", [])) >= 5:
            reason_flags.append("many_source_communities")
        if avg_score < threshold * 1.25:
            reason_flags.append("low_average_coherence")
        if reason_flags:
            suspects.append(
                {
                    "room_no": room["room_no"],
                    "title": room["title"],
                    "period_order": room.get("period_order", ""),
                    "core_content": room.get("core_content", ""),
                    "main_entities": room.get("main_entities", []),
                    "subzones": room.get("subzones", []),
                    "source_communities": room.get("source_communities", []),
                    "avg_score": round(avg_score, 4),
                    "reason_flags": reason_flags,
                    "low_communities": low_communities,
                    "all_communities": community_scores,
                }
            )

    suspects.sort(
        key=lambda item: (
            len(item["low_communities"]),
            "low_average_coherence" in item["reason_flags"],
            len(item["source_communities"]),
        ),
        reverse=True,
    )
    return suspects[:max_rooms]


def build_prompt(final_data: dict[str, Any], suspects: list[dict[str, Any]]) -> str:
    rooms = [
        {
            "room_no": room["room_no"],
            "title": room["title"],
            "period_order": room.get("period_order", ""),
            "core_content": room.get("core_content", ""),
            "main_entities": room.get("main_entities", []),
            "subzones": room.get("subzones", []),
            "source_communities": room.get("source_communities", []),
        }
        for room in final_data["rooms"]
    ]
    return f"""
당신은 한국사 학습용 3D 기억방 구조의 최종 의미 품질 검증자입니다.

아래 최종 방 목록과 로컬 알고리즘이 의심한 방 목록을 보고, 방의 의미 품질을 평가하십시오.
전체 방 구조를 새로 만들지 말고, 의심 방만 평가하십시오.

검증 기준:
- 방 제목과 포함 원본 커뮤니티가 의미상 맞는가?
- 시대/순서가 너무 넓거나 모순되지 않는가?
- 서로 다른 학습 주제가 한 방에 억지로 섞이지 않았는가?
- 하위 구역으로 처리하면 충분한가, 별도 방/이동이 필요한가?
- 기존 방 중 더 적절한 방이 있는가?

반드시 JSON만 출력하십시오.

출력 형식:
{{
  "room_reviews": [
    {{
      "room_no": 9,
      "verdict": "ok|needs_adjustment|needs_split|needs_new_room",
      "quality_score": 0.0,
      "problematic_communities": [25],
      "recommended_actions": [
        {{
          "community": 25,
          "action": "keep|move|split_out|new_room",
          "target_room_no": 10,
          "reason": "짧은 이유"
        }}
      ],
      "comment": "방 전체 평가"
    }}
  ]
}}

최종 방 전체 목록:
{json.dumps(rooms, ensure_ascii=False, indent=2)}

로컬 알고리즘이 의심한 방:
{json.dumps(suspects, ensure_ascii=False, indent=2)}
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
                "content": "You evaluate Korean history memory-room semantic quality and output strict JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=float(azure.get("temperature", 0.0)),
        max_completion_tokens=4000,
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


def build_markdown(review: dict[str, Any], suspects: list[dict[str, Any]]) -> str:
    suspect_by_room = {int(item["room_no"]): item for item in suspects}
    lines = [
        "# 최종 방 의미 품질 검증",
        "",
        "이 파일은 최종 방 구성을 다시 생성하지 않고, 로컬 알고리즘이 의심한 방만 GPT-5.4 mini로 의미 검증한 결과입니다.",
        "",
        "## 로컬 의심 방",
    ]
    for suspect in suspects:
        low = ", ".join(
            f"{item['community']}:{item['title']}"
            for item in suspect["low_communities"]
        )
        lines.extend(
            [
                f"- 방 {suspect['room_no']}: {suspect['title']}",
                f"  - 의심 사유: {', '.join(suspect['reason_flags'])}",
                f"  - 낮은 유사도 커뮤니티: {low or '없음'}",
            ]
        )

    lines.extend(["", "## LLM 의미 검증 결과"])
    for item in review.get("room_reviews", []):
        room_no = int(item.get("room_no"))
        suspect = suspect_by_room.get(room_no, {})
        lines.extend(
            [
                "",
                f"### 방 {room_no}: {suspect.get('title', '')}",
                f"- 판정: {item.get('verdict')}",
                f"- 품질 점수: {item.get('quality_score')}",
                f"- 문제 커뮤니티: {item.get('problematic_communities', [])}",
                f"- 코멘트: {item.get('comment')}",
                "- 권장 조치:",
            ]
        )
        for action in item.get("recommended_actions", []):
            lines.append(
                f"  - community {action.get('community')}: {action.get('action')} "
                f"-> {action.get('target_room_no')} | {action.get('reason')}"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    load_dotenv(Path(".env"))
    config = load_config(args.config)
    base = find_base()
    final_data = json.loads((base / "final_rooms_gpt5.4mini.json").read_text(encoding="utf-8"))
    original = load_original_communities(base)
    suspects = select_suspect_rooms(
        final_data, original, args.coherence_threshold, args.max_rooms
    )

    output_json = base / "semantic_quality_review_gpt5.4mini.json"
    output_md = base / "semantic_quality_review_gpt5.4mini.md"

    print(f"Suspect rooms: {[item['room_no'] for item in suspects]}")
    if args.dry_run:
        payload = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "dry_run": True,
            "suspects": suspects,
        }
        output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        output_md.write_text(build_markdown({"room_reviews": []}, suspects), encoding="utf-8")
        print("Dry run only. No API call was made.")
        print(f"Wrote: {output_json}")
        print(f"Wrote: {output_md}")
        return

    prompt = build_prompt(final_data, suspects)
    raw_response, usage = call_model(config, prompt)
    review = parse_json_response(raw_response)
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "suspects": suspects,
        "review": review,
        "usage": usage.model_dump() if hasattr(usage, "model_dump") else str(usage),
        "raw_response": raw_response,
    }
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(build_markdown(review, suspects), encoding="utf-8")
    print(f"Wrote: {output_json}")
    print(f"Wrote: {output_md}")
    if usage:
        print(f"Usage: {usage}")


if __name__ == "__main__":
    main()
