#!/usr/bin/env python3
"""배포 후 warm + 준비 폴 스크립트 (의존성 0, stdlib만).

heavy backend(serve)는 startup에서 스냅샷을 백그라운드로 warm load한다. 이 스크립트는
배포 직후 또는 데모 직전에:
  1. /ready 가 200(준비됨)이 될 때까지 폴링하고,
  2. 준비되면 trivial 질문으로 /query 를 한 번 쳐서 검색 경로(LLM 연결 포함)를 데운다.

--keep-warm 을 주면 데모 전까지 interval 마다 trivial 질문을 반복해 콜드아웃을 막는다
(Always On 과 별개로, 검색 경로/LLM 연결을 따뜻하게 유지).

기본 대상은 korean_history(canonical 데모 스냅샷). ai_school 은 gitignore 라 Azure
배포 패키지에 없을 수 있어(런북 참조) error 로 뜬다. 그건 키별로 격리되며, 이 스크립트가
korean_history 만 게이팅하므로 영향 없다.

예:
  # 로컬
  python ops/warmup_poll.py --base-url http://127.0.0.1:8000
  # Azure (combined backend: serve 는 루트에 마운트되어 경로 동일)
  python ops/warmup_poll.py --base-url https://<app>.azurewebsites.net
  # 데모 전 keep-warm (4분마다)
  python ops/warmup_poll.py --base-url https://<app>.azurewebsites.net --keep-warm --interval 240
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def _get(url: str, timeout: float) -> tuple[int, dict]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, _json(r.read())
    except urllib.error.HTTPError as e:  # 503/404 등도 본문째 받는다.
        return e.code, _json(e.read())


def _post(url: str, payload: dict, timeout: float) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, _json(r.read())
    except urllib.error.HTTPError as e:
        return e.code, _json(e.read())


def _json(raw: bytes) -> dict:
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {"_raw": raw.decode("utf-8", "replace")[:500]}


def poll_ready(base: str, snapshot: str, timeout_s: float, interval_s: float) -> bool:
    """/ready?snapshot=<key> 가 200 이 될 때까지 폴링. True=준비됨, False=타임아웃."""
    url = f"{base}/ready?snapshot={snapshot}"
    deadline = time.monotonic() + timeout_s
    t0 = time.monotonic()
    while True:
        try:
            code, body = _get(url, timeout=15.0)
        except Exception as e:  # noqa: BLE001  서버가 아직 안 떴을 수 있다.
            code, body = 0, {"error": str(e)}
        elapsed = time.monotonic() - t0
        if code == 200:
            print(f"[ready] {snapshot} 준비됨 ({elapsed:.0f}s)")
            return True
        if code == 404:
            print(f"[stop] {snapshot} 미등록(404). 등록 키 확인 필요: {body}")
            return False
        detail = body.get("detail") or body
        print(f"[wait] {snapshot} 아직 (HTTP {code}, {elapsed:.0f}s): {detail}")
        if time.monotonic() >= deadline:
            print(f"[timeout] {snapshot} 가 {timeout_s:.0f}s 안에 준비되지 않았다.")
            return False
        time.sleep(interval_s)


def warm_query(base: str, snapshot: str, question: str, timeout_s: float) -> bool:
    """trivial 질문 1회로 검색 경로를 데운다. True=200."""
    url = f"{base}/query"
    t0 = time.monotonic()
    code, body = _post(url, {"question": question, "snapshot": snapshot}, timeout=timeout_s)
    dt = time.monotonic() - t0
    if code == 200:
        ans = (body.get("answer") or "")[:120].replace("\n", " ")
        print(f"[warm] /query 200 ({dt:.0f}s): {ans}...")
        return True
    print(f"[warm] /query HTTP {code} ({dt:.0f}s): {body}")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="heavy backend warm + readiness poll")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000",
                    help="serve 베이스 URL (combined backend 도 serve 는 루트 마운트라 동일)")
    ap.add_argument("--snapshot", default="korean_history",
                    help="게이팅/warm 대상 스냅샷 키 (기본 canonical 데모)")
    ap.add_argument("--question", default="이 자료는 무엇에 대한 것인가?",
                    help="warm 용 trivial 질문")
    ap.add_argument("--ready-timeout", type=float, default=600.0,
                    help="준비 대기 최대 초")
    ap.add_argument("--interval", type=float, default=5.0,
                    help="폴 간격(초); keep-warm 에선 warm 질문 간격")
    ap.add_argument("--query-timeout", type=float, default=180.0,
                    help="warm /query 타임아웃(초)")
    ap.add_argument("--keep-warm", action="store_true",
                    help="준비 후 interval 마다 trivial 질문을 반복(데모 전 콜드아웃 방지)")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    print(f"target: {base}  snapshot: {args.snapshot}")

    if not poll_ready(base, args.snapshot, args.ready_timeout, args.interval):
        return 1
    if not warm_query(base, args.snapshot, args.question, args.query_timeout):
        return 1

    if args.keep_warm:
        print(f"[keep-warm] {args.interval:.0f}s 마다 warm. 중지: Ctrl-C")
        try:
            while True:
                time.sleep(args.interval)
                warm_query(base, args.snapshot, args.question, args.query_timeout)
        except KeyboardInterrupt:
            print("\n[keep-warm] 중지됨")
    return 0


if __name__ == "__main__":
    sys.exit(main())
