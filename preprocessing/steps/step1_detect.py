"""
STEP 1 — 스캔 / 디지털 PDF 판별

실행:
    python step1_detect.py --pdf "../../data/raw/통계기초.pdf"
    python step1_detect.py --pdf "../../data/raw/통계기초.pdf" --scan

판별 기준:
    - 문서 중간 2페이지의 평균 글자 수 < 100 → 스캔 PDF
    - PyMuPDF 미설치 시 스캔으로 간주
"""

import argparse
import sys

try:
    import fitz  # PyMuPDF
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False


def detect_scan(pdf_path: str, force_scan: bool = False) -> dict:
    """
    PDF가 스캔본인지 디지털 텍스트 PDF인지 판별한다.

    Returns:
        {
            "is_scan": bool,
            "avg_chars": float | None,   # PyMuPDF 미설치 시 None
            "checked_pages": list[int],  # 0-indexed
            "reason": str                # 판별 근거 메시지
        }
    """
    if force_scan:
        return {
            "is_scan": True,
            "avg_chars": None,
            "checked_pages": [],
            "reason": "--scan 플래그로 수동 강제 지정",
        }

    if not FITZ_AVAILABLE:
        return {
            "is_scan": True,
            "avg_chars": None,
            "checked_pages": [],
            "reason": "PyMuPDF 미설치 → 스캔으로 간주",
        }

    doc = fitz.open(pdf_path)
    n = len(doc)

    mid = n // 2
    pages = [mid, min(mid + 1, n - 1)]
    # 1페이지 문서인 경우 같은 페이지가 중복될 수 있으므로 dedupe
    pages = list(dict.fromkeys(pages))

    char_counts = [len(doc[i].get_text().strip()) for i in pages]
    avg = sum(char_counts) / len(char_counts)
    doc.close()

    is_scan = avg < 100
    detail = ", ".join(
        f"p{p + 1}={c}자" for p, c in zip(pages, char_counts)
    )
    reason = (
        f"중간 페이지 평균 {avg:.1f}자 ({detail}) "
        f"→ {'스캔' if is_scan else '디지털'} PDF"
    )

    return {
        "is_scan": is_scan,
        "avg_chars": avg,
        "checked_pages": pages,
        "reason": reason,
    }


def main():
    parser = argparse.ArgumentParser(description="STEP 1 — 스캔/디지털 PDF 판별")
    parser.add_argument("--pdf", required=True, help="입력 PDF 경로")
    parser.add_argument(
        "--scan",
        action="store_true",
        help="수동으로 스캔 PDF로 강제 지정",
    )
    args = parser.parse_args()

    result = detect_scan(args.pdf, force_scan=args.scan)

    print(f"[STEP 1] {result['reason']}")
    print(f"  is_scan    : {result['is_scan']}")
    print(f"  avg_chars  : {result['avg_chars']}")
    print(f"  pages      : {[p + 1 for p in result['checked_pages']]}")  # 1-indexed 표시
    print(f"  → 다음 단계: {'STEP 2-CU (Content Understanding)' if result['is_scan'] else 'STEP 2-MU (PyMuPDF)'}")

    # 종료 코드: 0 = 디지털, 1 = 스캔 (쉘 스크립트 분기용)
    sys.exit(1 if result["is_scan"] else 0)


if __name__ == "__main__":
    main()
