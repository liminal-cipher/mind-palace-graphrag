from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from openai import AzureOpenAI
import pandas as pd


DEFAULT_CONFIG = Path(
    "output/그래프라그 방나누기/gpt4.1mini/NEW/settings_gpt5.4mini.yaml"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ask GPT-5.4 mini to judge GraphRAG merge/split/anomaly candidates."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
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


def load_config(config_path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return expand_env(raw)


def read_input(config: dict[str, Any]) -> str:
    md_path = Path(config["inputs"]["merge_analysis_markdown"])
    if not md_path.exists():
        raise FileNotFoundError(md_path)
    merge_analysis = md_path.read_text(encoding="utf-8")
    community_list = read_original_community_list(md_path.parent)
    prompt = config["prompt"]
    rules = "\n".join(f"- {rule}" for rule in config.get("rules", []))
    room_policy = config.get("task", {}).get("room_count_policy", {})
    if room_policy:
        room_policy_text = yaml.safe_dump(
            room_policy, allow_unicode=True, sort_keys=False
        ).strip()
    else:
        target_room_count = config.get("task", {}).get("target_room_count", "자동")
        room_policy_text = f"target_room_count: {target_room_count}"
    return f"""{prompt}

추가 규칙:
{rules}

방 개수 정책:
```yaml
{room_policy_text}
```

아래는 알고리즘이 생성한 병합/분할/이상 엔티티 후보 분석입니다.

## 원본 커뮤니티 전체 목록

```text
{community_list}
```

## 후처리 후보 분석

```markdown
{merge_analysis}
```
"""


def read_original_community_list(base: Path) -> str:
    reports_path = base / "community_reports.parquet"
    if not reports_path.exists():
        return "원본 커뮤니티 목록을 찾지 못했습니다."
    reports = pd.read_parquet(reports_path)
    lines = []
    for row in reports.sort_values("community").itertuples(index=False):
        lines.append(f"{int(row.community)}: {row.title} (entities={int(row.size)})")
    return "\n".join(lines)


def call_model(config: dict[str, Any], user_content: str) -> tuple[str, Any]:
    azure = config["azure_openai"]
    client = AzureOpenAI(
        azure_endpoint=azure["endpoint"],
        api_key=azure["api_key"],
        api_version=azure["api_version"],
    )
    deployment = azure["deployment_name"]
    temperature = float(azure.get("temperature", 0.0))

    messages = [
        {
            "role": "system",
            "content": (
                "You are a careful Korean history learning-structure reviewer. "
                "Use the supplied GraphRAG candidate analysis only as evidence, "
                "and make conservative merge/split decisions."
            ),
        },
        {"role": "user", "content": user_content},
    ]

    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=messages,
            temperature=temperature,
            max_completion_tokens=8000,
        )
    except TypeError:
        response = client.chat.completions.create(
            model=deployment,
            messages=messages,
            temperature=temperature,
            max_tokens=8000,
        )

    content = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    return content, usage


def write_outputs(config: dict[str, Any], judgement: str, usage: Any) -> None:
    md_path = Path(config["outputs"]["judgement_markdown"])
    json_path = Path(config["outputs"]["judgement_json"])
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    md_path.write_text(judgement, encoding="utf-8")
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model": config["azure_openai"]["model"],
        "deployment_name": config["azure_openai"]["deployment_name"],
        "input": config["inputs"],
        "output_markdown": str(md_path),
        "usage": usage.model_dump() if hasattr(usage, "model_dump") else str(usage),
        "judgement": judgement,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Wrote: {md_path}")
    print(f"Wrote: {json_path}")
    if usage:
        print(f"Usage: {usage}")


def main() -> None:
    args = parse_args()
    load_dotenv(Path(".env"))
    config = load_config(args.config)
    user_content = read_input(config)

    print(f"Config: {args.config}")
    print(f"Deployment: {config['azure_openai']['deployment_name']}")
    print(f"Input chars: {len(user_content):,}")

    if args.dry_run:
        print("Dry run only. No API call was made.")
        return

    judgement, usage = call_model(config, user_content)
    write_outputs(config, judgement, usage)


if __name__ == "__main__":
    main()
