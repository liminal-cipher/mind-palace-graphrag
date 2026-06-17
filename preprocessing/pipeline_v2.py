"""
전처리 파이프라인 v2 (오케스트레이터)

각 단계의 실제 로직은 steps/ 에 있고, 이 파일은 단계 배선·버전 폴더 생성·
실행 로그만 담당한다. (steps/ 가 단일 진실원본 — 여기서 복제하지 않는다.)

경로 분기:
    스캔 PDF   → STEP 2-CU → STEP 3-CU → STEP 4(이미지 후처리) → STEP 5
    디지털 PDF → STEP 2-MU → STEP 5

실행:
    python pipeline_v2.py --pdf "../data/raw/통계기초.pdf"
    python pipeline_v2.py --pdf "../data/raw/국사교과서.pdf"
    python pipeline_v2.py --pdf "../data/raw/국사교과서.pdf" --debug
    python pipeline_v2.py --pdf "../data/raw/국사교과서.pdf" --scan   # 스캔 강제
"""

import argparse
import sys
import time
from datetime import date
from pathlib import Path

# steps/ 를 import 경로에 추가 (steps 내부 상대 import: _layout, _oai 해소용)
sys.path.insert(0, str(Path(__file__).parent / "steps"))

from step1_detect import detect_scan            # noqa: E402
from step2_extract_cu import step2_extract_cu    # noqa: E402
from step2_extract_mu import step2_extract_mu    # noqa: E402
from step3_parse_cu import step3_parse_cu        # noqa: E402
from step4_cv_refine import step4_cv_refine      # noqa: E402
from step5_llm import step5_llm                  # noqa: E402


# ---------------------------------------------------------------------------
# 유틸 — 버전 폴더 생성
# ---------------------------------------------------------------------------

def _make_out_dir(pdf_path: str) -> Path:
    """result/{pdf이름}_vN/ 폴더를 자동 버전 증가하며 생성한다."""
    pdf_stem = Path(pdf_path).stem
    base = Path(__file__).parent / "result"
    v = 1
    while True:
        out = base / f"{pdf_stem}_v{v}"
        if not out.exists():
            break
        v += 1
    (out / "images").mkdir(parents=True)
    (out / "txt").mkdir(parents=True)
    return out


def _prepare_out_dir(out_dir: Path) -> Path:
    """명시된 출력 디렉터리에 표준 하위 구조(images/ txt/)를 만든다(멱등).
    오케스트레이터가 작업 격리 디렉터리(var/jobs/<id>/preprocess)를 직접 줄 때 쓴다."""
    out_dir = Path(out_dir)
    (out_dir / "images").mkdir(parents=True, exist_ok=True)
    (out_dir / "txt").mkdir(parents=True, exist_ok=True)
    return out_dir


# ---------------------------------------------------------------------------
# 실행 로그 저장
# ---------------------------------------------------------------------------

