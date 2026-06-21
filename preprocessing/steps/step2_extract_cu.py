"""
STEP 2-CU — Content Understanding API 추출 (스캔 PDF)

실행:
    python step2_extract_cu.py --pdf "../../data/raw/국사교과서.pdf" --out "../result/test_cu_v1"

캐시 전략:
    out_dir 또는 동일 PDF의 이전 버전 폴더에 raw_response.json이 있으면 API 재호출 없이 재사용.

환경변수 (.env):
    CONTENT_UNDERSTANDING_ENDPOINT
    CONTENT_UNDERSTANDING_KEY
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# .env 로드 (pipeline_v2/steps/ → preprocess/.env)
load_dotenv(Path(__file__).parent.parent.parent / ".env")

ENDPOINT    = os.environ.get("CONTENT_UNDERSTANDING_ENDPOINT", "").rstrip("/")
KEY         = os.environ.get("CONTENT_UNDERSTANDING_KEY", "")
API_VER     = os.environ.get("CONTENT_UNDERSTANDING_API_VER", "2025-11-01")  # GA. preview(2024-12-01)는 이 리소스에서 410 Gone
ANALYZER_ID = "pdf_content_extractor_noform"  # GA(2025-11-01): analyzerId 하이픈 불가

_BASE_HDR = {"Ocp-Apim-Subscription-Key": KEY}
_JSON_HDR = {**_BASE_HDR, "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# 캐시 탐색
# ---------------------------------------------------------------------------

def _find_cached_raw(pdf_path: str, out_dir: Path) -> Path | None:
    """
    동일 PDF의 result/ 하위 버전 폴더에서 raw_response.json을 탐색.
    가장 최신 버전 우선. out_dir 자신도 포함.

    단, 캐시 응답의 apiVersion이 현재 설정된 API_VER과 다르면 재사용하지 않는다.
    (스키마가 달라 figure bbox가 없는 옛 응답을 그대로 쓰는 것을 방지)
    """
    pdf_stem = Path(pdf_path).stem
    result_dir = out_dir.parent  # result/

    found = None
    v = 1
    while True:
        folder = result_dir / f"{pdf_stem}_v{v}"
        if not folder.exists():
            break
        raw = folder / "raw_response.json"
        if raw.exists():
            try:
                data = json.loads(raw.read_text(encoding="utf-8"))
                cached_ver = data.get("result", {}).get("apiVersion", "")
            except Exception:
                cached_ver = ""
            if cached_ver == API_VER:
                found = raw  # 마지막으로 발견된 것 = 최신 버전
            else:
                print(f"  캐시 무시: {raw}  (apiVersion={cached_ver!r} ≠ {API_VER!r})")
        v += 1
    return found


# ---------------------------------------------------------------------------
# API 헬퍼
# ---------------------------------------------------------------------------

def _ensure_analyzer() -> None:
    """분석기 생성. 409(이미 존재)는 정상 처리. 410(삭제됨)은 DELETE 후 재생성."""
    url = f"{ENDPOINT}/contentunderstanding/analyzers/{ANALYZER_ID}?api-version={API_VER}"
    body = {
        "description": "PDF 텍스트·이미지·표·다이어그램 추출기",
        "baseAnalyzerId": "prebuilt-document",  # GA: custom 분석기는 prebuilt base 필수(문서 base)
        "config": {
            "returnDetails": True,   # figure bbox(source) 반환에 필수
            "enableOcr": True,
            "enableLayout": True,
            "enableBarcode": False,
            "enableFormula": False,  # 한글이 LaTeX 수식($...$)으로 오인식되는 것 방지
        },
    }
    resp = requests.put(url, headers=_JSON_HDR, json=body, timeout=60)

    if resp.status_code in (200, 201):
        print("  분석기: 생성 완료")
        return
    if resp.status_code == 409:
        print("  분석기: 기존 재사용")
        return
    if resp.status_code == 410:
        print("  분석기: 410 Gone 감지 → 삭제 후 재생성 시도")
        requests.delete(url, headers=_BASE_HDR, timeout=30)
        resp2 = requests.put(url, headers=_JSON_HDR, json=body, timeout=60)
        if resp2.status_code in (200, 201, 409):
            print("  분석기: 재생성 완료")
            return
        print(f"  [ERROR] {resp2.status_code}: {resp2.text[:1000]}")
        resp2.raise_for_status()
    else:
        print(f"  [ERROR] {resp.status_code}: {resp.text[:1000]}")
        resp.raise_for_status()


def _submit_analyze(pdf_path: str) -> str:
    """PDF를 application/pdf 바이너리로 전송 → Operation-Location URL 반환."""
    # GA: 로컬 파일 직접 업로드는 :analyzeBinary (raw 바이너리). :analyze는 JSON {url} 전용.
    url  = f"{ENDPOINT}/contentunderstanding/analyzers/{ANALYZER_ID}:analyzeBinary?api-version={API_VER}"
    hdrs = {**_BASE_HDR, "Content-Type": "application/pdf"}
    resp = requests.post(url, headers=hdrs, data=Path(pdf_path).read_bytes(), timeout=120)
    if not resp.ok:
        print(f"  [ERROR] {resp.status_code}: {resp.text[:1000]}")
    resp.raise_for_status()
    result_url = resp.headers.get("Operation-Location")
    if not result_url:
        raise RuntimeError(f"Operation-Location 헤더 없음: {dict(resp.headers)}")
    return result_url


def _poll(result_url: str, timeout: int = 900) -> dict:
    """분석 완료까지 5초 간격 폴링."""
    start = time.time()
    while time.time() - start < timeout:
        resp    = requests.get(result_url, headers=_BASE_HDR, timeout=30)
        resp.raise_for_status()
        data    = resp.json()
        status  = data.get("status", "unknown")
        elapsed = int(time.time() - start)
        print(f"  상태: {status:12s}  ({elapsed}s 경과)", end="\r", flush=True)
        if status == "Succeeded":
            print()
            return data
        if status in ("Failed", "Canceled"):
            raise RuntimeError(f"분석 실패: {json.dumps(data, ensure_ascii=False)[:300]}")
        time.sleep(5)
    raise TimeoutError(f"{timeout}초 초과")


# ---------------------------------------------------------------------------
# STEP 2-CU 메인
# ---------------------------------------------------------------------------

def step2_extract_cu(
    pdf_path: str,
    out_dir: Path,
    debug: bool = False,
    send_pdf_path: Optional[str] = None,
) -> dict:
    """
    CU API로 PDF 분석. 캐시가 있으면 재사용.

    Args:
        pdf_path:      원본 PDF 경로. 캐시 키(버전 폴더 탐색)는 *이 이름* 기준이라,
                       마스킹 여부와 무관하게 같은 원본은 같은 캐시를 가리킨다.
        send_pdf_path: 실제로 CU 에 업로드할 PDF. None 이면 pdf_path 를 그대로 보낸다.
                       PII 마스킹을 켜면 여기에 masked.pdf 경로를 넘겨, 외부로는
                       가려진 이미지만 나가고 원본 PII 는 전송되지 않는다.

    Returns:
        raw_response dict (result.contents 포함 전체 응답)
    """
    if not ENDPOINT or not KEY:
        raise RuntimeError(
            "환경변수 CONTENT_UNDERSTANDING_ENDPOINT / CONTENT_UNDERSTANDING_KEY 미설정"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    upload_path = send_pdf_path or pdf_path  # 외부로 나가는 실제 파일

    # 캐시 확인(원본 pdf_path 기준 — 마스킹본/원본이 같은 캐시를 공유)
    cached = _find_cached_raw(pdf_path, out_dir)
    if cached:
        print(f"[STEP 2-CU] 캐시 재사용 → {cached}")
        data = json.loads(cached.read_text(encoding="utf-8"))
        # 현재 out_dir에도 복사
        dest = out_dir / "raw_response.json"
        if dest != cached:
            dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    # API 호출 — upload_path(마스킹본 우선)를 전송한다.
    print("[STEP 2-CU] Azure API 호출 중...")
    if upload_path != pdf_path:
        print(f"  업로드 대상: {Path(upload_path).name} (PII 마스킹본)")
    _ensure_analyzer()
    result_url = _submit_analyze(upload_path)
    print(f"  Operation-Location: {result_url}")
    data = _poll(result_url)

    raw_path = out_dir / "raw_response.json"
    raw_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[STEP 2-CU] raw_response.json 저장 완료")

    # figure / content 요약 출력
    contents = data.get("result", {}).get("contents", [])
    fig_count = sum(len(c.get("figures", [])) for c in contents)
    print(f"[STEP 2-CU] 콘텐츠 블록 {len(contents)}개, figure 감지 {fig_count}개")

    return data


def main():
    parser = argparse.ArgumentParser(description="STEP 2-CU — Content Understanding API 추출")
    parser.add_argument("--pdf", required=True, help="입력 PDF 경로")
    parser.add_argument("--out", required=True, help="출력 디렉토리 경로")
    parser.add_argument("--debug", action="store_true", help="(현재 미사용)")
    args = parser.parse_args()

    out_dir = Path(args.out)
    data = step2_extract_cu(args.pdf, out_dir, debug=args.debug)

    contents = data.get("result", {}).get("contents", [])
    print(f"\n--- 결과 요약 ---")
    print(f"콘텐츠 블록 : {len(contents)}개")
    print(f"출력 위치   : {out_dir / 'raw_response.json'}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
