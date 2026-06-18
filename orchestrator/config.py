"""런타임 경로 + 상수. 모든 산출은 repo 루트의 var/ 아래(추적 안 함)에 격리해
frozen snapshots/ 영역을 오염시키지 않는다.
"""
from __future__ import annotations

import os
from pathlib import Path

# orchestrator/ 는 repo 루트 바로 아래 -> 부모의 부모가 루트.
REPO = Path(__file__).resolve().parent.parent

# 런타임 산출(잡 DB + 잡 폴더) 위치. App Service 는 코드가 휘발성 /tmp/<hash> 에서 돌아
# 기본 REPO/var 는 재시작/재배포 시 날아간다(진행·완료 잡 유실 -> 404). 배포에선
# ORCH_VAR_DIR=/home/var 로 영구 스토리지를 가리켜 잡이 보존되게 한다(로컬은 미설정 ->
# REPO/var 그대로). serve 의 등록-허용 루트도 이 JOBS_DIR 을 참조한다(단일 소스).
VAR_DIR = Path(os.environ.get("ORCH_VAR_DIR") or (REPO / "var"))
DB_PATH = VAR_DIR / "orchestrator.db"
JOBS_DIR = VAR_DIR / "jobs"

# STUB 스테이지 1개당 sleep(초). 데모/복구 시연용으로 env로 늘릴 수 있게 둔다.
STUB_STAGE_SECONDS = float(os.environ.get("ORCH_STUB_SECONDS", "2.0"))

# prompt-tune discover subprocess 상한(초). 행걸림 시 워커가 무한 대기하지 않고
# generic 폴백으로 떨어지게 한다. env로 조정 가능, 잠정 기본 600초.
PROMPT_TUNE_TIMEOUT_S = float(os.environ.get("ORCH_PROMPT_TUNE_TIMEOUT", "600"))

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
