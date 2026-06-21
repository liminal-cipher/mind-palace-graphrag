"""
로컬 PaddleOCR 텍스트 추출 유틸 (스캔 PDF → 텍스트, CPU)

목적:
    스캔 PDF 한 부에서 본문 텍스트만 로컬에서 뽑는다(외부 API·비용 없음). Azure CU
    경로(steps/step2_extract_cu)의 텍스트를 대체/검증할 때 쓰는 보조 도구다.
    이미지·캡션·목차는 만들지 않는다(그건 CU 경로의 STEP 3/4/5 가 담당).

설계 결정(레포 정합):
    - 입력은 항상 *주어진 PDF 경로*다(폴더 glob 안 함). 프론트 업로드 →
      orchestrator → 잡 폴더로 들어온 PDF 경로를 그대로 받는 흐름과 같다.
    - 래스터화는 poppler/pdf2image 가 아니라 fitz(PyMuPDF)로 한다 —
      steps/step2_premask._render_page 와 동일 방식이라 새 바이너리 의존이 없다.
    - PaddleOCR 은 레포에 설치된 2.10.0 API 를 쓴다(step2_premask 와 동일):
      PaddleOCR(use_angle_cls=True, ...) + ocr.ocr(arr, cls=True).
    - MIN_SCORE 미만 인식 결과는 버린다(지도 위 깨진 글자 등 노이즈 제거).

출력:
    txt/content_paged.txt 와 같은 [pageN] 마커 형식으로 쓴다(파이프라인에 그대로
    먹일 수 있게). --plain 이면 마커 없이 본문만.

실행:
    python preprocessing/ocr_paddle.py --pdf "<경로>.pdf"
    python preprocessing/ocr_paddle.py --pdf "<경로>.pdf" --out content.txt --plain
    python preprocessing/ocr_paddle.py --pdf "<경로>.pdf" --dpi 200 --min-score 0.5
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import fitz  # PyMuPDF — 페이지 래스터화(step2_premask 와 동일)

logger = logging.getLogger("preprocessing.ocr_paddle")

# ---- 기본 설정 ----
DEFAULT_DPI = 300          # test.py 와 동일. fitz 배율 = DPI/72.
DEFAULT_MIN_SCORE = 0.6    # 이 신뢰도 미만 인식 결과는 버림(노이즈 제거)
# -------------------


# ── 로컬 OCR (PaddleOCR 2.10) — lazy 싱글톤 ─────────────────────────────────
_OCR = None


def _get_ocr():
    """PaddleOCR 한국어 모델을 lazy 로드(2.10 API, step2_premask 와 동일 호출).
    실패하면 명확한 에러로 중단한다(유틸은 OCR 가 핵심이라 폴백 의미 없음)."""
    global _OCR
    if _OCR is None:
        # Windows DLL 순서: paddle 을 torch 보다 먼저 로드하면 torch 가 shm.dll 의존
        # 로드에서 WinError 127 로 깨진다(둘이 같은 런타임 DLL 을 공유). paddleocr 의
        # import 체인이 paddle 을 먼저 끌어오므로, 여기서 torch 를 *먼저* 임포트해
        # DLL 로드 순서를 고정한다.
        import torch  # noqa: F401  (순서 고정용 선임포트)
        from paddleocr import PaddleOCR

        # PaddleOCR 3.x API. lang="korean": 한글+숫자+영문.
        # use_textline_orientation=True(구 use_angle_cls): 회전 텍스트 보정.
        # device="cpu": 레포 CPU 휠 전제. enable_mkldnn=False: OneDNN 융합 conv 가
        # paddle 3.3.1 에서 'fused_conv2d ... does not have input Filter' 로 터지는
        # 것을 막는다(일반 conv 폴백). 인자 구성은 검증된 zip test.py 와 동일.
        _OCR = PaddleOCR(
            use_textline_orientation=True,
            lang="korean",
            device="cpu",
            enable_mkldnn=False,
        )
        logger.info("PaddleOCR(korean) 로드 완료")
    return _OCR


def _render_page(page: "fitz.Page", dpi: int) -> "Image.Image":
    """페이지를 dpi 배율로 렌더해 PIL 이미지로 돌려준다(step2_premask 와 동일 방식)."""
    from PIL import Image

    scale = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def ocr_image(pil_img, min_score: float) -> list[str]:
    """한 페이지 이미지에서 신뢰도 min_score 이상인 텍스트 줄 목록을 뽑는다."""
    import numpy as np

    ocr = _get_ocr()
    result = ocr.predict(np.array(pil_img))

    lines: list[str] = []
    # PaddleOCR 3.x 반환: result 는 페이지별 dict 리스트. 각 dict 의 rec_texts/
    # rec_scores 가 인식 텍스트·신뢰도 병렬 배열. (구 4점-폴리곤 반환과 다름)
    for res in result:
        texts = res.get("rec_texts", [])
        scores = res.get("rec_scores", [1.0] * len(texts))
        for text, score in zip(texts, scores):
            if score >= min_score and text.strip():
                lines.append(text)
    return lines


def ocr_pdf(
    pdf_path: str,
    out_path: Path,
    *,
    dpi: int = DEFAULT_DPI,
    min_score: float = DEFAULT_MIN_SCORE,
    plain: bool = False,
) -> dict:
    """스캔 PDF 를 페이지별 OCR 해 out_path 에 텍스트를 쓴다.

    plain=False(기본): 페이지마다 [pageN] 마커 + 본문(content_paged.txt 호환).
    plain=True: 마커 없이 본문만 이어붙임(content.txt 호환).
    반환: {out_path, pages, chars}.
    """
    src = Path(pdf_path)
    if not src.is_file():
        raise FileNotFoundError(f"PDF 없음: {src}")

    doc = fitz.open(src)
    blocks: list[str] = []
    try:
        for i in range(len(doc)):
            page_no = i + 1
            print(f"  - {page_no}/{len(doc)} 페이지 OCR 중...")
            lines = ocr_image(_render_page(doc[i], dpi), min_score)
            body = "\n".join(lines)
            blocks.append(body if plain else f"[page{page_no}]\n{body}")
    finally:
        doc.close()

    text = "\n\n".join(blocks).strip() + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"[저장 완료] {out_path} ({len(text):,}자, {len(blocks)}페이지)")
    return {"out_path": out_path, "pages": len(blocks), "chars": len(text)}


def main() -> None:
    parser = argparse.ArgumentParser(description="로컬 PaddleOCR 스캔 PDF 텍스트 추출")
    parser.add_argument("--pdf", required=True, help="입력 PDF 경로")
    parser.add_argument(
        "--out", default=None,
        help="출력 텍스트 경로(미지정 시 <pdf>_ocr.txt)",
    )
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"래스터 DPI(기본 {DEFAULT_DPI})")
    parser.add_argument(
        "--min-score", type=float, default=DEFAULT_MIN_SCORE,
        help=f"이 신뢰도 미만 인식 결과 버림(기본 {DEFAULT_MIN_SCORE})",
    )
    parser.add_argument(
        "--plain", action="store_true",
        help="[pageN] 마커 없이 본문만(content.txt 형식)",
    )
    args = parser.parse_args()

    out = Path(args.out) if args.out else Path(args.pdf).with_name(Path(args.pdf).stem + "_ocr.txt")
    print(f"{'='*60}\n[처리 중] {Path(args.pdf).name}\n{'='*60}")
    ocr_pdf(
        args.pdf, out,
        dpi=args.dpi, min_score=args.min_score, plain=args.plain,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    main()
