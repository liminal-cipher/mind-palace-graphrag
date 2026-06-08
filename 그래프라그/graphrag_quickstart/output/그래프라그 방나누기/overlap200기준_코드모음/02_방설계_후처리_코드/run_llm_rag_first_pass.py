from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml


BASE_DIR = Path("output/그래프라그 방나누기/LLM+라그")
SOURCE_TEXT = BASE_DIR / "content.txt"
PASS_DIR = BASE_DIR / "1차"
ROOT_DIR = PASS_DIR / "graphrag_root"
INPUT_DIR = ROOT_DIR / "input"
OUTPUT_DIR = ROOT_DIR / "output"
LOG_DIR = ROOT_DIR / "logs"
CACHE_DIR = ROOT_DIR / "cache"
PROMPTS_DIR = ROOT_DIR / "prompts"


def load_dotenv(path: Path) -> dict[str, str]:
    env = os.environ.copy()
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def read_settings_template(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text)


def write_settings(settings: dict, path: Path) -> None:
    settings = json.loads(json.dumps(settings, ensure_ascii=False))
    settings["input_storage"]["base_dir"] = "input"
    settings["output_storage"]["base_dir"] = "output"
    settings["reporting"]["base_dir"] = "logs"
    settings["cache"]["storage"]["base_dir"] = "cache"
    settings["vector_store"]["db_uri"] = "output/lancedb"
    # Keep the current tuned settings, but make the copied root self-contained.
    path.write_text(
        yaml.safe_dump(settings, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def prepare_root(force: bool = False) -> None:
    if not SOURCE_TEXT.exists():
        raise FileNotFoundError(SOURCE_TEXT)
    if ROOT_DIR.exists() and force:
        shutil.rmtree(ROOT_DIR)
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if PROMPTS_DIR.exists():
        shutil.rmtree(PROMPTS_DIR)
    shutil.copytree(Path("prompts"), PROMPTS_DIR)
    shutil.copy2(SOURCE_TEXT, INPUT_DIR / "content.txt")
    settings = read_settings_template(Path("settings.yaml"))
    write_settings(settings, ROOT_DIR / "settings.yaml")


def run_graphrag() -> None:
    env = load_dotenv(Path(".env"))
    cmd = [str(Path(".venv/Scripts/graphrag.exe")), "index", "--root", str(ROOT_DIR)]
    subprocess.run(cmd, check=True, env=env)


def find_parquet_dir() -> Path:
    candidates = sorted(OUTPUT_DIR.rglob("community_reports.parquet"))
    if not candidates:
        raise FileNotFoundError("community_reports.parquet not found under " + str(OUTPUT_DIR))
    return candidates[-1].parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Run isolated GraphRAG pass for LLM+RAG content.txt.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-index", action="store_true")
    args = parser.parse_args()

    prepare_root(force=args.force)
    if not args.skip_index:
        run_graphrag()
    parquet_dir = find_parquet_dir()
    (PASS_DIR / "graphrag_output_path.txt").write_text(str(parquet_dir), encoding="utf-8")
    print(f"GraphRAG output: {parquet_dir}")


if __name__ == "__main__":
    main()
