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
import json
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
        # 스캔 경로: (PII 마스킹) → CU 추출 → 파싱 → 이미지 후처리
        #
        # PII_MASK_SCAN=1(기본) 이면 CU 전송 전에 페이지를 마스킹한다. 로컬 OCR 로 PII
        # 위치를 찾아 검은 박스로 가린 masked.pdf 를 CU 로 보내고, STEP3 figure 크롭도
        # 같은 마스킹 페이지(같은 SCALE)에서 한다 → 외부(CU)와 그림 양쪽에 PII 없음.
        # 끄려면 PII_MASK_SCAN=0 (원본 그대로 CU 전송, 기존 동작).
        import os as _os

        mask_on = _os.environ.get("PII_MASK_SCAN", "1") != "0"
        masked_page_paths = None
        send_pdf = pdf_path
        if mask_on:
            from step2_premask import premask_pdf

            t = time.time()
            pre = premask_pdf(pdf_path, out_dir)
            masked_page_paths = pre["page_paths"]
            send_pdf = str(pre["masked_pdf"])  # CU 로는 마스킹본을 보낸다
            timings["STEP 2-PRE 마스킹"] = time.time() - t
            notes.append(
                f"PII 마스킹 ON: {pre['total_masked']}개 영역 가림 "
                f"(CU·그림 모두 마스킹본 사용)"
            )
        else:
            timings["STEP 2-PRE 마스킹"] = None
            notes.append("PII 마스킹 OFF (원본 그대로 CU 전송)")

        t = time.time()
        # 캐시키는 원본(pdf_path), 실제 업로드는 send_pdf(마스킹본).
        raw = step2_extract_cu(pdf_path, out_dir, debug=debug, send_pdf_path=send_pdf)
        timings["STEP 2-CU API 추출"] = time.time() - t

        t = time.time()
        figures = step3_parse_cu(
            raw, pdf_path, out_dir, debug=debug,
            masked_page_paths=masked_page_paths,  # 크롭도 마스킹 페이지에서
        )
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

    # PII 텍스트 스크럽 (STEP5=Azure LLM 전, 양쪽 경로 공통 — 방어 심층).
    #   디지털: 텍스트가 로컬 추출이라 마스킹 대상 이미지가 없다 → 추출 텍스트에서 PII
    #           구간을 제거해 GraphRAG/STEP5(Azure)로 PII 누출 차단(유일 차단 지점).
    #   스캔: premask 로 이미 이미지에서 제거됐지만, OCR 오인식으로 샌 PII 를 텍스트
    #         단계에서 한 번 더 거른다(안전망). 인물·지명은 KO_PII_EXCLUDE 로 보존.
    #   토큰을 안 남기고 *제거* 한다 → 스캔(검은박스=텍스트 부재)과 동일, 가짜 노드 0.
    from step2_premask import scrub_text_pii

    t = time.time()
    craw = out_dir / "txt" / "content_raw.txt"
    if craw.is_file():
        cleaned, n = scrub_text_pii(craw.read_text(encoding="utf-8"))
        craw.write_text(cleaned, encoding="utf-8")
        notes.append(f"PII 텍스트 스크럽: {n}건 제거(토큰 없음)")
    timings["STEP 4.5 PII 스크럽"] = time.time() - t

    # STEP 5 — LLM 정제·캡션·목차 (스캔 여부 전달)
    t = time.time()
    figures = step5_llm(out_dir, is_scan=step1["is_scan"], figures=figures, debug=debug)
    timings["STEP 5 LLM 전체"] = time.time() - t

    # meta/figures.json 을 최종 figures 로 다시 쓴다. step3/step2-MU 가 저장한 버전은
    # STEP4 분리(자식 _cv_ 추가·부모 폐기)와 STEP5 캡션 정제 전이라, 함수 호출 경로에선
    # 그걸 반영한 최종본을 아무도 저장하지 않았다(단독 실행 step4 만 저장). 다운스트림
    # (match_images)이 보는 단일 진실원본이므로 분리 자식 + 정제 캡션까지 담아 갱신한다.
    meta_dir = out_dir / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "figures.json").write_text(
        json.dumps(figures, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[META]   meta/figures.json 갱신 ({len(figures)}개, 최종)")

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