def _write_run_log(out_dir: Path, pdf_path: str, is_scan: bool, timings: dict, figures: list[dict], notes: list[str]) -> None:
    pdf_name   = Path(pdf_path).name
    pdf_type   = "스캔" if is_scan else "디지털"
    today      = date.today().isoformat()
    total      = sum(v for v in timings.values() if v is not None)
    img_count  = len(figures)
    cap_count  = sum(1 for f in figures if f.get("caption"))
    content    = (out_dir / "txt" / "content.txt")
    body_chars = len(content.read_text(encoding="utf-8")) if content.exists() else 0

    rows = []
    for label, secs in timings.items():
        val = f"{secs:.1f}s" if secs is not None else "-"
        rows.append(f"| {label} | {val} |")

    notes_md = "\n".join(f"- {n}" for n in notes) if notes else "- 특이사항 없음"

    md = f"""\
### {today} — {pdf_name} ({pdf_type})

| 스텝 | 소요 시간 |
|------|-----------|
{chr(10).join(rows)}
| **총 소요** | **{total:.1f}s** |

결과: 이미지 {img_count}개 / 캡션 {cap_count}개 / 본문 {body_chars:,}자

특이사항:
{notes_md}
"""

    log_path = out_dir / "run_log.md"
    log_path.write_text(md, encoding="utf-8")
    print(f"[LOG]    {log_path}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def run_pipeline(pdf_path: str, out_dir=None, *, force_scan: bool = False, debug: bool = False) -> dict:
    """PDF 한 부를 전처리해 산출 디렉터리를 채운다.

    out_dir 가 None 이면 result/{stem}_vN/ 로 자동 버전, 주어지면 그 디렉터리(작업
    격리)에 직접 쓴다. steps 호출 순서·인자는 main 과 동일 — 추출/정제 로직은 여기서
    바꾸지 않는다(steps/ 가 단일 진실원본). 반환: out_dir/is_scan/content_path 등.
    """
    timings: dict[str, float | None] = {}
    notes: list[str] = []

    # STEP 1 — 스캔/디지털 판별
    t = time.time()
    step1 = detect_scan(pdf_path, force_scan=force_scan)
    timings["STEP 1 스캔 판별"] = time.time() - t
    print(f"[STEP 1] {step1['reason']}")

    out_dir = _prepare_out_dir(out_dir) if out_dir is not None else _make_out_dir(pdf_path)
    print(f"[OUT]    {out_dir}")

    if step1["is_scan"]:
        # 스캔 경로: CU 추출 → 파싱 → 이미지 후처리
        t = time.time()
        raw = step2_extract_cu(pdf_path, out_dir, debug=debug)
        timings["STEP 2-CU API 추출"] = time.time() - t

        t = time.time()
        figures = step3_parse_cu(raw, pdf_path, out_dir, debug=debug)
        timings["STEP 3-CU 분리"] = time.time() - t

        t = time.time()
        figures = step4_cv_refine(figures, pdf_path, out_dir, debug=debug)
        timings["STEP 4 이미지 후처리"] = time.time() - t
    else:
        # 디지털 경로: PyMuPDF 추출 (STEP 3/4 미적용)
        t = time.time()
        figures = step2_extract_mu(pdf_path, out_dir, debug=debug)
        timings["STEP 2-MU 추출"] = time.time() - t
        timings["STEP 3-CU 분리"] = None
        timings["STEP 4 이미지 후처리"] = None
        notes.append("STEP 3/4 미적용 (디지털 경로)")

    # STEP 5 — LLM 정제·캡션·목차 (스캔 여부 전달)
    t = time.time()
    figures = step5_llm(out_dir, is_scan=step1["is_scan"], figures=figures, debug=debug)
    timings["STEP 5 LLM 전체"] = time.time() - t

    _write_run_log(out_dir, pdf_path, step1["is_scan"], timings, figures, notes)

    total = sum(v for v in timings.values() if v is not None)
    print(f"[DONE]   파이프라인 완료 (총 {total:.1f}s)")
    return {
        "out_dir": out_dir,
        "is_scan": step1["is_scan"],
        "content_path": out_dir / "txt" / "content.txt",
        "timings": timings,
        "figures": figures,
    }


def main():
    parser = argparse.ArgumentParser(description="전처리 파이프라인 v2")
    parser.add_argument("--pdf", required=True, help="입력 PDF 경로")
    parser.add_argument("--scan", action="store_true", help="스캔 PDF로 강제 지정")
    parser.add_argument("--debug", action="store_true", help="중간 파일 저장")
    parser.add_argument(
        "--out-dir", default=None,
        help="출력 디렉터리(미지정 시 result/{pdf이름}_vN/ 자동 버전)",
    )
    args = parser.parse_args()
    run_pipeline(args.pdf, out_dir=args.out_dir, force_scan=args.scan, debug=args.debug)


if __name__ == "__main__":
    main()
