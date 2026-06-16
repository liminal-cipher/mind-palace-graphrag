"""
전처리 파이프라인 v2

실행 (원본 PDF는 preprocessing/source/<domain>.pdf 규약):
    python -m preprocessing.pipeline_v2 --pdf preprocessing/source/statistics.pdf
    python -m preprocessing.pipeline_v2 --pdf preprocessing/source/korean_history.pdf --debug
    python -m preprocessing.pipeline_v2 --pdf preprocessing/source/<domain>.pdf --scan
"""

import argparse
import base64
import io
import json
import os
import re
import sys
import tiktoken
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

try:
    import fitz  # PyMuPDF
    from PIL import Image
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False

# .env 로드 (pipeline_v2/ → preprocess/.env)
load_dotenv(Path(__file__).parent.parent / ".env")

_MU_SCALE = 2    # 렌더링 배율 (크롭 해상도)
_CU_SCALE = 2.0  # CU 경로 크롭 배율
_MIN_AREA_PX = 30 * 30


# ---------------------------------------------------------------------------
# STEP 1 — 스캔 / 디지털 PDF 판별
# ---------------------------------------------------------------------------

def detect_scan(pdf_path: str, force_scan: bool = False) -> dict:
    """
    Returns:
        {
            "is_scan": bool,
            "avg_chars": float | None,
            "checked_pages": list[int],  # 0-indexed
            "reason": str,
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
    pages = list(dict.fromkeys([mid, min(mid + 1, n - 1)]))
    char_counts = [len(doc[i].get_text().strip()) for i in pages]
    avg = sum(char_counts) / len(char_counts)
    doc.close()

    is_scan = avg < 100
    detail = ", ".join(f"p{p + 1}={c}자" for p, c in zip(pages, char_counts))
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


# ---------------------------------------------------------------------------
# STEP 2-CU — Content Understanding API 추출  (스캔 PDF)
# ---------------------------------------------------------------------------

_CU_ENDPOINT    = os.environ.get("CONTENT_UNDERSTANDING_ENDPOINT", "").rstrip("/")
_CU_KEY         = os.environ.get("CONTENT_UNDERSTANDING_KEY", "")
_CU_API_VER     = os.environ.get("CONTENT_UNDERSTANDING_API_VER", "2025-11-01")
_CU_ANALYZER_ID = "pdf_content_extractor"
_CU_BASE_HDR    = {"Ocp-Apim-Subscription-Key": _CU_KEY}
_CU_JSON_HDR    = {**_CU_BASE_HDR, "Content-Type": "application/json"}


def _cu_find_cached_raw(pdf_path: str, out_dir: Path) -> Path | None:
    """동일 PDF의 result/ 하위 버전 폴더에서 raw_response.json 탐색 (최신 우선)."""
    pdf_stem   = Path(pdf_path).stem
    result_dir = out_dir.parent
    found = None
    v = 1
    while True:
        folder = result_dir / f"{pdf_stem}_v{v}"
        if not folder.exists():
            break
        raw = folder / "raw_response.json"
        if raw.exists():
            found = raw
        v += 1
    return found


def _cu_ensure_analyzer() -> None:
    url  = f"{_CU_ENDPOINT}/contentunderstanding/analyzers/{_CU_ANALYZER_ID}?api-version={_CU_API_VER}"
    body = {
        "description": "PDF 텍스트·이미지·표·다이어그램 추출기",
        "baseAnalyzerId": "prebuilt-document",
    }
    resp = requests.put(url, headers=_CU_JSON_HDR, json=body, timeout=60)
    if resp.status_code in (200, 201):
        print("  분석기: 생성 완료")
        return
    if resp.status_code == 409:
        print("  분석기: 기존 재사용")
        return
    if resp.status_code == 410:
        print("  분석기: 410 Gone → 삭제 후 재생성")
        requests.delete(url, headers=_CU_BASE_HDR, timeout=30)
        resp2 = requests.put(url, headers=_CU_JSON_HDR, json=body, timeout=60)
        if resp2.status_code not in (200, 201, 409):
            print(f"  [ERROR] {resp2.status_code}: {resp2.text[:1000]}")
            resp2.raise_for_status()
        print("  분석기: 재생성 완료")
    else:
        print(f"  [ERROR] {resp.status_code}: {resp.text[:1000]}")
        resp.raise_for_status()


def _cu_submit(pdf_path: str) -> str:
    url  = f"{_CU_ENDPOINT}/contentunderstanding/analyzers/{_CU_ANALYZER_ID}:analyze?api-version={_CU_API_VER}"
    b64  = base64.b64encode(Path(pdf_path).read_bytes()).decode()
    body = {"inputs": [{"data": b64}]}
    resp = requests.post(url, headers=_CU_JSON_HDR, json=body, timeout=120)
    if not resp.ok:
        print(f"  [ERROR] {resp.status_code}: {resp.text[:1000]}")
    resp.raise_for_status()
    result_url = resp.headers.get("Operation-Location")
    if not result_url:
        raise RuntimeError(f"Operation-Location 헤더 없음: {dict(resp.headers)}")
    return result_url


def _cu_poll(result_url: str, timeout: int = 900) -> dict:
    start = time.time()
    while time.time() - start < timeout:
        resp    = requests.get(result_url, headers=_CU_BASE_HDR, timeout=30)
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


def step2_extract_cu(pdf_path: str, out_dir: Path, debug: bool = False) -> dict:
    """CU API로 PDF 분석. 캐시가 있으면 재사용. Returns: raw_response dict."""
    if not _CU_ENDPOINT or not _CU_KEY:
        raise RuntimeError(
            "환경변수 CONTENT_UNDERSTANDING_ENDPOINT / CONTENT_UNDERSTANDING_KEY 미설정"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    cached = _cu_find_cached_raw(pdf_path, out_dir)
    if cached:
        print(f"[STEP 2-CU] 캐시 재사용 → {cached}")
        data = json.loads(cached.read_text(encoding="utf-8"))
        dest = out_dir / "raw_response.json"
        if dest != cached:
            dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    print("[STEP 2-CU] Azure API 호출 중...")
    _cu_ensure_analyzer()
    result_url = _cu_submit(pdf_path)
    data = _cu_poll(result_url)

    (out_dir / "raw_response.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    contents  = data.get("result", {}).get("contents", [])
    fig_count = sum(len(c.get("figures", [])) for c in contents)
    print(f"[STEP 2-CU] 콘텐츠 블록 {len(contents)}개, figure {fig_count}개 감지 완료")
    return data


# ---------------------------------------------------------------------------
# STEP 2-MU — PyMuPDF 추출  (디지털 PDF)
# ---------------------------------------------------------------------------

def step2_extract_mu(pdf_path: str, out_dir: Path, debug: bool = False) -> list[dict]:
    """
    디지털 PDF에서 텍스트와 이미지 블록을 추출한다.

    Returns: figures 리스트 (figures.json 스키마)
    """
    img_dir = out_dir / "img"
    txt_dir = out_dir / "txt"
    img_dir.mkdir(parents=True, exist_ok=True)
    txt_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    mat = fitz.Matrix(_MU_SCALE, _MU_SCALE)

    text_pages: list[str] = []
    figures: list[dict] = []
    page_img_count: dict[int, int] = {}

    for page_num, page in enumerate(doc):
        page_no = page_num + 1
        blocks = page.get_text("dict")["blocks"]

        # 텍스트 수집
        page_texts = []
        for b in blocks:
            if b["type"] != 0:
                continue
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    t = span.get("text", "").strip()
                    if t:
                        page_texts.append(t)
        text_pages.append(f"[page{page_no}]\n{' '.join(page_texts)}")

        # 이미지 블록 크롭
        img_blocks = [b for b in blocks if b["type"] == 1]
        if not img_blocks:
            continue

        pix = page.get_pixmap(matrix=mat)
        page_img = Image.open(io.BytesIO(pix.tobytes("png")))

        for block in img_blocks:
            x0, y0, x1, y1 = [int(v * _MU_SCALE) for v in block["bbox"]]
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(pix.width, x1), min(pix.height, y1)
            if x1 <= x0 or y1 <= y0:
                continue

            idx = page_img_count.get(page_no, 0) + 1
            page_img_count[page_no] = idx

            img_filename = f"fig_{page_no}_{idx}.png"
            page_img.crop((x0, y0, x1, y1)).save(str(img_dir / img_filename))

            figures.append({
                "id": f"{page_no}.{idx}",
                "page": page_no,
                "bbox": [int(v) for v in block["bbox"]],
                "img_path": str(Path("img") / img_filename),
                "caption": "",
                "false_positive_type": None,
                "sub_crops": [],
            })

    doc.close()

    (txt_dir / "content_raw.txt").write_text(
        "\n\n".join(text_pages), encoding="utf-8"
    )

    if debug:
        meta_dir = out_dir / "meta"
        meta_dir.mkdir(exist_ok=True)
        (meta_dir / "figures.json").write_text(
            json.dumps(figures, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(f"[STEP 2-MU] 텍스트 {len(text_pages)}페이지, 이미지 {len(figures)}개 추출 완료")
    return figures


# ---------------------------------------------------------------------------
# STEP 3-CU — 이미지 / 텍스트 / 캡션 분리  (CU 경로 전용)
# ---------------------------------------------------------------------------

def _parse_source(source: str) -> list[dict]:
    regions = []
    for m in re.finditer(r"D\((\d+),([\d.,]+)\)", source):
        page = int(m.group(1))
        coords = [float(v) for v in m.group(2).split(",")]
        xs, ys = coords[0::2], coords[1::2]
        regions.append({"page": page, "bbox": [min(xs), min(ys), max(xs), max(ys)]})
    return regions


def _inch_to_px(bbox_inch: list[float], scale: float) -> list[int]:
    dpi = 72.0 * scale
    return [int(v * dpi) for v in bbox_inch]


def _insert_page_markers(text: str) -> str:
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


_CAPTION_INLINE_PAT = re.compile(
    r"^(그림\s*\d+[\.\s]|Figure\s*\d+[\.\s])|(\|.*\|.{0,100})$",
    re.MULTILINE | re.IGNORECASE,
)


def step3_parse_cu(raw_response: dict, pdf_path: str, out_dir: Path, debug: bool = False) -> list[dict]:
    """raw_response.json → 이미지 크롭 + content_raw.txt + 캡션 분리."""
    img_dir = out_dir / "img"
    txt_dir = out_dir / "txt"
    img_dir.mkdir(parents=True, exist_ok=True)
    txt_dir.mkdir(parents=True, exist_ok=True)

    # 1. 이미지 크롭
    raw_figs = []
    for content in raw_response.get("result", {}).get("contents", []):
        raw_figs.extend(content.get("figures", []))
        for page in content.get("pages", []):
            raw_figs.extend(page.get("figures", []))

    doc = fitz.open(pdf_path)
    page_cache: dict[int, Image.Image] = {}
    figures: list[dict] = []
    page_img_count: dict[int, int] = {}

    for raw_fig in raw_figs:
        regions = _parse_source(raw_fig.get("source", ""))
        if not regions:
            continue
        r = regions[0]
        page_no, page_idx = r["page"], r["page"] - 1
        if page_idx < 0 or page_idx >= len(doc):
            continue
        if page_idx not in page_cache:
            pix = doc[page_idx].get_pixmap(matrix=fitz.Matrix(_CU_SCALE, _CU_SCALE))
            page_cache[page_idx] = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        pil_img = page_cache[page_idx]
        bbox_px = _inch_to_px(r["bbox"], _CU_SCALE)
        area = (bbox_px[2] - bbox_px[0]) * (bbox_px[3] - bbox_px[1])
        if area < _MIN_AREA_PX:
            continue
        idx = page_img_count.get(page_no, 0) + 1
        page_img_count[page_no] = idx
        img_filename = f"fig_{page_no}_{idx}.png"
        x0, y0, x1, y1 = bbox_px
        w, h = pil_img.size
        pil_img.crop((max(0, x0), max(0, y0), min(w, x1), min(h, y1))).save(img_dir / img_filename)

        cap_raw = raw_fig.get("caption") or ""
        if isinstance(cap_raw, dict):
            cap_raw = cap_raw.get("content", "")

        figures.append({
            "id": raw_fig.get("id", ""),
            "page": page_no,
            "bbox_inch": r["bbox"],
            "img_path": str(Path("img") / img_filename),
            "caption": cap_raw.strip(),
            "false_positive_type": None,
            "sub_crops": [],
        })

    doc.close()
    print(f"[STEP 3-CU] 이미지 {len(figures)}개 크롭 완료")

    # 2. 본문 텍스트
    contents = raw_response.get("result", {}).get("contents", [])
    md_parts = [c.get("markdown") or c.get("markdownContent", "") for c in contents]
    full_md = "\n\n".join(p for p in md_parts if p)

    # figcaption 수집 (텍스트 정제 전)
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

    body = _clean_markdown(full_md)
    inline_caps: list[str] = []

    def _capture(m):
        inline_caps.append(m.group(0).strip())
        return ""

    body = _CAPTION_INLINE_PAT.sub(_capture, body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    (txt_dir / "content_raw.txt").write_text(body, encoding="utf-8")
    print(f"[STEP 3-CU] content_raw.txt 저장 ({len(body):,}자)")

    if debug:
        (txt_dir / "content_raw.md").write_text(full_md, encoding="utf-8")
        caption_lines = [f"[page{c['page']}] {c['text']}" for c in figcaption_list]
        caption_lines += [f"[inline] {t}" for t in inline_caps if t]
        (txt_dir / "caption_raw.txt").write_text("\n".join(caption_lines), encoding="utf-8")
        meta_dir = out_dir / "meta"
        meta_dir.mkdir(exist_ok=True)
        (meta_dir / "figures.json").write_text(
            json.dumps(figures, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[STEP 3-CU] debug 파일 저장 완료")

    # figcaption으로 figures caption 보완 (순서 기반)
    for i, fig in enumerate(figures):
        if not fig["caption"] and i < len(figcaption_list):
            fig["caption"] = figcaption_list[i]["text"]

    return figures


# ---------------------------------------------------------------------------
# STEP 4 — OpenCV 이미지 후처리  (CU 경로 전용)
# ---------------------------------------------------------------------------

def step4_cv_refine(figures: list, out_dir: Path) -> list:
    raise NotImplementedError("STEP 4 미구현")


# ---------------------------------------------------------------------------
# STEP 5 — LLM 정제 및 목차 추출
# ---------------------------------------------------------------------------

_OAI_ENDPOINT = os.environ.get("OPEN_AI_ENDPOINT", "").rstrip("/")
_OAI_KEY      = os.environ.get("OPEN_AI_KEY", "")
_OAI_MINI     = os.environ.get("OPEN_AI_DEPLOYMENT_NAME_4.1_MINI", "")
_OAI_4O       = os.environ.get("OPEN_AI_DEPLOYMENT_NAME_4O", "")
_OAI_API_VER  = "2024-10-21"
_TEXT_CHUNK_MAX = 40_000
# Refine output is ~1:1 with input; a 40K-char chunk under a 4096-token cap
# truncated the tail (lost ~80% on large docs). Chunk by TOKENS (same encoding
# graphrag indexes with) so the cleaned output always fits well under the cap,
# and _oai_chat raises on any length-truncation so loss can never be silent.
_REFINE_ENC = tiktoken.get_encoding("o200k_base")
_REFINE_CHUNK_TOKENS = 6_000   # input tokens/chunk; refined output (~<=input) << cap
_REFINE_MAX_TOKENS = 16_384    # gpt-4.1-mini output cap; ~2.7x the chunk budget


class _Truncated(RuntimeError):
    """LLM 출력이 max_tokens에서 잘림 -> refine이 청크를 더 쪼개 재시도."""


def _oai_chat(messages: list[dict], deployment: str, max_tokens: int = 4096) -> str:
    url = f"{_OAI_ENDPOINT}/openai/deployments/{deployment}/chat/completions?api-version={_OAI_API_VER}"
    resp = requests.post(
        url,
        headers={"api-key": _OAI_KEY, "Content-Type": "application/json"},
        json={"messages": messages, "max_tokens": max_tokens},
        timeout=120,
    )
    if not resp.ok:
        print(f"  [LLM ERROR] {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    choice = resp.json()["choices"][0]
    if choice.get("finish_reason") == "length":
        # Output hit max_tokens = the tail was dropped. Never accept it silently;
        # the refine path catches this and re-splits the chunk (see _refine_one).
        raise _Truncated(f"output truncated at max_tokens={max_tokens}")
    return choice["message"]["content"].strip()


def _split_chunks(text: str) -> list[str]:
    """[pageN] 경계 기준으로 refine 토큰 상한(_REFINE_CHUNK_TOKENS) 이하로 분할."""
    def ntok(s: str) -> int:
        return len(_REFINE_ENC.encode(s))

    if ntok(text) <= _REFINE_CHUNK_TOKENS:
        return [text]
    parts = re.split(r"(\[page\d+\])", text)
    chunks, cur, cur_tok = [], "", 0
    for part in parts:
        ptok = ntok(part)
        if cur_tok + ptok > _REFINE_CHUNK_TOKENS and cur:
            chunks.append(cur)
            cur, cur_tok = part, ptok
        else:
            cur += part
            cur_tok += ptok
    if cur:
        chunks.append(cur)
    return chunks


_REFINE_SYS = (
    "당신은 한국어 교육 문서 편집 전문가입니다. "
    "LaTeX 수식 오류, OCR 잡음, 불필요한 특수문자를 교정하고 "
    "자연스러운 문장 흐름으로 정리하세요. "
    "[pageN] 마커는 반드시 원본 위치 그대로 유지하세요. 내용은 변경하지 마세요."
)


def _halve(text: str) -> tuple[str, str]:
    """중앙에 가장 가까운 [pageN] 경계에서 분할(없으면 글자 중앙). 페이지 마커 보존."""
    mid = len(text) // 2
    marks = [m.start() for m in re.finditer(r"\[page\d+\]", text) if 0 < m.start() < len(text)]
    cut = min(marks, key=lambda p: abs(p - mid)) if marks else mid
    return text[:cut], text[cut:]


def _refine_one(chunk: str, depth: int = 0) -> str:
    """청크 1개 정제. 모델이 잘리면(_Truncated) 절반으로 쪼개 재귀 재시도 = 손실 0."""
    msgs = [
        {"role": "system", "content": _REFINE_SYS},
        {"role": "user", "content": f"아래 텍스트를 정제해 주세요.\n\n{chunk}"},
    ]
    try:
        return _oai_chat(msgs, _OAI_MINI, max_tokens=_REFINE_MAX_TOKENS)
    except _Truncated:
        a, b = _halve(chunk)
        if depth >= 8 or not a.strip() or not b.strip():
            raise  # 더 못 쪼갬: 조용히 잃느니 명시적 실패
        print(f"    [잘림 감지 -> 절반 분할 재시도 depth={depth + 1}]")
        return _refine_one(a, depth + 1) + "\n\n" + _refine_one(b, depth + 1)


def _refine_body(raw_text: str) -> str:
    """본문 텍스트 정제. [pageN] 마커 유지. 토큰 청킹 + 잘림 시 자동 재분할."""
    chunks = _split_chunks(raw_text)
    refined = []
    for i, chunk in enumerate(chunks, 1):
        print(f"  청크 {i}/{len(chunks)} ({len(chunk):,}자)")
        refined.append(_refine_one(chunk))
    return "\n\n".join(refined)


def _refine_caption(caption_text: str) -> str:
    msgs = [
        {
            "role": "system",
            "content": (
                "당신은 한국어 교육 자료의 캡션을 교정하는 전문가입니다. "
                "불완전한 캡션을 보완하고 OCR 오류를 교정하세요. "
                "교정 불가하면 원본 그대로 반환하세요."
            ),
        },
        {"role": "user", "content": f"다음 캡션을 교정해 주세요.\n\n{caption_text}"},
    ]
    return _oai_chat(msgs, _OAI_MINI, max_tokens=256)


def _generate_caption(img_path: Path) -> str:
    b64 = base64.b64encode(img_path.read_bytes()).decode()
    msgs = [
        {"role": "system", "content": "당신은 교육 자료의 이미지를 설명하는 전문가입니다."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "아래 이미지의 내용을 간결하게 설명하는 캡션을 한 문장으로 작성해 주세요."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        },
    ]
    return _oai_chat(msgs, _OAI_4O, max_tokens=256)


def step5_llm(out_dir: Path, is_scan: bool, figures: list[dict], debug: bool = False) -> list[dict]:
    """LLM 정제 및 목차 추출. Returns: caption이 채워진 figures 리스트."""
    if not _OAI_ENDPOINT or not _OAI_KEY:
        raise RuntimeError("환경변수 OPEN_AI_ENDPOINT / OPEN_AI_KEY 미설정")

    txt_dir = out_dir / "txt"
    txt_dir.mkdir(exist_ok=True)

    # ── 5-1. 본문 텍스트 정제 ────────────────────────────────────────────────
    raw_path = txt_dir / "content_raw.txt"
    if not raw_path.exists():
        raise FileNotFoundError(f"content_raw.txt 없음: {raw_path}")

    raw_text = raw_path.read_text(encoding="utf-8")
    print(f"[STEP 5-1] 본문 정제 시작 ({len(raw_text):,}자)")

    content_paged = _refine_body(raw_text)
    content_pure  = re.sub(r"\n{3,}", "\n\n", re.sub(r"\[page\d+\]", "", content_paged)).strip()

    (txt_dir / "content_paged.txt").write_text(content_paged, encoding="utf-8")
    (txt_dir / "content.txt").write_text(content_pure, encoding="utf-8")
    print(f"[STEP 5-1] content.txt / content_paged.txt 저장 완료")

    # ── 5-2. 캡션 정제 / 생성 ────────────────────────────────────────────────
    print(f"[STEP 5-2] 캡션 처리 시작 ({len(figures)}개)")
    caption_lines = []

    for fig in figures:
        page    = fig.get("page", 0)
        raw_cap = fig.get("caption", "").strip()

        if is_scan:
            refined = _refine_caption(raw_cap) if raw_cap else ""
        else:
            img_path = out_dir / fig.get("img_path", "")
            refined  = _generate_caption(img_path) if img_path.exists() else ""

        fig["caption"] = refined
        if refined:
            caption_lines.append(f"[page{page}] {refined}")

    (txt_dir / "caption.txt").write_text("\n".join(caption_lines), encoding="utf-8")
    print(f"[STEP 5-2] caption.txt 저장 완료 ({len(caption_lines)}개)")

    # ── 5-3. 목차 추출 ───────────────────────────────────────────────────────
    print("[STEP 5-3] 목차 추출 시작")
    toc_input = content_pure[:_TEXT_CHUNK_MAX]
    msgs = [
        {
            "role": "system",
            "content": "당신은 한국어 교육 문서를 분석하는 전문가입니다. 주어진 텍스트에서 문서의 핵심 목차 항목을 추출하세요.",
        },
        {
            "role": "user",
            "content": (
                "이 문서의 목차 항목을 5개에서 10개 사이로 추출해 주세요. "
                "번호와 제목만 간결하게 작성해 주세요.\n\n" + toc_input
            ),
        },
    ]
    toc = _oai_chat(msgs, _OAI_MINI, max_tokens=512)
    (txt_dir / "toc.txt").write_text(toc, encoding="utf-8")
    print("[STEP 5-3] toc.txt 저장 완료")

    return figures


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
    (out / "img").mkdir(parents=True)
    (out / "txt").mkdir(parents=True)
    return out


# ---------------------------------------------------------------------------
# 실행 로그 저장
# ---------------------------------------------------------------------------

def _write_run_log(out_dir: Path, pdf_path: str, is_scan: bool, timings: dict, figures: list[dict], notes: list[str]) -> None:
    from datetime import date

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

def main():
    parser = argparse.ArgumentParser(description="전처리 파이프라인 v2")
    parser.add_argument("--pdf", required=True, help="입력 PDF 경로")
    parser.add_argument("--scan", action="store_true", help="스캔 PDF로 강제 지정")
    parser.add_argument("--debug", action="store_true", help="중간 파일 저장")
    args = parser.parse_args()

    pdf_path = args.pdf
    timings: dict[str, float | None] = {}
    notes: list[str] = []

    # STEP 1
    t = time.time()
    step1 = detect_scan(pdf_path, force_scan=args.scan)
    timings["STEP 1 스캔 판별"] = time.time() - t
    print(f"[STEP 1] {step1['reason']}")

    out_dir = _make_out_dir(pdf_path)
    print(f"[OUT]    {out_dir}")

    if step1["is_scan"]:
        t = time.time()
        raw = step2_extract_cu(pdf_path, out_dir, debug=args.debug)
        timings["STEP 2-CU API 추출"] = time.time() - t

        t = time.time()
        figures = step3_parse_cu(raw, pdf_path, out_dir, debug=args.debug)
        timings["STEP 3-CU 분리"] = time.time() - t

        timings["STEP 4 OpenCV 후처리"] = None
        notes.append("STEP 4 미구현, 건너뜀")
    else:
        t = time.time()
        figures = step2_extract_mu(pdf_path, out_dir, debug=args.debug)
        timings["STEP 2-MU 추출"] = time.time() - t

        timings["STEP 3-CU 분리"] = None
        timings["STEP 4 OpenCV 후처리"] = None
        notes.append("STEP 3/4 미적용 (디지털 경로)")

    t = time.time()
    figures = step5_llm(out_dir, is_scan=step1["is_scan"], figures=figures, debug=args.debug)
    elapsed5 = time.time() - t
    timings["STEP 5-1 본문 정제"] = None   # step5 내부에서 세분화 불가 (통합 측정)
    timings["STEP 5-2 캡션 처리"] = None
    timings["STEP 5-3 목차 추출"] = None
    timings["STEP 5 LLM 전체"] = elapsed5

    _write_run_log(out_dir, pdf_path, step1["is_scan"], timings, figures, notes)

    total = sum(v for v in timings.values() if v is not None)
    print(f"[DONE]   파이프라인 완료 (총 {total:.1f}s)")


if __name__ == "__main__":
    main()
