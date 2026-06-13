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


def job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def ensure_dirs() -> None:
    VAR_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
