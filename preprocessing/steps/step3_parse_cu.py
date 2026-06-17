"""
STEP 3-CU — 이미지 / 텍스트 / 캡션 분리 (CU 경로 전용)

raw_response.json을 파싱하여:
  - 이미지: figure bbox → PyMuPDF로 크롭 → img/fig_{page}_{idx}.png
  - 본문 텍스트: markdown 정제 → txt/content_raw.txt
  - 캡션: figcaption / figure.caption 필드 추출

실행:
    python step3_parse_cu.py --raw "../result/test_v1/raw_response.json" \
                              --pdf "../../data/raw/국사교과서.pdf" \
                              --out "../result/test_v1"
    python step3_parse_cu.py --raw ... --pdf ... --out ... --debug
"""

import argparse
import io
import json
import re
from pathlib import Path

import fitz
from PIL import Image

SCALE = 2.0
MIN_AREA_PX = 30 * 30   # 너무 작은 이미지 제외 (픽셀²)


# ---------------------------------------------------------------------------
# 이미지 크롭 헬퍼
# ---------------------------------------------------------------------------

def _parse_source(source: str) -> list[dict]:
    """
    'D(page,x0,y0,x1,y1,...);D(...)' → [{"page": int, "bbox": [x0,y0,x1,y1]}, ...]
    좌표 단위: 인치, page는 1-based.
    """
    regions = []
    for m in re.finditer(r"D\((\d+),([\d.,]+)\)", source):
        page = int(m.group(1))
        coords = [float(v) for v in m.group(2).split(",")]
        xs, ys = coords[0::2], coords[1::2]
        regions.append({"page": page, "bbox": [min(xs), min(ys), max(xs), max(ys)]})
    return regions


def _inch_to_px(bbox_inch: list[float], scale: float) -> list[int]:
    """인치 → 픽셀 (72 pt/inch × scale)"""
    dpi = 72.0 * scale
    return [int(v * dpi) for v in bbox_inch]


def _safe_crop(pil_img: Image.Image, bbox_px: list[int]) -> Image.Image:
    x0, y0, x1, y1 = bbox_px
    w, h = pil_img.size
    return pil_img.crop((max(0, x0), max(0, y0), min(w, x1), min(h, y1)))


# 매 페이지 반복되는 머리말/꼬리말 장식(로고 등)은 제외한다.
_SKIP_FIGURE_ROLES = {"pageHeader", "pageFooter"}


def _collect_raw_figures(data: dict) -> list[dict]:
    """raw_response.json에서 figure 목록을 모은다.

    figure가 참조하는 paragraph의 role이 pageHeader/pageFooter이면
    (매 페이지 반복되는 국사편찬위원회 로고 등) 본문 이미지가 아니므로 건너뛴다.
    """
    figures = []
    for content in data.get("result", {}).get("contents", []):
        paragraphs = content.get("paragraphs", [])
        skip_idx = {
            i for i, p in enumerate(paragraphs)
            if p.get("role") in _SKIP_FIGURE_ROLES
        }

        def _is_chrome(fig: dict) -> bool:
            # 참조 paragraph가 있고 그 role이 전부 header/footer일 때만 장식으로 본다.
            # (로고는 pageHeader paragraph 1개만 참조. 본문 figure는 여러 paragraph를
            #  참조하며 일부에 footer가 섞여도 본문이므로 제외하지 않는다.)
            para_idx = [
                int(m.group(1))
                for e in fig.get("elements", [])
                if (m := re.match(r"/paragraphs/(\d+)$", e))
            ]
            return bool(para_idx) and all(i in skip_idx for i in para_idx)

        for fig in content.get("figures", []):
            if not _is_chrome(fig):
                figures.append(fig)
        for page in content.get("pages", []):
            for fig in page.get("figures", []):
                if not _is_chrome(fig):
                    figures.append(fig)
    return figures


# ---------------------------------------------------------------------------
# 텍스트 정제 헬퍼
# ---------------------------------------------------------------------------

