"""
STEP 5 — LLM 정제 및 목차 추출

실행:
    python step5_llm.py --out "../result/test_v1" --scan
    python step5_llm.py --out "../result/test_v1"
    python step5_llm.py --out "../result/test_v1" --debug
"""

import argparse
import base64
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

_OAI_ENDPOINT = os.environ.get("OPEN_AI_ENDPOINT", "").rstrip("/")
_OAI_KEY      = os.environ.get("OPEN_AI_KEY", "")
_OAI_MINI     = (os.environ.get("OPEN_AI_DEPLOYMENT_NAME_4_1_MINI")  # Azure Linux App Service 는 env 이름의 '.' 를 못 넘김 -> '_' 형 우선
                 or os.environ.get("OPEN_AI_DEPLOYMENT_NAME_4.1_MINI", ""))  # 로컬 .env(점 이름) 폴백
_OAI_4O       = os.environ.get("OPEN_AI_DEPLOYMENT_NAME_4O", "")
_OAI_API_VER  = "2024-10-21"
_TEXT_CHUNK_MAX = 12_000
_BODY_MAX_TOKENS = 8192
_MAX_WORKERS = int(os.environ.get("OAI_MAX_WORKERS", "6"))  # 동시 LLM 요청 수 (429 나면 줄이기)


