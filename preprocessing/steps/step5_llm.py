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
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

_OAI_ENDPOINT = os.environ.get("OPEN_AI_ENDPOINT", "").rstrip("/")
_OAI_KEY      = os.environ.get("OPEN_AI_KEY", "")
_OAI_MINI     = os.environ.get("OPEN_AI_DEPLOYMENT_NAME_4.1_MINI", "")
_OAI_4O       = os.environ.get("OPEN_AI_DEPLOYMENT_NAME_4O", "")
_OAI_API_VER  = "2024-10-21"
_TEXT_CHUNK_MAX = 40_000


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
    return resp.json()["choices"][0]["message"]["content"].strip()


def _split_chunks(text: str) -> list[str]:
    if len(text) <= _TEXT_CHUNK_MAX:
        return [text]
    parts = re.split(r"(\[page\d+\])", text)
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


def _refine_body(raw_text: str) -> str:
    chunks = _split_chunks(raw_text)
    refined = []
    for i, chunk in enumerate(chunks, 1):
        print(f"  청크 {i}/{len(chunks)} ({len(chunk):,}자)")
        msgs = [
            {
                "role": "system",
                "content": (
                    "당신은 한국어 교육 문서 편집 전문가입니다. "
                    "LaTeX 수식 오류, OCR 잡음, 불필요한 특수문자를 교정하고 "
                    "자연스러운 문장 흐름으로 정리하세요. "
                    "[pageN] 마커는 반드시 원본 위치 그대로 유지하세요. 내용은 변경하지 마세요."
                ),
            },
            {"role": "user", "content": f"아래 텍스트를 정제해 주세요.\n\n{chunk}"},
        ]
        refined.append(_oai_chat(msgs, _OAI_MINI, max_tokens=4096))
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
