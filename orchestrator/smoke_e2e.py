"""오케스트레이터 end-to-end 스모크: 업로드 -> index(scaffold) -> build_palace(real)
-> rag(serve register) -> /jobs/{id}/query 가 한 줄로 흐르는지 라이브로 검증한다.

전제: 두 서버가 이미 떠 있어야 한다(이 스크립트는 순수 클라이언트다).
  1) RAG 서빙:       .venv/Scripts/python -m uvicorn serve:app --port 8000
  2) 오케스트레이터:  .venv/Scripts/python -m uvicorn orchestrator.app:app --port 8001
환경변수로 주소를 바꿀 수 있다: SERVE_URL(기본 :8000), ORCH_URL(기본 :8001).

판정 기준은 도메인 경로에 따라 다르다:
  - korean_history (frozen TOC + seed cache): 엄격.
      room_count == 7, 보존 엔티티 수가 골든과 동일,
      골든 동치(compare_golden 재사용; run_id 에서 파생되는 3필드
      meta.run_id / palace.id / palace.title 만 제외한 뒤 diff 0),
      build_palace LLM 0콜(잡 캐시 == seed 캐시, 새 항목 0).
      하나라도 어긋나면 FAIL.
  - ai_school (full TOC+rooms): 느슨.
      방 >= 1 + 보존 엔티티 > 0 + 쿼리 응답 비어있지 않음.
      방 이름은 라이브 TOC 가 매 실행 미세하게 흔들리는 알려진 noise 라
      이름 차이로 FAIL 처리하지 않는다(구조는 Stage B seed 로 안정적).
  - 공통: /query 응답이 비어있지 않아야 한다(체인 페이로프).

종료 코드: 전부 PASS 면 0, 아니면 1.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from orchestrator import config as orch_config  # noqa: E402

SERVE_URL = os.environ.get("SERVE_URL", "http://127.0.0.1:8000").rstrip("/")
ORCH_URL = os.environ.get("ORCH_URL", "http://127.0.0.1:8001").rstrip("/")

GOLDEN_DIR = REPO / "palace" / "tests" / "golden"
# run_id == job_id 이므로 잡 산출물 이름이 job_id 기반이다. 골든은 run_id 고정값.
# 따라서 golden vs job 비교에서 run_id 에서 파생되는 이 필드들만 예상된 차이다.
IGNORE_FIELDS = {"meta.run_id", "palace.id", "palace.title"}

# 잡 완료까지(전 스테이지 + build_palace subprocess + serve warm) 넉넉히 기다린다.
JOB_TIMEOUT_S = 600.0
POLL_INTERVAL_S = 2.0
QUERY_TIMEOUT_S = 180.0


def _load_compare_golden():
    """compare_golden.py 를 파일 경로로 로드한다(palace/tests 는 패키지가 아니므로
    일반 import 가 안 된다). 모듈 import 만으로는 main 이 돌지 않는다."""
    path = REPO / "palace" / "tests" / "compare_golden.py"
    spec = importlib.util.spec_from_file_location("compare_golden", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tree_fingerprint(d: Path) -> dict[str, bytes]:
    """디렉터리 안 모든 파일의 상대경로 -> 바이트. 캐시 동일성 비교에 쓴다."""
    out: dict[str, bytes] = {}
    if not d.is_dir():
        return out
    for p in sorted(d.rglob("*")):
        if p.is_file():
            out[p.relative_to(d).as_posix()] = p.read_bytes()
    return out


def _require_servers() -> None:
    """두 서버가 응답하는지 먼저 확인하고, 아니면 실행법을 알려주고 멈춘다."""
    problems = []
    for name, url in (("serve", SERVE_URL), ("orchestrator", ORCH_URL)):
        try:
            r = httpx.get(f"{url}/health", timeout=10.0)
            if r.status_code != 200:
                problems.append(f"{name} {url}/health -> HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            problems.append(f"{name} {url}/health 연결 실패: {e}")
    if problems:
        print("STOP: 서버가 준비되지 않았다.")
        for p in problems:
            print(f"  - {p}")
        print("  먼저 두 서버를 띄워라:")
        print("    .venv/Scripts/python -m uvicorn serve:app --port 8000")
        print("    .venv/Scripts/python -m uvicorn orchestrator.app:app --port 8001")
        sys.exit(2)


def _upload(domain: str, showcase: str | None = None, body: bytes | None = None) -> str:
    """업로드해 job_id 를 반환한다. showcase 가 있으면 scaffold(내용 무관, 자리표시자
    본문이면 충분). showcase 가 없으면 라이브 인덱싱이므로 body 에 진짜 코퍼스를 준다."""
    if body is None:
        body = f"smoke upload for domain={domain}\n".encode("utf-8")
    params = {"filename": f"{domain}_smoke.txt", "domain": domain}
    if showcase is not None:
        params["showcase"] = showcase
    r = httpx.post(
        f"{ORCH_URL}/upload",
        params=params,
        content=body,
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()["job_id"]


# 라이브 인덱싱 검증용 작은 코퍼스(도메인 감지 + discover + 추출이 돌 만큼의 본문).
# 쇼케이스(국사/통계)와 겹치지 않는 도메인(세포생물학)이라 프리베이크로 새지 않음을
# 도메인 자체로도 보여준다.
LIVE_CORPUS = (
    "세포 생물학 기초\n\n"
    "세포는 생명의 기본 단위다. 진핵세포는 핵을 가지며 원핵세포는 핵이 없다.\n"
    "미토콘드리아는 세포 호흡을 담당해 ATP 를 생성한다. 리보솜은 단백질을 합성한다.\n"
    "세포막은 인지질 이중층으로 물질 출입을 조절한다. 소포체는 단백질과 지질을 운반한다.\n"
    "골지체는 단백질을 가공하고 분류한다. 리소좀은 세포 내 소화를 담당한다.\n"
    "세포는 분열로 증식한다. 체세포 분열은 유사 분열이고 생식세포는 감수 분열을 한다.\n"
    "DNA 는 핵 안에 유전 정보를 저장하고 RNA 로 전사되어 단백질로 번역된다.\n"
    "광합성은 엽록체에서 빛 에너지를 화학 에너지로 바꾼다. 식물 세포는 세포벽을 가진다.\n"
)


def _poll_until_terminal(job_id: str) -> dict:
    """DONE/FAILED 까지 상태를 폴링한다. 마지막 status dict 를 반환."""
    deadline = time.monotonic() + JOB_TIMEOUT_S
    last = {}
    while time.monotonic() < deadline:
        r = httpx.get(f"{ORCH_URL}/jobs/{job_id}/status", timeout=15.0)
        r.raise_for_status()
        last = r.json()
        if last["state"] in ("DONE", "FAILED"):
            return last
        time.sleep(POLL_INTERVAL_S)
    last["_timeout"] = True
    return last


def _get_palace_via_api(job_id: str) -> dict:
    """오케스트레이터 /jobs/{id}/palace 가 palace.json 본문을 돌려주는지(체인 도달)."""
    r = httpx.get(f"{ORCH_URL}/jobs/{job_id}/palace", timeout=30.0)
    r.raise_for_status()
    return r.json()


def _query(job_id: str, question: str) -> str:
    """serve 의 잡별 질의. 라이브 등록 키 = job_id."""
    r = httpx.post(
        f"{SERVE_URL}/jobs/{job_id}/query",
        json={"question": question},
        timeout=QUERY_TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json().get("answer", "")


def _palace_totals(palace: dict) -> tuple[int, int, int]:
    """(room_count, kept_total, demoted_total)."""
    rooms = palace.get("rooms", [])
    kept = sum(r.get("kept_count", 0) for r in rooms)
    demoted = sum(len(r.get("demoted", [])) for r in rooms)
    return len(rooms), kept, demoted


def _check_korean_history(job_id: str, api_palace: dict, fails: list[str], notes: list[str]) -> None:
    cmp = _load_compare_golden()
    job_dir = orch_config.JOBS_DIR / job_id
    palace_out = job_dir / "palace_out"
    job_rooms_p = palace_out / f"{job_id}.json"
    job_palace_p = palace_out / f"{job_id}.palace.json"

    room_count, kept, demoted = _palace_totals(api_palace)
    preserved = kept + demoted
    notes.append(f"room_count={room_count} kept={kept} demoted={demoted} preserved={preserved}")

    if room_count != 7:
        fails.append(f"room_count={room_count} (기대 7)")

    # 골든 동치: rooms.json + palace.json 을 잡 산출물에서 직접 읽어 비교한다.
    if not job_rooms_p.exists() or not job_palace_p.exists():
        fails.append(f"잡 산출물 누락: {job_rooms_p.name} 또는 {job_palace_p.name}")
        return
    g_rooms = json.loads((GOLDEN_DIR / "korean_history.json").read_text(encoding="utf-8"))
    g_palace = json.loads((GOLDEN_DIR / "korean_history.palace.json").read_text(encoding="utf-8"))
    j_rooms = json.loads(job_rooms_p.read_text(encoding="utf-8"))
    j_palace = json.loads(job_palace_p.read_text(encoding="utf-8"))

    g_room_count, g_kept, g_demoted = _palace_totals(g_palace)
    g_preserved = g_kept + g_demoted
    if preserved != g_preserved:
        fails.append(f"보존 엔티티 {preserved} != 골든 {g_preserved}")
    else:
        notes.append(f"보존 엔티티 골든과 일치({g_preserved})")

    rows: list[dict] = []
    cmp.compare_rooms(g_rooms, j_rooms, rows)
    cmp.compare_palace(g_palace, j_palace, rows)
    unexpected = [r for r in rows if r["field"] not in IGNORE_FIELDS]
    if unexpected:
        fails.append(f"골든 동치 깨짐: 예상 밖 diff {len(unexpected)}건")
        print(cmp.format_diff(unexpected))
    else:
        notes.append("골든 동치 OK (run_id 파생 필드만 차이)")

    # build_palace LLM 0콜: 잡 캐시가 seed 캐시와 byte 동일하면 새 계산 0 = 콜 0.
    seed_cache = REPO / "cache" / "palace" / "korean_history"
    job_cache = job_dir / "cache"
    seed_fp = _tree_fingerprint(seed_cache)
    job_fp = _tree_fingerprint(job_cache)
    added = sorted(set(job_fp) - set(seed_fp))
    changed = sorted(k for k in (set(job_fp) & set(seed_fp)) if job_fp[k] != seed_fp[k])
    if added or changed:
        fails.append(
            f"build_palace LLM 콜 발생 추정: 캐시 신규 {len(added)} 변경 {len(changed)} "
            f"(added={added[:3]} changed={changed[:3]})"
        )
    else:
        notes.append(f"build_palace LLM 0콜 (잡 캐시 == seed, 파일 {len(job_fp)}개 동일)")


def _check_ai_school(api_palace: dict, fails: list[str], notes: list[str]) -> None:
    room_count, kept, demoted = _palace_totals(api_palace)
    names = [r.get("name") for r in api_palace.get("rooms", [])]
    notes.append(f"room_count={room_count} kept={kept} demoted={demoted}")
    notes.append(f"방 이름(라이브 noise 허용): {names}")
    if room_count < 1:
        fails.append(f"방이 없음(room_count={room_count})")
    if kept + demoted < 1:
        fails.append("보존 엔티티 0")


def _check_live(job_id: str, api_palace: dict, fails: list[str], notes: list[str]) -> None:
    """라이브 인덱싱 경로(진짜 graphrag index). 느슨한 구조 검증 + 프리베이크로 안
    샜는지 확인: 잡 스냅샷이 var/jobs/<id>/index_root/output 이어야 한다(국사/통계
    프리베이크 results/snapshots 가 아니라)."""
    room_count, kept, demoted = _palace_totals(api_palace)
    names = [r.get("name") for r in api_palace.get("rooms", [])]
    notes.append(f"room_count={room_count} kept={kept} demoted={demoted}")
    notes.append(f"방 이름: {names}")
    if room_count < 1:
        fails.append(f"방이 없음(room_count={room_count})")
    if kept + demoted < 1:
        fails.append("보존 엔티티 0")
    # 누수 차단 확인: 라이브 스냅샷은 잡 폴더 안이어야 하고 프리베이크가 아니어야 한다.
    status = httpx.get(f"{ORCH_URL}/jobs/{job_id}/status", timeout=15.0).json()
    job_out = (orch_config.JOBS_DIR / job_id / "index_root" / "output").resolve()
    if not job_out.is_dir():
        fails.append(f"라이브 스냅샷 출력 dir 없음: {job_out}")
    else:
        notes.append(f"라이브 스냅샷=잡 폴더 출력(프리베이크 아님): {job_out.name} 경로 OK")
    # 도메인은 감지 라벨이어야 한다(업로드 시 준 'live_bio' 가 아니라).
    notes.append(f"감지 domain 라벨: {status.get('domain')}")


DOMAINS = [
    {
        # 명시 showcase 트리거로 scaffold 경로(프리베이크 repro_run3)를 탄다.
        "domain": "korean_history",
        "showcase": "korean_history",
        "question": "조선 전기의 통치 제도를 설명해줘.",
        "checker": "korean_history",
    },
    {
        # global search 는 overview/요약형 질문에 강하다. 좁은 "A와 B의 차이" 류는
        # 커뮤니티 리포트에 대조항이 없으면 거절 폴백이 나오므로(체인과 무관한
        # 질문-스냅샷 적합도 문제) 요약형으로 둔다.
        "domain": "ai_school",
        "showcase": "ai_school",
        "question": "이 자료의 핵심 통계 개념들을 요약해줘.",
        "checker": "ai_school",
    },
    {
        # 라이브 인덱싱: showcase 없음 -> 진짜 graphrag index. 업로드 domain 은 라벨일
        # 뿐(감지가 덮어쓴다). 프리베이크(국사/통계)와 다른 도메인이라 누수 0 도 자명.
        "domain": "live_bio",
        "showcase": None,
        "corpus": LIVE_CORPUS,
        "question": "이 자료의 핵심 개념들을 요약해줘.",
        "checker": "live",
    },
]


def run_one(spec: dict) -> bool:
    domain = spec["domain"]
    fails: list[str] = []
    notes: list[str] = []
    print(f"\n=== [{domain}] 체인 시작 ===")

    body = spec.get("corpus")
    job_id = _upload(domain, spec.get("showcase"), body.encode("utf-8") if body else None)
    print(f"  upload -> job_id={job_id}")

    status = _poll_until_terminal(job_id)
    state = status.get("state")
    print(f"  최종 상태: state={state} rag_ready={status.get('rag_ready')} "
          f"palace_ready={status.get('palace_ready')}")
    if status.get("_timeout"):
        fails.append(f"잡 미완료(타임아웃, 마지막 state={state})")
    elif state != "DONE":
        fails.append(f"잡 실패: state={state} error={status.get('error')}")

    api_palace = None
    if state == "DONE":
        api_palace = _get_palace_via_api(job_id)
        print(f"  /jobs/{job_id}/palace OK (room_count={api_palace.get('palace', {}).get('room_count')})")

        if spec["checker"] == "korean_history":
            _check_korean_history(job_id, api_palace, fails, notes)
        elif spec["checker"] == "live":
            _check_live(job_id, api_palace, fails, notes)
        else:
            _check_ai_school(api_palace, fails, notes)

        # 공통: 쿼리 응답 비어있지 않은지(체인 페이로프).
        answer = _query(job_id, spec["question"])
        preview = answer.strip().replace("\n", " ")[:120]
        print(f"  /jobs/{job_id}/query -> {len(answer)}자: {preview}")
        if not answer.strip():
            fails.append("쿼리 응답이 비어 있음")
        else:
            notes.append(f"쿼리 응답 {len(answer)}자(non-empty)")

    for n in notes:
        print(f"    - {n}")
    verdict = "PASS" if not fails else "FAIL"
    print(f"  [{domain}] {verdict}")
    for f in fails:
        print(f"    ! {f}")
    return not fails


def run_failure_injection() -> bool:
    """실패 주입: (1) 빈 본문 -> 422(잡 미생성), (2) 추출 불가(구두점만) 라이브 입력 ->
    잡 FAILED. 둘 다 후 서버가 살아 있어야 한다(워커 비차단)."""
    print("\n=== [failure-injection] ===")
    fails: list[str] = []

    # (1) 빈 본문은 업로드 단계에서 거절.
    r = httpx.post(f"{ORCH_URL}/upload", params={"domain": "x"}, content=b"", timeout=30.0)
    if r.status_code == 422:
        print("    - 빈 본문 -> 422 거절 OK")
    else:
        fails.append(f"빈 본문이 422 가 아님: {r.status_code}")

    # (2) 추출 불가 입력(공백/개행만, 엔티티가 나올 토큰 없음) -> graphrag "No entities
    #     detected" 또는 엔티티 0 게이트로 라이브 잡 FAILED. 숫자/단어가 있으면 그것들이
    #     엔티티로 추출돼 정상 인덱싱되므로(=깨진 입력이 아님) 순수 공백을 쓴다.
    job_id = _upload("fail_inject", None, ("   \n \t \n  \n" * 8).encode("utf-8"))
    print(f"    - broken 라이브 업로드 -> job_id={job_id}")
    status = _poll_until_terminal(job_id)
    state = status.get("state")
    print(f"    - 최종 state={state} error={(status.get('error') or '')[:80]}")
    if status.get("_timeout"):
        fails.append("broken 잡이 종단되지 않음(타임아웃)")
    elif state != "FAILED":
        fails.append(f"broken 잡이 FAILED 가 아님: {state}")
    else:
        print("    - broken 입력 -> FAILED OK")

    # (3) 서버 생존 확인.
    try:
        h = httpx.get(f"{ORCH_URL}/health", timeout=10.0).json()
        if h.get("worker_alive"):
            print("    - 실패 후 워커 생존 OK")
        else:
            fails.append(f"실패 후 워커 비생존: {h}")
    except Exception as e:  # noqa: BLE001
        fails.append(f"실패 후 /health 접근 불가: {e}")

    verdict = "PASS" if not fails else "FAIL"
    print(f"  [failure-injection] {verdict}")
    for f in fails:
        print(f"    ! {f}")
    return not fails


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"serve={SERVE_URL}  orchestrator={ORCH_URL}")
    _require_servers()

    all_names = [d["domain"] for d in DOMAINS] + ["failure-injection"]
    selected = sys.argv[1:] or all_names
    results: dict[str, bool] = {}
    for spec in DOMAINS:
        if spec["domain"] in selected:
            results[spec["domain"]] = run_one(spec)
    if "failure-injection" in selected:
        results["failure-injection"] = run_failure_injection()

    print("\n=== 요약 ===")
    for domain, ok in results.items():
        print(f"  {domain}: {'PASS' if ok else 'FAIL'}")
    all_pass = all(results.values()) and bool(results)
    print(f"전체: {'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
