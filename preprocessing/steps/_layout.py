"""
STEP 4 — 레이아웃 모델 기반 이미지 객체 검출 (옵션 2)

doclayout-yolo(DocStructBench)로 figure 영역을 의미적으로 검출한다.
휴리스틱(_cv.py)과 동일한 인터페이스 `detect_image_objects(crop) -> list[Box]`라
step4_cv_refine은 import만 바꾸면 된다.

모델: juliozhao/DocLayout-YOLO-DocStructBench (HF, 최초 1회 자동 다운로드 후 캐시)
클래스: 0 title / 1 plain text / 2 abandon / 3 figure / 4 figure_caption
        5 table / 6 table_caption / 7 table_footnote / 8 isolate_formula / 9 formula_caption
"""

from __future__ import annotations

from PIL import Image

Box = tuple[int, int, int, int]

_REPO = "juliozhao/DocLayout-YOLO-DocStructBench"
_WEIGHT = "doclayout_yolo_docstructbench_imgsz1024.pt"
_TARGET_CLASSES = {"figure"}   # 필요 시 "table", "isolate_formula" 추가 가능

_MODEL = None


def _get_model():
    """모델 1회 로드 후 캐시."""
    global _MODEL
    if _MODEL is None:
        from doclayout_yolo import YOLOv10
        from huggingface_hub import hf_hub_download

        weight = hf_hub_download(_REPO, _WEIGHT)
        _MODEL = YOLOv10(weight)
    return _MODEL


