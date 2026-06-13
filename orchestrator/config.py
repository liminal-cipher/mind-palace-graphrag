"""런타임 경로 + 상수. 모든 산출은 repo 루트의 var/ 아래(추적 안 함)에 격리해
frozen results/snapshots/ 영역을 오염시키지 않는다.
"""
from __future__ import annotations

import os
from pathlib import Path

# orchestrator/ 는 repo 루트 바로 아래 -> 부모의 부모가 루트.
REPO = Path(__file__).resolve().parent.parent

VAR_DIR = REPO / "var"
DB_PATH = VAR_DIR / "orchestrator.db"
JOBS_DIR = VAR_DIR / "jobs"

# STUB 스테이지 1개당 sleep(초). 데모/복구 시연용으로 env로 늘릴 수 있게 둔다.
STUB_STAGE_SECONDS = float(os.environ.get("ORCH_STUB_SECONDS", "2.0"))

# rag 스테이지가 빌드된 스냅샷을 등록할 serve 인스턴스. 내부 전용 register라 기본은
# 로컬. env로 바꿀 수 있게 둔다.
SERVE_URL = os.environ.get("SERVE_URL", "http://127.0.0.1:8000")

# SCAFFOLD: 다음 슬라이스에서 진짜 GraphRAG 인덱싱으로 교체.
# 알려진 showcase 입력(domain) -> 기존(reports 포함) 스냅샷 디렉터리(repo 상대) 매핑.
# index 스테이지가 새로 빌드하는 대신 이 dir로 snapshot_path를 가리켜, rag가 등록할
# "진짜 스냅샷"이 생긴다. 둘 다 community_reports 있음(global search 가능).
SHOWCASE_SNAPSHOTS: dict[str, str] = {
    "korean_history": "results/snapshots/repro_run3",
    "ai_school": "results/snapshots/ai_school",
}


def job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def ensure_dirs() -> None:
    VAR_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
