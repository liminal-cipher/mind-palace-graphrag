"""
STEP 4 — 이미지 후처리 (레이아웃 모델) — CU 경로 전용

STEP 3-CU가 크롭한 figure 이미지의 오탐을 doclayout-yolo로 정제한다.
crop 안에서 figure 객체를 검출해 개수로 분기한다:

  객체 0개 → 폐기 (파일 삭제 + figures에서 제거)
  객체 1개 → 해당 박스로 재크롭 (원본 덮어쓰기)
  객체 N개 → 각 박스를 독립 figure로 승격 분리 (부모 폐기)

면적비 게이트(area_thr): 게이트 미만 figure는 모델을 거치지 않고 그대로 통과한다
(= 게이트 아래는 폐기되지 않음). 채택안 B는 낮은 게이트(0.10)로 작은 잡동사니는
모델 호출을 건너뛰어 속도를 확보하고, 본문 멀티이미지·텍스트 페이지만 처리한다.

실행:
    python step4_cv_refine.py --raw "../result/test_cu_v3/raw_response.json" \
                              --pdf "../../data/raw/국사교과서.pdf" \
                              --out "../result/test_cu_v3" --debug
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

from _layout import detect_layout, match_caption
from _oai import read_caption

DEFAULT_AREA_THR = 0.10   # 채택안 B (낮은 게이트). 0으로 두면 A(전부 모델·잡동사니 폐기)


def _page_size_inch(doc: fitz.Document, page_no: int) -> tuple[float, float]:
    """1-based 페이지의 (가로, 세로) 인치 크기. (PDF point = 1/72 inch)"""
    page = doc[page_no - 1]
    return page.rect.width / 72.0, page.rect.height / 72.0


def _area_ratio(fig: dict, doc: fitz.Document) -> float:
    """figure bbox 면적 / 페이지 면적 비율. 계산 불가 시 0.0."""
    bbox = fig.get("bbox_inch")
    page_no = fig.get("page")
    if not bbox or not page_no or page_no < 1 or page_no > len(doc):
        return 0.0
    x0, y0, x1, y1 = bbox
    bbox_area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    pw, ph = _page_size_inch(doc, page_no)
    page_area = pw * ph
    return bbox_area / page_area if page_area else 0.0


def step4_cv_refine(
    figures: list[dict],
    pdf_path: str,
    out_dir: Path,
    area_thr: float = DEFAULT_AREA_THR,
    debug: bool = False,
) -> list[dict]:
    """CU figure crop의 오탐을 정제한다. Returns: 정제된 figures 리스트."""
    img_dir = out_dir / "images"
    doc = fitz.open(pdf_path)

    debug_dir = None
    if debug:
        debug_dir = out_dir / "meta" / "step4_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)

    n_a_drop = n_a_recrop = n_b = n_c = 0
    kept: list[dict] = []

    for fig in figures:
        # 0) 재실행 가드 — 이미 처리된 figure(특히 flatten된 자식)는 재탐지하지 않음
        if fig.get("false_positive_type") is not None:
            kept.append(fig)
            n_c += 1
            continue

        path = img_dir / Path(fig["img_path"]).name

        # 1) 면적비 사전 게이트 — 게이트 미만은 모델 호출 없이 그대로 통과(폐기 안 함)
        ratio = _area_ratio(fig, doc)
        if ratio < area_thr or not path.exists():
            fig["false_positive_type"] = None
            kept.append(fig)
            n_c += 1
            continue

        # 2) 이미지 객체 감지 (figure + figure_caption 박스 1회 추론)
        crop = Image.open(path).convert("RGB")
        boxes, cap_boxes = detect_layout(crop)

        if debug and debug_dir is not None:
            _save_debug(crop, boxes, debug_dir / path.name)

        # 3) 검출 개수로 분기 (0 폐기 / 1 재크롭 / N 개별 분리)
        if len(boxes) == 0:
            fig["false_positive_type"] = "A"
            path.unlink(missing_ok=True)
            n_a_drop += 1
            print(f"  [폐기] {path.name} (면적비 {ratio:.2f}, 객체 0)")
            # figures에서 제외
        elif len(boxes) == 1:
            fig["false_positive_type"] = "A"
            crop.crop(boxes[0]).save(path, format="PNG")
            kept.append(fig)
            n_a_recrop += 1
            print(f"  [재크롭] {path.name} (면적비 {ratio:.2f}) -> {tuple(int(v) for v in boxes[0])}")
        else:
            # 객체 N개 → 분리. 부모는 버리고 각 조각을 독립 figure 로 승격해
            # "모든 figure 는 실제 이미지 하나를 가진다"는 불변식을 유지한다.
            stem = path.stem
            cw, ch = crop.size
            pbb = fig.get("bbox_inch")
            used_caps: set[int] = set()
            # 부모 figcaption 보존: 줄 수가 자식 수와 같으면 위→아래로 줄별 배분,
            # 아니면 전체 캡션을 자식 모두에 상속한다(생성 폴백보다 실제 캡션이 우선).
            parent_cap = (fig.get("caption") or "").strip()
            cap_lines = [ln.strip() for ln in parent_cap.splitlines() if ln.strip()]
            split_lines = cap_lines if len(cap_lines) == len(boxes) else None
            for i, b in enumerate(boxes, 1):
                sub_name = f"{stem}_cv_{i}.png"
                crop.crop(b).save(img_dir / sub_name, format="PNG")
                child = dict(fig)                              # 부모 메타(page 등) 상속
                child["id"]       = f"{fig.get('id', '')}_cv_{i}"
                child["img_path"] = str(Path("images") / sub_name)
                child["false_positive_type"] = "B"
                # 자식 bbox_inch 재계산 (부모 crop의 px/inch로 환산, stale 상속 제거)
                if pbb and cw and ch:
                    ppi_x = cw / max(1e-6, pbb[2] - pbb[0])
                    ppi_y = ch / max(1e-6, pbb[3] - pbb[1])
                    child["bbox_inch"] = [
                        pbb[0] + b[0] / ppi_x, pbb[1] + b[1] / ppi_y,
                        pbb[0] + b[2] / ppi_x, pbb[1] + b[3] / ppi_y,
                    ]
                # 캡션 연계: 기본값은 부모 figcaption 상속(줄별 배분 또는 전체).
                child["caption"] = split_lines[i - 1] if split_lines else parent_cap
                # doclayout figure_caption 박스를 찾으면 그 정밀 전사로 덮어쓴다.
                ci = match_caption(b, cap_boxes, used_caps)
                if ci is not None:
                    used_caps.add(ci)
                    try:
                        text = read_caption(crop.crop(cap_boxes[ci])).strip()
                    except Exception as e:
                        text = ""
                        print(f"    [캡션 읽기 실패] {sub_name}: {e}")
                    if text:
                        child["caption"] = text
                        child["caption_done"] = True   # step5에서 건너뜀
                # 박스 없음/전사 실패 → 상속한 부모 캡션 유지(step5에서 정제, 생성 안 함)
                kept.append(child)
            path.unlink(missing_ok=True)                       # 부모 컨테이너 이미지 폐기
            n_b += 1                                            # 부모 figure 는 kept 에 안 넣음
            print(f"  [분리] {path.name} -> {len(boxes)}개")

    doc.close()
    print(
        f"[STEP 4] 완료 - 폐기 {n_a_drop} / 재크롭 {n_a_recrop} / "
        f"분리 {n_b} / 정상(게이트통과) {n_c}"
    )
    return kept


def _save_debug(crop: Image.Image, boxes: list, dest: Path) -> None:
    """검출 박스를 그린 디버그 이미지 저장 (임계값 튜닝용)."""
    dbg = crop.convert("RGB").copy()
    draw = ImageDraw.Draw(dbg)
    for i, b in enumerate(boxes, 1):
        draw.rectangle(b, outline=(230, 20, 20), width=3)
        draw.text((b[0] + 4, max(0, b[1] - 14)), str(i), fill=(230, 20, 20))
    dbg.save(dest, quality=90)


# ---------------------------------------------------------------------------
# 단독 실행 — figures 입력은 meta/figures.json 우선, 없으면 step3 재실행
# ---------------------------------------------------------------------------

def _load_figures(out_dir: Path, raw_path: str | None, pdf_path: str, debug: bool) -> list[dict]:
    meta = out_dir / "meta" / "figures.json"
    if meta.exists():
        print(f"[STEP 4] figures 입력: {meta}")
        return json.loads(meta.read_text(encoding="utf-8"))

    if not raw_path:
        raise FileNotFoundError(
            f"{meta} 없음 — --raw 로 raw_response.json 경로를 지정해 STEP 3을 재실행하세요."
        )
    print(f"[STEP 4] figures 입력: STEP 3-CU 재실행 ({raw_path})")
    import importlib.util

    step3_file = Path(__file__).parent / "step3_parse_cu.py"
    spec = importlib.util.spec_from_file_location("step3_parse_cu", step3_file)
    step3 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(step3)
    raw = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    return step3.step3_parse_cu(raw, pdf_path, out_dir, debug=debug)


def main():
    parser = argparse.ArgumentParser(description="STEP 4 — 이미지 후처리 (CV)")
    parser.add_argument("--pdf", required=True, help="원본 PDF 경로")
    parser.add_argument("--out", required=True, help="결과 디렉토리 (result/{pdf}_vN)")
    parser.add_argument("--raw", help="raw_response.json 경로 (figures.json 없을 때)")
    parser.add_argument("--area-thr", type=float, default=DEFAULT_AREA_THR, help="면적비 게이트 (이 미만은 모델 스킵·폐기 안 함). 0이면 전부 모델")
    parser.add_argument("--debug", action="store_true", help="검출 박스 디버그 이미지 저장")
    args = parser.parse_args()

    out_dir = Path(args.out)
    figures = _load_figures(out_dir, args.raw, args.pdf, args.debug)

    figures = step4_cv_refine(figures, args.pdf, out_dir, area_thr=args.area_thr, debug=args.debug)

    # 정제 결과를 figures.json에 반영
    meta_dir = out_dir / "meta"
    meta_dir.mkdir(exist_ok=True)
    (meta_dir / "figures.json").write_text(
        json.dumps(figures, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n--- 결과 요약 ---")
    print(f"이미지(정제 후): {len(figures)}개")
    print(f"figures.json   : {meta_dir / 'figures.json'}")


if __name__ == "__main__":
    main()