def _oai_chat(messages: list[dict], deployment: str, max_tokens: int = 4096,
              temperature: float | None = None) -> str:
    url = f"{_OAI_ENDPOINT}/openai/deployments/{deployment}/chat/completions?api-version={_OAI_API_VER}"
    payload = {"messages": messages, "max_tokens": max_tokens}
    if temperature is not None:
        payload["temperature"] = temperature
    resp = requests.post(
        url,
        headers={"api-key": _OAI_KEY, "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    if not resp.ok:
        print(f"  [LLM ERROR] {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _parallel_map(fn, items: list, label: str = "작업") -> list:
    """fn을 입력 순서를 보존하며 병렬 실행한다 (결과 순서 = 입력 순서)."""
    items = list(items)
    n = len(items)
    if n == 0:
        return []
    workers = min(_MAX_WORKERS, n)
    done = 0
    lock = threading.Lock()

    def _wrapped(item):
        nonlocal done
        result = fn(item)
        with lock:
            done += 1
            print(f"  {label} {done}/{n} 완료", end="\r", flush=True)
        return result

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(_wrapped, items))  # map은 입력 순서대로 결과 반환
    print()
    return results


_BODY_SYSTEM_PROMPT = (
    "당신은 한국어 교육 문서 편집 전문가입니다. "
    "PDF에서 추출된 텍스트의 OCR 잡음과 깨진 글자, 불필요한 특수문자를 교정하여 "
    "GraphRAG 입력용 깨끗한 텍스트로 정리하세요.\n"
    "\n"
    "[수식 처리]\n"
    "- 깨지거나 줄마다 끊긴 수식(예: 'σ2 = 1 / N Σ / N / (xi−μ)2')을 "
    "한 줄의 유니코드 평문 수식으로 복원하세요.\n"
    "- LaTeX 명령(\\frac, \\sum, \\sigma, \\[ \\] 등)이나 $ 기호를 쓰지 말고, "
    "유니코드 기호로 표기하세요: 위첨자 ²³ⁿ, 아래첨자 ₁₂ᵢ, 그리스문자 σ μ Σ √, 분수는 (분자)/(분모).\n"
    "- 예시: 'σ² = (1/N) Σᵢ₌₁ᴺ (xᵢ − μ)²', 'σ = √( (1/N) Σᵢ₌₁ᴺ (xᵢ − μ)² )'\n"
    "\n"
    "[줄바꿈 처리]\n"
    "- 한 문장이 여러 줄로 끊긴 경우(예: '...데이터 기반 의사\\n결정을 지원') "
    "공백으로 이어붙여 한 문장으로 만드세요.\n"
    "- 단, 문단 구분, 글머리표(•, -)·번호 목록, 표(| ... |) 행의 줄바꿈은 그대로 보존하세요.\n"
    "\n"
    "[규칙]\n"
    "- 내용(의미)은 추가·삭제·요약하지 말고, 표기와 형식만 정리하세요.\n"
    "- [pageN] 같은 페이지 마커는 입력에 없습니다. 임의로 만들지 마세요."
)


def _split_by_size(text: str) -> list[str]:
    """한 페이지가 출력 토큰 한계를 넘을 만큼 클 때 문단(빈 줄) 단위로 분할."""
    if len(text) <= _TEXT_CHUNK_MAX:
        return [text]
    parts = re.split(r"(\n{2,})", text)
    chunks, cur = [], ""
    for part in parts:
        if len(cur) + len(part) > _TEXT_CHUNK_MAX and cur:
            chunks.append(cur)
            cur = part
        else:
            cur += part
    if cur:
        chunks.append(cur)
    return chunks


def _refine_text(text: str) -> str:
    """마커가 제거된 순수 본문 텍스트를 정제한다."""
    refined = []
    for sub in _split_by_size(text):
        msgs = [
            {"role": "system", "content": _BODY_SYSTEM_PROMPT},
            {"role": "user", "content": f"아래 텍스트를 정제해 주세요.\n\n{sub}"},
        ]
        refined.append(_oai_chat(msgs, _OAI_MINI, max_tokens=_BODY_MAX_TOKENS))
    return "\n\n".join(refined)


def _refine_body(raw_text: str) -> str:
    """페이지([pageN]) 단위로 정제하고 마커는 코드에서 재부착해 100% 보존한다."""
    # parts: [선두본문, '[page2]', 본문, '[page3]', 본문, ...]
    parts = re.split(r"(\[page\d+\])", raw_text)

    # (marker, body) 세그먼트 구성. 첫 마커 이전 선두 본문은 marker=None.
    segments: list[tuple[str | None, str]] = []
    if parts[0].strip():
        segments.append((None, parts[0]))
    for i in range(1, len(parts), 2):
        marker = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        segments.append((marker, body))

    def _process(seg: tuple[str | None, str]) -> str | None:
        marker, body = seg
        refined_body = _refine_text(body) if body.strip() else ""
        if marker:
            return f"{marker}\n{refined_body}".rstrip()  # 본문이 비어도 마커는 보존
        return refined_body or None

    # 페이지 세그먼트는 서로 독립 → 병렬 처리. 결과는 입력 순서대로 모여 마커 순서 보존.
    refined_parts = _parallel_map(_process, segments, label="페이지")
    return "\n\n".join(p for p in refined_parts if p)


_BAR_RE = re.compile(r"\s*[|￨ㅣ]\s*")  # ASCII bar, halfwidth bar, hangul I
_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")
# 종결어미/문장부호로 끝나거나 길면 '설명형'(제목 없음), 아니면 '제목형'으로 본다.
# 새 글자를 만들지 않고 원문 텍스트를 어느 칸에 넣을지만 결정한다(날조 금지).
_SENTENCE_END_RE = re.compile(r"(?:다|음|함|임|됨|요|이다|지도|문서)\.?$|[.。!?]$")


def _looks_like_sentence(text: str) -> bool:
    return len(text) > 30 or bool(_SENTENCE_END_RE.search(text))


def _split_printed_caption(text: str) -> tuple[str, str]:
    """인쇄/전사 캡션을 (caption_title, caption)으로 가른다. 원문 보존 원칙:
    caption 은 항상 원문 본문(임베딩·표시용)을 그대로 들고, caption_title 은 '확실히
    아는 제목'일 때만 채운다. 새 단어를 만들지 않는다(있는 글자를 어느 칸에 넣을지만 결정).
      - '|' 있음        -> 앞=title, caption=원문 전체(구분자 포함 보존)
      - '|' 없음 + 문장   -> title='' , caption=원문 전체
      - '|' 없음 + 명사구 -> title=끝괄호(소장처 등 메타) 제거한 명사구, caption=원문 전체
    """
    text = " ".join(text.split())
    if not text:
        return "", ""
    if _BAR_RE.search(text):
        return _BAR_RE.split(text, 1)[0].strip(), text
    if _looks_like_sentence(text):
        return "", text
    return _TRAILING_PAREN_RE.sub("", text).strip(), text


def _parse_caption_json(raw: str) -> dict:
    """이미지 생성 캡션의 JSON 응답을 파싱한다. 코드펜스/주변 잡텍스트를 관대하게 벗기고,
    실패하면 전체를 설명(caption)으로 폴백한다(제목 없음)."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s.split("\n", 1)[1] if "\n" in s else s
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if m:
        s = m.group(0)
    try:
        d = json.loads(s)
        return {
            "caption_title": " ".join(str(d.get("caption_title", "")).split()),
            "caption": " ".join(str(d.get("caption", "")).split()),
        }
    except (json.JSONDecodeError, AttributeError, TypeError):
        return {"caption_title": "", "caption": " ".join(raw.split())}


def _refine_caption(caption_text: str) -> str:
    msgs = [
        {
            "role": "system",
            "content": (
                "당신은 한국어 캡션의 띄어쓰기와 명백한 오탈자만 교정하는 교정기입니다. "
                "원문에 충실해야 하며 다음을 반드시 지키세요.\n"
                "- 잘못된 띄어쓰기(예: '교실이 었다'→'교실이었다', '땀흘려 일 하는'→'땀 흘려 일하는')와 "
                "명백한 오탈자만 고치세요.\n"
                "- 문장을 재서술·요약·축약·완성하지 말고, 말투나 표현을 바꾸지 마세요. "
                "(예: '청의'를 '청나라'로, '가졌는데'를 '겸하였으며'로 바꾸지 말 것)\n"
                "- 단어를 새로 추가하거나(예: '영정'→'영정 사진') 내용을 지어내지 마세요. "
                "끊기거나 깨진 부분도 추측해 채우지 말고 그대로 두세요.\n"
                "- 어떤 글자도 삭제하지 마세요. 특히 캡션 뒤의 설명 문장을 절대 지우지 마세요.\n"
                "- 단, 문장 조각의 순서가 뒤바뀌어 있으면(문장 끝부분이 중간보다 앞에 온 경우) "
                "이미 있는 조각들의 순서만 바로잡아 자연스러운 한 문장으로 이어 붙이세요. "
                "이때도 단어를 바꾸거나 추가·삭제하지 말고 있는 글자만 재배열하세요. "
                "(예: '경남 진주 아 주는 역할을 하였다. 임진왜란 때 왜군의 호남 진출을 막' "
                "→ '경남 진주 임진왜란 때 왜군의 호남 진출을 막아 주는 역할을 하였다.')\n"
                "- 고칠 것이 없으면 원문을 그대로 반환하고, 결과 텍스트만 출력하세요."
            ),
        },
        {"role": "user", "content": f"다음 캡션을 교정해 주세요(띄어쓰기·오탈자, 그리고 순서가 뒤바뀐 조각의 재배열만).\n\n{caption_text}"},
    ]
    return _oai_chat(msgs, _OAI_MINI, max_tokens=256, temperature=0)


_MATH_RULE = (
    " 수식이 있으면 LaTeX 명령이나 $ 기호를 쓰지 말고 유니코드 평문으로 표기하세요"
    " (위첨자 ²³ⁿ, 아래첨자 ₁₂ᵢ, 그리스문자 σ μ Σ √, 분수는 (분자)/(분모))."
)


def _generate_caption(img_path: Path, math_unicode: bool = False) -> dict:
    """이미지를 보고 캡션을 생성한다. {caption_title, caption} 둘 다 반환한다.

    원문 캡션이 없어 LLM이 저자가 되는 경로이므로 제목(명사구)과 설명(한 문장)을 모두
    채운다. math_unicode=True면 수식을 LaTeX 대신 유니코드 평문으로 표기하도록 지시한다
    (디지털 경로 전용, 스캔 경로엔 적용하지 않아 결과 변화를 막는다).
    """
    b64 = base64.b64encode(img_path.read_bytes()).decode()
    prompt = (
        "아래 이미지를 설명하는 캡션을 만들어 JSON 객체 하나로만 답하세요. "
        '형식: {"caption_title": "...", "caption": "..."}. '
        "caption_title 은 이미지의 핵심 대상을 가리키는 짧은 제목(명사구, 5어절 이내), "
        "caption 은 이미지 내용을 설명하는 한 문장입니다. 두 필드를 모두 반드시 채우세요."
    )
    if math_unicode:
        prompt += _MATH_RULE
    msgs = [
        {"role": "system", "content": "당신은 교육 자료의 이미지를 설명하는 전문가입니다. JSON 으로만 답합니다."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        },
    ]
    return _parse_caption_json(_oai_chat(msgs, _OAI_4O, max_tokens=256))


def step5_llm(out_dir: Path, is_scan: bool, figures: list[dict], debug: bool = False) -> list[dict]:
    if not _OAI_ENDPOINT or not _OAI_KEY:
        raise RuntimeError("환경변수 OPEN_AI_ENDPOINT / OPEN_AI_KEY 미설정")

    txt_dir = out_dir / "txt"
    txt_dir.mkdir(exist_ok=True)

    # 5-1. 본문 텍스트 정제
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

    # 5-2. 캡션 정제 / 생성
    print(f"[STEP 5-2] 캡션 처리 시작 ({len(figures)}개)")

    def _process_caption(fig: dict) -> tuple[str, str, str]:
        """(caption_title, caption, caption_source) 반환. 출처별 정책:
        원문(인쇄/전사)이면 보존하며 분리하고, 이미지 생성이면 제목+설명을 둘 다 만든다.
        caption 은 항상 임베딩 가능한 본문을 유지하고(빈 caption 은 매칭 자동 미배치),
        caption_title 은 확실히 아는 제목일 때만 채운다. 캡션 내부 줄바꿈/연속 공백은
        단일 공백으로 정규화한다(한 줄 캡션)."""
        raw_cap = " ".join(fig.get("caption", "").split())
        # STEP 4 vision 전사 캡션: 원문으로 취급해 보존 분리.
        if fig.get("caption_done"):
            t, c = _split_printed_caption(raw_cap)
            return t, c, "vision"
        if is_scan:
            # 인쇄 캡션 있으면 교정 후 보존 분리, 없으면 이미지로 생성(제목+설명, 수식 규칙 X).
            if raw_cap:
                t, c = _split_printed_caption(_refine_caption(raw_cap))
                return t, c, "printed"
            img_path = out_dir / fig.get("img_path", "")
            if img_path.exists():
                g = _generate_caption(img_path)
                return g["caption_title"], g["caption"], "generated"
            return "", "", "none"
        # 디지털 경로: 항상 이미지 생성(수식 유니코드 표기), 제목+설명 둘 다.
        img_path = out_dir / fig.get("img_path", "")
        if img_path.exists():
            g = _generate_caption(img_path, math_unicode=True)
            return g["caption_title"], g["caption"], "generated"
        return "", "", "none"

    # 캡션들도 서로 독립 → 병렬 처리. 결과는 figures 순서대로 모임.
    processed = _parallel_map(_process_caption, figures, label="캡션")

    caption_lines: list[str] = []
    caption_records: list[dict] = []
    for fig, (title, cap, source) in zip(figures, processed):
        fig["caption_title"] = title
        fig["caption"] = cap
        fig["caption_source"] = source
        if not cap:
            continue
        page = fig.get("page", 0)
        # 일관 표기 "[pageN] 제목 | 설명". 제목이 caption 본문에 이미 들어 있으면(인쇄 '|'
        # 보존/명사구) 중복을 피해 caption 그대로 쓴다.
        if title and title not in cap:
            caption_lines.append(f"[page{page}] {title} | {cap}")
        else:
            caption_lines.append(f"[page{page}] {cap}")
        caption_records.append({
            "page": page, "caption_title": title,
            "caption": cap, "caption_source": source,
        })

    (txt_dir / "caption.txt").write_text("\n".join(caption_lines), encoding="utf-8")
    (txt_dir / "caption.json").write_text(
        json.dumps(caption_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[STEP 5-2] caption.txt / caption.json 저장 완료 ({len(caption_lines)}개)")

    # 5-3. 목차 추출
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


def main():
    parser = argparse.ArgumentParser(description="STEP 5 — LLM 정제 및 목차 추출")
    parser.add_argument("--out",   required=True,        help="결과 디렉토리 (result/xxx_v1)")
    parser.add_argument("--scan",  action="store_true",  help="스캔 PDF 경로 (캡션 정제 모드)")
    parser.add_argument("--debug", action="store_true",  help="중간 파일 저장")
    args = parser.parse_args()

    out_dir = Path(args.out)
    if not out_dir.exists():
        print(f"[오류] 출력 디렉토리 없음: {out_dir}")
        sys.exit(1)

    # figures 로드 (debug 모드에서 저장된 figures.json 사용, 없으면 빈 리스트)
    figures_path = out_dir / "meta" / "figures.json"
    if figures_path.exists():
        figures = json.loads(figures_path.read_text(encoding="utf-8"))
        print(f"[STEP 5] figures.json 로드 ({len(figures)}개)")
    else:
        figures = []
        print("[STEP 5] figures.json 없음 → 캡션 처리 생략")

    figures = step5_llm(out_dir, is_scan=args.scan, figures=figures, debug=args.debug)

    print("\n--- 결과 요약 ---")
    print(f"출력: {out_dir / 'txt'}")
    print(f"캡션: {sum(1 for f in figures if f.get('caption'))}개")


if __name__ == "__main__":
    main()
