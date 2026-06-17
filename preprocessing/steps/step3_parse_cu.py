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
# 본문 캡션 추출 — figcaption 태그 밖, 본문에 흘러든 캡션
# 형태: "주제 | 시·도 설명" (파이프 1개 + 뒤에 광역 지역명). 푸터/헤딩/키워드목록 배제.
# ---------------------------------------------------------------------------

_SIDO = "서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주"
_SIDO_RE = re.compile(rf"(?:{_SIDO})\b")


def _is_body_caption(line: str) -> bool:
    s = line.strip()
    if not s or s[0] in "#<|":               # 헤딩/주석/표 행 제외
        return False
    if (s.count("|") + s.count("ㅣ")) != 1:    # 파이프 정확히 1개(키워드목록 배제)
        return False
    after = re.split(r"[|ㅣ]", s, 1)[1].strip()
    return _SIDO_RE.match(after) is not None    # 파이프 뒤가 지역명으로 시작


def _looks_like_block(line: str) -> bool:
    """캡션 이어붙이기를 멈춰야 하는 줄(빈 줄/새 블록 시작)인지."""
    s = line.strip()
    return (not s) or s[0] in "#<|" or _is_body_caption(line)


# 캡션 끝에 CU가 잘못 붙인 러닝푸터(쪽번호 + 로마자 단원기호 + 단원명) 제거.
# 예: "조운선 모형 134 V. 조선의 성립과 발전" → "조운선 모형"
_FOOTER_RE = re.compile(
    r"\s*\d{1,3}\s*[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫIVXWvwx]+\s*\.\s*[가-힣][가-힣\s·]*$"
)


def _strip_footer(text: str) -> str:
    return _FOOTER_RE.sub("", text).rstrip()


def _iter_body_captions(md: str, start_page: int):
    """본문 캡션을 (offset, page, text, raw_block)로 yield. 이어지는 줄까지 합친다."""
    lines = md.split("\n")
    offs, o = [], 0
    for ln in lines:
        offs.append(o)
        o += len(ln) + 1
    j = 0
    while j < len(lines):
        if _is_body_caption(lines[j]):
            start = offs[j]
            pb = len(re.findall(r"<!--\s*PageBreak\s*-->", md[:start]))
            buf = [lines[j].strip()]
            k = j + 1
            while k < len(lines) and not _looks_like_block(lines[k]):
                buf.append(lines[k].strip())
                k += 1
            raw_block = "\n".join(lines[j:k])
            text = " ".join(" ".join(buf).split())
            yield start, start_page + pb, text, raw_block
            j = k
        else:
            j += 1


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
        caption = _strip_footer(cap_raw.strip())

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

    # figcaption + 본문 캡션을 문서 위치(offset) 순서로 수집 (페이지번호 포함)
    caption_entries: list[tuple[int, int, str]] = []   # (offset, page, text)
    body_blocks: list[str] = []                        # 본문에서 제거할 캡션 블록
    cursor = 0
    fig_pat = re.compile(r"<figcaption>(.*?)</figcaption>", re.DOTALL)
    for c in contents:
        md = c.get("markdown") or c.get("markdownContent", "")
        if not md:
            continue
        start_page = c.get("startPageNumber", 1)
        for m in fig_pat.finditer(md):
            pb = len(re.findall(r"<!--\s*PageBreak\s*-->", md[: m.start()]))
            text = _strip_footer(m.group(1).strip())   # \n 유지(한 블록 캡션 2개면 step4 분리에 사용)
            if text:
                caption_entries.append((cursor + m.start(), start_page + pb, text))
        for off, page, text, raw_block in _iter_body_captions(md, start_page):
            caption_entries.append((cursor + off, page, _strip_footer(text)))
            body_blocks.append(raw_block)
        cursor += len(md) + 2           # full_md "\n\n".join 보정

    # 추출한 본문 캡션은 content_raw.txt에 중복되지 않도록 본문에서 제거 후 정제
    for blk in body_blocks:
        full_md = full_md.replace(blk, "", 1)
    body = _clean_markdown(full_md)
    body, inline_caps = _extract_inline_captions(body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    (txt_dir / "content_raw.txt").write_text(body, encoding="utf-8")
    print(f"[CU] content_raw.txt 저장 완료 ({len(body):,}자)")

    if debug:
        (txt_dir / "content_raw.md").write_text(full_md, encoding="utf-8")
        print(f"[CU] content_raw.md 저장 완료 (debug)")

    # ── 3. 캡션 → figure 매칭 (페이지 단위) ───────────────────────────────────
    # 문서 순서로 정렬해 페이지별 캡션 풀을 만든다.
    caption_entries.sort()
    caps_by_page: dict[int, list[str]] = {}
    for _off, page, text in caption_entries:
        caps_by_page.setdefault(page, []).append(text)

    def _norm(t: str) -> str:
        return "".join(t.split())

    # C 분리 전 원본 figure.caption(병합본 포함) 정규화 집합 — 같은 캡션이 <figcaption>
    # 마크다운으로 풀에도 들어와 다른 figure에 중복 배정되는 것을 막기 위함.
    prior_caps = {_norm(f["caption"]) for f in figures if f.get("caption")}

    # 병합 캡션 분리: figure.caption에 '주제 | 시·도 …' 형태의 별개 캡션이 \n으로
    # 묶여 있으면(예: page37 영조 어진 + 녹우단), 첫 캡션만 남기고 떼어낸 캡션은
    # 같은 페이지 풀에 넣어 빈 figure에 배정한다.
    # 게이트: 떼어낼 줄이 '| 시·도' 독립 캡션일 때만 → '향교 | 김홍도'(작가) 등은
    # 분리하지 않아 step4 이미지 분리 로직(page10)을 깨지 않는다.
    for fig in figures:
        cap = fig.get("caption", "")
        if "\n" not in cap:
            continue
        lines = [ln.strip() for ln in cap.split("\n") if ln.strip()]
        # 첫 줄은 항상 본 캡션으로 유지. 둘째 줄 이후에서 '| 시·도' 독립 캡션만 떼어낸다
        # (소프트랩 연속 줄은 본 캡션에 붙여 둠 → page17 같은 한 문장 캡션 보존).
        keep = [lines[0]]
        split_off = []
        for ln in lines[1:]:
            (split_off if _is_body_caption(ln) else keep).append(ln)
        if split_off:
            fig["caption"] = " ".join(keep)
            caps_by_page.setdefault(fig["page"], []).extend(split_off)

    if debug:
        caption_lines = [f"[page{p}] {t}" for _o, p, t in caption_entries]
        caption_lines += [f"[inline] {t}" for t in inline_caps if t]
        (txt_dir / "caption_raw.txt").write_text(
            "\n".join(caption_lines), encoding="utf-8"
        )
        print(f"[CU] caption_raw.txt 저장 완료 (debug, {len(caption_lines)}개)")

    # 같은 페이지의 캡션을 figure에 위→아래(문서 순서)로 배정 → 페이지 넘는 오배정 방지.
    # 원본·현재 figure.caption과 같은 풀 항목은 제외(병합본 중복 방지 포함).
    assigned = prior_caps | {_norm(f["caption"]) for f in figures if f["caption"]}
    pools = {
        pg: [t for t in txts if _norm(t) not in assigned]
        for pg, txts in caps_by_page.items()
    }
    for fig in figures:
        if fig["caption"]:
            continue
        pool = pools.get(fig["page"])
        if pool:
            fig["caption"] = pool.pop(0)

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
