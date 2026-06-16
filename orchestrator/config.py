"""런타임 경로 + 상수. 모든 산출은 repo 루트의 var/ 아래(추적 안 함)에 격리해
frozen snapshots/ 영역을 오염시키지 않는다.
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

# 옵션 A: build_palace 가 잡별(콜드) 캐시를 그 도메인의 커밋된 캐시로 seed 한다.
# 쇼케이스 도메인이 레퍼런스 방(국사=골든)을 결정적으로 재현하게 함. False 면 seed
# 생략 = 전부 콜드(옵션 C, 매 잡 Stage A/B 를 real LLM 으로 재계산). A<->C 전환은
# 이 플래그 한 줄.
SEED_PALACE_CACHE = os.environ.get("ORCH_SEED_PALACE_CACHE", "1") != "0"

# SCAFFOLD: 다음 슬라이스에서 진짜 GraphRAG 인덱싱으로 교체.
# 알려진 showcase 입력(domain) -> 기존(reports 포함) 스냅샷 디렉터리(repo 상대) 매핑.
# index 스테이지가 새로 빌드하는 대신 이 dir로 snapshot_path를 가리켜, rag가 등록할
# "진짜 스냅샷"이 생긴다. 둘 다 community_reports 있음(global search 가능).
SHOWCASE_SNAPSHOTS: dict[str, str] = {
    "korean_history": "snapshots/repro_run3",
    "statistics": "snapshots/statistics",
}

# 도메인 -> palace 빌드 베이스 config (repo 상대). build_palace 가 이걸 베이스로
# per-job override 한다(snapshot/출력/캐시만 잡 경로로). index 가 라이브가 되어도
# 이 매핑은 그대로고 snapshot 만 잡 경로로 바뀐다(SHOWCASE_SNAPSHOTS 와 평행한 별도
# 레지스트리라 scaffold 가정이 build_palace 로 새지 않는다).
PALACE_CONFIGS: dict[str, str] = {
    "korean_history": "palace/configs/korean_history.json",
    "statistics": "palace/configs/statistics.json",
}


def load_env() -> None:
    """REPO/.env 의 키를 프로세스 환경으로 로드(이미 설정된 값은 보존). 라이브
    인덱싱은 GRAPHRAG_API_KEY/BASE 가 필요하고, in-process 감지 호출과 subprocess
    (env 상속) 양쪽이 이 값을 본다. palace/run.py 의 _load_dotenv 와 동형."""
    env_path = REPO / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def ensure_dirs() -> None:
    VAR_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