def _insert_page_markers(text: str) -> str:
    """<!-- page X–Y --> 및 <!-- PageBreak --> → [pageN] 마커로 변환."""
    current_page = [1]

    def _on_header(m):
        current_page[0] = int(m.group(1))
        return f"[page{current_page[0]}]"

    def _on_break(_m):
        current_page[0] += 1
        return f"[page{current_page[0]}]"

    text = re.sub(r"<!--\s*page\s+(\d+)[–\-]\d+\s*-->", _on_header, text)
    text = re.sub(r"<!--\s*PageBreak\s*-->", _on_break, text)
    return text


def _clean_markdown(md: str) -> str:
    """markdown 원본 → 순수 본문 텍스트 (content_raw.txt용)."""
    text = md
    text = re.sub(r"<table>.*?</table>", "", text, flags=re.DOTALL)
    text = re.sub(r"<figure>.*?</figure>", "", text, flags=re.DOTALL)
    text = _insert_page_markers(text)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"\$\$.*?\$\$", "", text, flags=re.DOTALL)
    text = re.sub(r"\$[^$\n]+?\$", "", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[•·]\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# 캡션 혼입 감지 패턴
# ---------------------------------------------------------------------------

_CAPTION_INLINE_PAT = re.compile(
    r"^(그림\s*\d+[\.\s]|Figure\s*\d+[\.\s])|(\|.*\|.{0,100})$",
    re.MULTILINE | re.IGNORECASE,
)


def _extract_inline_captions(text: str) -> tuple[str, list[str]]:
    """본문에 혼입된 캡션 패턴을 감지·분리한다. (text_cleaned, inline_captions)"""
    inline = []

    def _capture(m):
        inline.append(m.group(0).strip())
        return ""

    cleaned = _CAPTION_INLINE_PAT.sub(_capture, text)
    return cleaned, inline


# ---------------------------------------------------------------------------
# STEP 3-CU 메인
# ---------------------------------------------------------------------------

def step3_parse_cu(
    raw_response: dict,
    pdf_path: str,
    out_dir: Path,
    debug: bool = False,
) -> list[dict]:
    """
    raw_response.json → 이미지 크롭 + 텍스트 + 캡션 분리.

    Returns: figures 리스트 (figures.json 스키마)
    """
    img_dir = out_dir / "img"
    txt_dir = out_dir / "txt"
    img_dir.mkdir(parents=True, exist_ok=True)
    txt_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. 이미지 크롭 ───────────────────────────────────────────────────────
    raw_figures = _collect_raw_figures(raw_response)
    doc = fitz.open(pdf_path)
    page_cache: dict[int, Image.Image] = {}

    figures: list[dict] = []
    page_img_count: dict[int, int] = {}

    for raw_fig in raw_figures:
        fig_id  = raw_fig.get("id", "")
        source  = raw_fig.get("source", "")
        regions = _parse_source(source)
        if not regions:
            continue

        r        = regions[0]
        page_no  = r["page"]          # 1-based
        page_idx = page_no - 1

        if page_idx < 0 or page_idx >= len(doc):
            continue

        if page_idx not in page_cache:
            pix = doc[page_idx].get_pixmap(matrix=fitz.Matrix(SCALE, SCALE))
            page_cache[page_idx] = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        pil_img = page_cache[page_idx]
        bbox_px = _inch_to_px(r["bbox"], SCALE)
        area    = (bbox_px[2] - bbox_px[0]) * (bbox_px[3] - bbox_px[1])
        if area < MIN_AREA_PX:
            continue

        idx = page_img_count.get(page_no, 0) + 1
        page_img_count[page_no] = idx

        img_filename = f"fig_{page_no}_{idx}.png"
        _safe_crop(pil_img, bbox_px).save(img_dir / img_filename, format="PNG")
        print(f"  [page {page_no:3d}] {img_filename}  bbox_inch={r['bbox']}")

        # 캡션 — 1순위: raw_fig.caption 필드, 없으면 빈 문자열
        cap_raw = raw_fig.get("caption") or ""
        if isinstance(cap_raw, dict):
            cap_raw = cap_raw.get("content", "")
        caption = cap_raw.strip()

        figures.append({
            "id":                fig_id,
            "page":              page_no,
            "bbox_inch":         r["bbox"],
            "img_path":          str(Path("img") / img_filename),
            "caption":           caption,
            "false_positive_type": None,
            "sub_crops":         [],
        })

    doc.close()
    print(f"\n[CU] 이미지 {len(figures)}개 크롭 완료")

    # ── 2. 본문 텍스트 추출 ──────────────────────────────────────────────────
    contents = raw_response.get("result", {}).get("contents", [])
    md_parts = []
    for c in contents:
        md = c.get("markdown") or c.get("markdownContent", "")
        if md:
            md_parts.append(md)
    full_md = "\n\n".join(md_parts)

    # figcaption에서 캡션 먼저 수집 (본문 텍스트 정제 전)
    fig_pat = re.compile(r"<figcaption>(.*?)</figcaption>", re.DOTALL)
    figcaption_list: list[dict] = []
    for c in contents:
        md = c.get("markdown") or c.get("markdownContent", "")
        if not md:
            continue
        start_page = c.get("startPageNumber", 1)
        for m in fig_pat.finditer(md):
            pb = len(re.findall(r"<!--\s*PageBreak\s*-->", md[: m.start()]))
            text = m.group(1).strip()
            if text:
                figcaption_list.append({"page": start_page + pb, "text": text})

    # 본문 정제
    body = _clean_markdown(full_md)
    body, inline_caps = _extract_inline_captions(body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    (txt_dir / "content_raw.txt").write_text(body, encoding="utf-8")
    print(f"[CU] content_raw.txt 저장 완료 ({len(body):,}자)")

    if debug:
        (txt_dir / "content_raw.md").write_text(full_md, encoding="utf-8")
        print(f"[CU] content_raw.md 저장 완료 (debug)")

    # ── 3. 캡션 병합 저장 ────────────────────────────────────────────────────
    # figcaption 우선, 그 다음 inline 혼입 캡션
    # figures 각 항목의 caption 필드는 이미 위에서 채워짐
    # figcaption_list는 STEP 5에서 LLM 정제 입력으로 사용

    caption_lines = [f"[page{c['page']}] {c['text']}" for c in figcaption_list]
    caption_lines += [f"[inline] {t}" for t in inline_caps if t]

    # caption.txt는 STEP 5 LLM 정제 후 덮어쓸 예정이므로 여기서는 _raw 저장
    if debug:
        (txt_dir / "caption_raw.txt").write_text(
            "\n".join(caption_lines), encoding="utf-8"
        )
        print(f"[CU] caption_raw.txt 저장 완료 (debug, {len(caption_lines)}개)")

    # figcaption 정보를 figures에 보완 (순서 기반 매칭)
    for i, fig in enumerate(figures):
        if not fig["caption"] and i < len(figcaption_list):
            fig["caption"] = figcaption_list[i]["text"]

    # figures.json — step4·step5로 넘기는 필수 핸드오프이므로 항상 저장
    # (캡션 보완까지 끝난 최종 figures를 기록)
    meta_dir = out_dir / "meta"
    meta_dir.mkdir(exist_ok=True)
    (meta_dir / "figures.json").write_text(
        json.dumps(figures, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[CU] meta/figures.json 저장 완료")

    return figures


def main():
    parser = argparse.ArgumentParser(description="STEP 3-CU — 이미지/텍스트/캡션 분리")
    parser.add_argument("--raw", required=True, help="raw_response.json 경로")
    parser.add_argument("--pdf", required=True, help="원본 PDF 경로")
    parser.add_argument("--out", required=True, help="출력 디렉토리 경로")
    parser.add_argument("--debug", action="store_true", help="중간 파일 저장")
    args = parser.parse_args()

    out_dir = Path(args.out)
    raw = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    figures = step3_parse_cu(raw, args.pdf, out_dir, debug=args.debug)

    print(f"\n--- 결과 요약 ---")
    print(f"이미지  : {len(figures)}개")
    print(f"출력    : {out_dir}")


if __name__ == "__main__":
    main()
