"""
PoC — CU 통합 전, 마스킹 전처리가 실제로 되는지 단독 검증.

파이프라인에 끼우기 전에 이 스크립트만으로 다음을 눈으로 확인한다:
    1. PaddleOCR 가 한글 페이지에서 글자+좌표(bbox)를 뽑는가
    2. ko-pii / 안전망 정규식이 PII 조각을 골라내는가
    3. 검은 박스가 올바른 위치에 칠해지는가 (좌표 정합)

실행:
    # 실제 스캔 PDF 로
    python -m preprocessing.poc_premask --pdf preprocessing/source/sample.pdf --page 1

    # PDF 없이 합성 테스트 이미지로(OCR/마스킹 파이프 점검만)
    python -m preprocessing.poc_premask --synthetic

출력:
    out/poc_premask/page_{N}_original.png   원본 렌더
    out/poc_premask/page_{N}_masked.png     마스킹 결과
    out/poc_premask/page_{N}_report.txt     OCR 조각별 PII 판정 리포트(감사용)

주의:
    이 스크립트는 검증 전용이라 본 파이프라인(step2_premask.premask_pdf)을 그대로
    호출하지 않고, 페이지별 중간 산출(원본/마스킹/리포트)을 따로 떨궈 비교를 돕는다.
    실제 동작 로직은 step2_premask 의 함수를 재사용한다(단일 진실원본).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "preprocessing" / "steps"))

import step2_premask as pm  # noqa: E402


def _synthetic_image():
    """PII 가 섞인 합성 한글 이미지 한 장(PDF·OCR 없이 마스킹 로직만 점검)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", [900, 500], (255, 255, 255))
    draw = ImageDraw.Draw(img)
    lines = [
        "조선 태조 이성계는 1392년에 즉위하였다.",      # PII 아님(연도·인명 제외)
        "신청인 홍길동 (880101-1234568)",               # 주민번호 → 가려야 함
        "연락처 010-1234-5678  이메일 hong@test.kr",    # 전화·이메일 → 가려야 함
        "한양은 수도로 정해졌다.",                       # PII 아님
    ]
    # 폰트 없이 기본 비트맵으로 그린다(PoC 라 가독성만). y 좌표를 박스로 쓴다.
    boxes = []
    y = 60
    for text in lines:
        draw.text((40, y), text, fill=(0, 0, 0))
        # 합성 bbox: 텍스트 줄 전체를 한 박스로(실제론 OCR 이 단어별로 쪼갬)
        boxes.append((text, [40.0, float(y), 860.0, float(y + 28)]))
        y += 90
    return img, boxes


def _process_page(img, boxes, page_no: int, out_dir: Path) -> None:
    from PIL import Image  # noqa: F401

    original = img.copy()
    report_lines = [f"=== page {page_no} — OCR 조각 {len(boxes)}개 ===", ""]
    masked_count = 0
    for text, bbox in boxes:
        is_pii = pm._text_has_pii(text)
        mark = "■ MASK" if is_pii else "      "
        report_lines.append(f"{mark}  {text!r}")
        if is_pii:
            masked_count += 1
    report_lines += ["", f"마스킹 대상: {masked_count}/{len(boxes)} 조각"]

    n = pm._mask_page(img, boxes)  # img 에 직접 검은 박스
    assert n == masked_count, "리포트 판정과 실제 마스킹 수 불일치"

    out_dir.mkdir(parents=True, exist_ok=True)
    original.save(out_dir / f"page_{page_no}_original.png")
    img.save(out_dir / f"page_{page_no}_masked.png")
    (out_dir / f"page_{page_no}_report.txt").write_text(
        "\n".join(report_lines), encoding="utf-8"
    )
    print(f"[page {page_no}] OCR {len(boxes)}조각 / 마스킹 {n}개")
    for ln in report_lines:
        print("   " + ln)


def main() -> None:
    ap = argparse.ArgumentParser(description="마스킹 전처리 PoC")
    ap.add_argument("--pdf", help="검증할 스캔 PDF 경로")
    ap.add_argument("--page", type=int, default=1, help="검증할 페이지(1-based)")
    ap.add_argument("--synthetic", action="store_true", help="PDF 없이 합성 이미지로 점검")
    ap.add_argument("--out", default=str(REPO / "out" / "poc_premask"), help="출력 디렉터리")
    args = ap.parse_args()

    out_dir = Path(args.out)

    if args.synthetic:
        img, boxes = _synthetic_image()
        _process_page(img, boxes, args.page, out_dir)
        print(f"\n결과: {out_dir} (원본/마스킹/리포트 비교)")
        return

    if not args.pdf:
        ap.error("--pdf 또는 --synthetic 중 하나는 필요합니다")

    import fitz

    doc = fitz.open(args.pdf)
    page_idx = args.page - 1
    if page_idx < 0 or page_idx >= len(doc):
        ap.error(f"페이지 범위 밖: {args.page} (총 {len(doc)}쪽)")

    img = pm._render_page(doc[page_idx])      # SCALE=2.0 으로 렌더(파이프라인과 동일)
    boxes = pm._ocr_boxes(img)                # PaddleOCR 로 글자+bbox
    doc.close()

    if not boxes:
        print("[경고] OCR 결과 0 — PaddleOCR 미설치이거나 글자 인식 실패. "
              "안전망 정규식만으로는 위치를 못 잡아 마스킹이 비어있을 수 있음.")
    _process_page(img, boxes, args.page, out_dir)
    print(f"\n결과: {out_dir} (원본/마스킹/리포트 비교)")


if __name__ == "__main__":
    main()
