"""
STEP 2-MU — PyMuPDF 추출 (디지털 PDF)

실행:
    python step2_extract_mu.py --pdf "../../data/raw/통계기초.pdf" --out "../result/test_v1"
    python step2_extract_mu.py --pdf "../../data/raw/통계기초.pdf" --out "../result/test_v1" --debug

산출물:
    out_dir/img/fig_{page}_{idx}.png  ← 크롭 이미지
    out_dir/txt/content_raw.txt       ← 페이지 마커 포함 원본 텍스트 (STEP 5 입력)
    (debug) out_dir/meta/figures.json ← 이미지 메타데이터
"""

import argparse
import io
import json
from pathlib import Path

import fitz
from PIL import Image

SCALE = 2  # 렌더링 배율 (크롭 해상도)


def step2_extract_mu(pdf_path: str, out_dir: Path, debug: bool = False) -> list[dict]:
    """
    디지털 PDF에서 텍스트와 이미지 블록을 추출한다.

    Returns:
        figures — figures.json 스키마와 동일한 dict 리스트
        [
            {
                "id": "1.1",
                "page": 1,           # 1-indexed
                "bbox": [x0,y0,x1,y1],
                "img_path": "img/fig_1_1.png",
                "caption": "",       # MU 경로: STEP 5에서 LLM 생성
                "false_positive_type": null,
                "sub_crops": []
            },
            ...
        ]
    """
    img_dir = out_dir / "img"
    txt_dir = out_dir / "txt"
    img_dir.mkdir(parents=True, exist_ok=True)
    txt_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    mat = fitz.Matrix(SCALE, SCALE)

    text_pages: list[str] = []   # 페이지별 텍스트 ([pageN] 마커 포함)
    figures: list[dict] = []
    page_img_count: dict[int, int] = {}  # page → 이미지 순번 (1-indexed)

    for page_num, page in enumerate(doc):
        page_no = page_num + 1  # 1-indexed
        blocks = page.get_text("dict")["blocks"]

        # --- 텍스트 수집 ---
        page_texts = []
        for b in blocks:
            if b["type"] != 0:
                continue
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    t = span.get("text", "").strip()
                    if t:
                        page_texts.append(t)

        page_text = " ".join(page_texts)
        text_pages.append(f"[page{page_no}]\n{page_text}")

        # --- 이미지 블록 크롭 ---
        img_blocks = [b for b in blocks if b["type"] == 1]
        if not img_blocks:
            continue

        pix = page.get_pixmap(matrix=mat)
        page_img = Image.open(io.BytesIO(pix.tobytes("png")))

        for block in img_blocks:
            x0, y0, x1, y1 = [int(v * SCALE) for v in block["bbox"]]
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(pix.width, x1), min(pix.height, y1)

            if x1 <= x0 or y1 <= y0:
                continue

            idx = page_img_count.get(page_no, 0) + 1
            page_img_count[page_no] = idx

            img_filename = f"fig_{page_no}_{idx}.png"
            img_path = img_dir / img_filename
            page_img.crop((x0, y0, x1, y1)).save(str(img_path))

            figures.append({
                "id": f"{page_no}.{idx}",
                "page": page_no,
                "bbox": [int(v) for v in block["bbox"]],
                "img_path": str(Path("img") / img_filename),
                "caption": "",
                "false_positive_type": None,
                "sub_crops": [],
            })

            print(f"  [page {page_no:3d}] fig_{page_no}_{idx}.png  bbox={block['bbox']}")

    doc.close()

    # --- content_raw.txt 저장 ---
    raw_text = "\n\n".join(text_pages)
    (txt_dir / "content_raw.txt").write_text(raw_text, encoding="utf-8")
    print(f"\n[MU] content_raw.txt 저장 완료 ({len(raw_text):,}자)")
    print(f"[MU] 이미지 {len(figures)}개 크롭 완료")

    # --- figures.json 저장 (step5로 넘기는 필수 핸드오프이므로 항상 저장) ---
    meta_dir = out_dir / "meta"
    meta_dir.mkdir(exist_ok=True)
    (meta_dir / "figures.json").write_text(
        json.dumps(figures, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[MU] meta/figures.json 저장 완료")

    return figures


def main():
    parser = argparse.ArgumentParser(description="STEP 2-MU — PyMuPDF 추출")
    parser.add_argument("--pdf", required=True, help="입력 PDF 경로")
    parser.add_argument("--out", required=True, help="출력 디렉토리 경로")
    parser.add_argument("--debug", action="store_true", help="중간 파일 저장")
    args = parser.parse_args()

    out_dir = Path(args.out)
    figures = step2_extract_mu(args.pdf, out_dir, debug=args.debug)

    print(f"\n--- 결과 요약 ---")
    print(f"이미지 블록 : {len(figures)}개")
    print(f"출력 위치   : {out_dir}")


if __name__ == "__main__":
    main()
