"""
CU 분석기 관리 — 목록 조회 / 삭제

분석기 config(enableFormula 등)를 바꾼 뒤, 같은 ID로 재생성하려면
기존 분석기를 먼저 삭제해야 한다 (같은 ID PUT은 409로 무시되기 때문).

사용:
    python manage_analyzer.py --list
    python manage_analyzer.py --delete pdf_content_extractor

환경변수 (.env):
    CONTENT_UNDERSTANDING_ENDPOINT
    CONTENT_UNDERSTANDING_KEY
    CONTENT_UNDERSTANDING_API_VER (기본 2024-12-01-preview)
"""

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

ENDPOINT = os.environ.get("CONTENT_UNDERSTANDING_ENDPOINT", "").rstrip("/")
KEY      = os.environ.get("CONTENT_UNDERSTANDING_KEY", "")
API_VER  = os.environ.get("CONTENT_UNDERSTANDING_API_VER", "2024-12-01-preview")
HDR      = {"Ocp-Apim-Subscription-Key": KEY}


def list_analyzers() -> None:
    url  = f"{ENDPOINT}/contentunderstanding/analyzers?api-version={API_VER}"
    resp = requests.get(url, headers=HDR, timeout=30)
    resp.raise_for_status()
    items = resp.json().get("value", [])
    if not items:
        print("(등록된 분석기 없음)")
        return
    for a in items:
        aid = a.get("analyzerId", "?")
        cfg = a.get("config", {})
        print(f"- {aid}  (enableFormula={cfg.get('enableFormula')})")


def delete_analyzer(analyzer_id: str) -> None:
    url  = f"{ENDPOINT}/contentunderstanding/analyzers/{analyzer_id}?api-version={API_VER}"
    resp = requests.delete(url, headers=HDR, timeout=30)
    if resp.status_code in (200, 204):
        print(f"삭제 완료: {analyzer_id}")
    elif resp.status_code == 404:
        print(f"이미 없음(404): {analyzer_id}")
    else:
        print(f"[ERROR] {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()


def main():
    p = argparse.ArgumentParser(description="CU 분석기 관리")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="분석기 목록 조회")
    g.add_argument("--delete", metavar="ANALYZER_ID", help="분석기 삭제")
    args = p.parse_args()

    if not ENDPOINT or not KEY:
        raise RuntimeError("CONTENT_UNDERSTANDING_ENDPOINT / KEY 미설정")

    if args.list:
        list_analyzers()
    else:
        delete_analyzer(args.delete)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