def _overlap_ratio(a: Box, b: Box) -> float:
    """교집합 / 작은 박스 면적 (작은 박스가 큰 박스에 얼마나 들어가는지)."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter == 0:
        return 0.0
    aa = (a[2] - a[0]) * (a[3] - a[1])
    ba = (b[2] - b[0]) * (b[3] - b[1])
    return inter / max(1, min(aa, ba))


def _area(b: Box) -> int:
    return (b[2] - b[0]) * (b[3] - b[1])


def _union(boxes: list[Box]) -> Box:
    return (
        min(b[0] for b in boxes), min(b[1] for b in boxes),
        max(b[2] for b in boxes), max(b[3] for b in boxes),
    )


# rule1 잔여영역 채택 기준: 큰 박스가 작은 박스들의 합집합 밖에 가진 고유 영역이
# 자기 면적의 이 비율 이상이면 "별개 사진"으로 보고 잔여 밴드를 살린다.
_RESIDUAL_RATIO = 0.25
_RESIDUAL_MIN_SIDE = 40   # 잔여 밴드 최소 변(px) — 너무 얇은 띠는 무시


def _residual_band(big: Box, inner: Box) -> Box | None:
    """big 안에서 inner(겹친 작은 박스들의 합집합) 바깥의 가장 큰 사각 밴드.

    위/아래/좌/우 4개 후보 중 면적 최대를 고른다. fig_3_2·fig_23_2처럼
    '위 사진들 + 아래 가로 bleed 사진'에서 아래 밴드를 분리해 살리는 용도.
    """
    bx0, by0, bx1, by1 = big
    ux0, uy0, ux1, uy1 = inner
    cands = [
        (bx0, uy1, bx1, by1),   # 아래
        (bx0, by0, bx1, uy0),   # 위
        (ux1, by0, bx1, by1),   # 오른쪽
        (bx0, by0, ux0, by1),   # 왼쪽
    ]
    best, best_area = None, 0
    for c in cands:
        w, h = c[2] - c[0], c[3] - c[1]
        if w < _RESIDUAL_MIN_SIDE or h < _RESIDUAL_MIN_SIDE:
            continue
        a = w * h
        if a > best_area:
            best, best_area = c, a
    return best


def _cleanup(boxes: list[Box]) -> list[Box]:
    """겹침/포함 박스 정리.

    rule1: 어떤 박스가 다른 박스 2개 이상과 크게 겹치고 그중 가장 크면,
           겹친 박스들의 합집합 밖 고유 영역이 충분하면 그 잔여 밴드로 교체
           (별개의 가로 bleed 사진), 아니면 제거(여러 사진을 한 덩어리로 잡은 병합 오탐).
    rule2: 더 큰 박스에 80% 이상 포함된 작은 박스 제거
           (다이어그램 일부를 별도 figure로 잡은 중복 제거)
    """
    n = len(boxes)
    drop: set[int] = set()
    work = list(boxes)   # rule1에서 일부 박스를 잔여 밴드로 교체

    for i in range(n):
        ov = [j for j in range(n) if j != i and _overlap_ratio(boxes[i], boxes[j]) > 0.5]
        if len(ov) >= 2 and all(_area(boxes[i]) >= _area(boxes[j]) for j in ov):
            resid = _residual_band(boxes[i], _union([boxes[j] for j in ov]))
            if resid and _area(resid) >= _RESIDUAL_RATIO * _area(boxes[i]):
                work[i] = resid          # 별개 사진 → 잔여 밴드로 축소해 유지
            else:
                drop.add(i)              # 병합 오탐 → 제거

    for i in range(n):
        if i in drop:
            continue
        for j in range(n):
            if j == i or j in drop:
                continue
            if _area(work[j]) > _area(work[i]) and _overlap_ratio(work[i], work[j]) >= 0.8:
                drop.add(i)
                break

    return [work[i] for i in range(n) if i not in drop]


def detect_layout(crop: Image.Image, conf: float = 0.2, imgsz: int = 1024) -> tuple[list[Box], list[Box]]:
    """모델 1회 추론으로 (figure 박스, figure_caption 박스)를 함께 반환한다.

    - figure: cleanup(겹침/포함 정리) 적용 후 위→아래 정렬
    - figure_caption: 원본 박스(캡션 매칭용), 위→아래 정렬
    """
    rgb = crop.convert("RGB")
    W, H = rgb.size
    model = _get_model()
    result = model.predict(rgb, imgsz=imgsz, conf=conf, verbose=False)[0]

    figures: list[Box] = []
    captions: list[Box] = []
    for b in result.boxes:
        name = result.names[int(b.cls)]
        x0, y0, x1, y1 = (int(v) for v in b.xyxy[0].tolist())
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(W, x1), min(H, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        if name in _TARGET_CLASSES:
            figures.append((x0, y0, x1, y1))
        elif name == "figure_caption":
            captions.append((x0, y0, x1, y1))

    figures = sorted(_cleanup(figures), key=lambda r: (r[1], r[0]))
    captions = sorted(captions, key=lambda r: (r[1], r[0]))
    return figures, captions


def detect_image_objects(crop: Image.Image, conf: float = 0.2, imgsz: int = 1024) -> list[Box]:
    """figure crop에서 실제 이미지(figure) 객체 박스 목록을 반환한다.

    반환 개수로 step4_cv_refine이 분기: 0개 폐기 / 1개 재크롭 / N개 분리.
    """
    return detect_layout(crop, conf=conf, imgsz=imgsz)[0]


def match_caption(fig_box: Box, captions: list[Box], used: set[int] | None = None) -> int | None:
    """figure에 가장 잘 맞는 caption 박스의 인덱스를 반환 (없으면 None).

    조건: 수평으로 겹치고, figure 아래(또는 살짝 겹침)에 위치. 가장 가까운 것을 고른다.
    used에 든 인덱스는 이미 다른 figure에 배정됐으므로 제외.
    """
    fx0, fy0, fx1, fy1 = fig_box
    fh = max(1, fy1 - fy0)
    used = used or set()
    best_idx = None
    best_key = None
    for i, c in enumerate(captions):
        if i in used:
            continue
        cx0, cy0, cx1, cy1 = c
        overlap_x = min(fx1, cx1) - max(fx0, cx0)
        if overlap_x <= 0:
            continue                      # 수평으로 안 겹치면 다른 사진의 캡션
        vgap = cy0 - fy1
        if vgap < -fh * 0.5:
            continue                      # 캡션이 사진 위/안쪽 깊숙이면 제외
        key = (abs(vgap), -overlap_x)     # 수직 간격 최소 + 수평 겹침 최대
        if best_key is None or key < best_key:
            best_key = key
            best_idx = i
    return best_idx
