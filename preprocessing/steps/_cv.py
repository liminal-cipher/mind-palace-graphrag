"""
STEP 4 — CV 영역 검출 순수 함수 모듈

img-processing/_internal/extract_figures_with_captions.py의 검증된 CV 로직을
crop 단위 "객체 감지 후 개별 크롭"에 맞게 이식·개선한 모듈. (NumPy + Pillow)

설계: figure crop 안의 실제 이미지 객체를 감지해 박스 리스트로 반환한다.
  0개 → 폐기 / 1개 → 재크롭 / N개 → 개별 분리  (step4_cv_refine에서 분기)

원본(1050px 페이지 통이미지) 대비 개선점:
  (a) 과병합 제거 — MaxFilter 축소 + merge gap 축소로 인접 사진을 붙이지 않음
  (b) 컬럼 전용 분리 폐기 — 2D 연결요소로 분리, refine은 캡션 행 잘라내기만
  (c) 텍스트·장식 띠 거부 강화 — 사진 vs 텍스트/머리띠 구분
  + 페이지 위치 전제 필터 제거, 절대 임계값 → crop 상대값
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np
from PIL import Image, ImageFilter

Box = tuple[int, int, int, int]


# ---------------------------------------------------------------------------
# 연결 영역 / 박스 병합 (원본 그대로)
# ---------------------------------------------------------------------------

def connected_components(mask: np.ndarray, min_area: int) -> list[tuple[int, int, int, int, int]]:
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    boxes = []
    for y in range(h):
        xs = np.flatnonzero(mask[y] & ~seen[y])
        for x0 in xs:
            if seen[y, x0] or not mask[y, x0]:
                continue
            q = deque([(x0, y)])
            seen[y, x0] = True
            minx = maxx = x0
            miny = maxy = y
            area = 0
            while q:
                x, yy = q.popleft()
                area += 1
                minx = min(minx, x)
                maxx = max(maxx, x)
                miny = min(miny, yy)
                maxy = max(maxy, yy)
                for nx, ny in ((x + 1, yy), (x - 1, yy), (x, yy + 1), (x, yy - 1)):
                    if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((nx, ny))
            if area >= min_area:
                boxes.append((minx, miny, maxx + 1, maxy + 1, area))
    return boxes


def merge_boxes(boxes: list[Box], gap: int) -> list[Box]:
    out: list[Box] = []
    for box in boxes:
        x0, y0, x1, y1 = box
        merged = False
        for i, old in enumerate(out):
            ox0, oy0, ox1, oy1 = old
            close = not (x1 + gap < ox0 or ox1 + gap < x0 or y1 + gap < oy0 or oy1 + gap < y0)
            if close:
                out[i] = (min(x0, ox0), min(y0, oy0), max(x1, ox1), max(y1, oy1))
                merged = True
                break
        if not merged:
            out.append(box)
    if len(out) == len(boxes):
        return out
    return merge_boxes(out, gap)


# ---------------------------------------------------------------------------
# (b) 캡션 행 잘라내기 — 컬럼 분리 없이 위/아래 캡션 텍스트만 trim
# ---------------------------------------------------------------------------

def trim_caption_rows(rgb: Image.Image, box: Box) -> Box:
    """박스 상/하단의 희소한 캡션 텍스트 행을 잘라내고 빽빽한 이미지 영역만 남긴다."""
    x0, y0, x1, y1 = box
    crop = np.asarray(rgb.crop(box)).astype(np.int16)
    if crop.size == 0:
        return box
    maxc = crop.max(axis=2)
    minc = crop.min(axis=2)
    sat = maxc - minc
    colored = (sat > 26) & (maxc < 248)
    dark = maxc < 95
    score = colored.mean(axis=1) + dark.mean(axis=1) * 0.12
    dense = score > 0.024

    rows = np.flatnonzero(dense)
    if not len(rows):
        return box
    start = rows[0]
    end = rows[0]
    last = rows[0]
    for r in rows[1:]:
        # 큰 행 간격 = 캡션 시작. 이미지 본체(>35행)를 확보한 뒤 멈춘다.
        if r - last > 12 and (last - start) > 35:
            break
        end = r
        last = r
    ny0 = y0 + max(0, int(start) - 3)
    ny1 = min(y1, y0 + int(end) + 6)
    return (x0, ny0, x1, ny1)


# ---------------------------------------------------------------------------
# (c) 종이/텍스트/장식 띠 박스 거부 (페이지 위치 필터 제거 + crop 상대 임계값)
# ---------------------------------------------------------------------------

def is_keep_figure(rgb: Image.Image, box: Box) -> bool:
    W, H = rgb.size
    x0, y0, x1, y1 = [int(v) for v in box]
    bw, bh = x1 - x0, y1 - y0

    # crop 상대 최소 크기
    if bw < W * 0.08 or bh < H * 0.06:
        return False
    # 전체폭 얇은 띠 (페이지 머리/꼬리 색 띠) 거부
    if bw > W * 0.80 and bh < H * 0.12:
        return False

    crop = np.asarray(rgb.crop((x0, y0, x1, y1))).astype(np.int16)
    if crop.size == 0:
        return False
    maxc = crop.max(axis=2)
    minc = crop.min(axis=2)
    sat = maxc - minc
    paper = (maxc > 220) & (sat < 30)
    visual = ((sat > 28) & (maxc < 248)) | (maxc < 110)
    visual_fill = float(visual.mean())
    paper_fill = float(paper.mean())

    # 가로로 긴 텍스트 줄 거부
    if bw / max(bh, 1) > 5.8 and bh < H * 0.12:
        return False
    # 사진은 연속톤이라 박스를 빽빽이 채운다(visual_fill 높음, paper_fill 낮음).
    # 텍스트/장식 띠 페이지는 흰 여백이 많아 그 반대 → 거부.
    # (실측: 사진 vis 0.56~0.89/paper 0.07~0.34, 텍스트 vis 0.29/paper 0.66)
    if visual_fill < 0.40:
        return False
    if paper_fill > 0.55:
        return False
    return True


# ---------------------------------------------------------------------------
# crop 단위 이미지 객체 감지 (detect_visual_boxes 개선판)
# ---------------------------------------------------------------------------

def detect_image_objects(crop: Image.Image) -> list[Box]:
    """figure crop 한 장에서 실제 이미지 객체 박스 목록을 반환한다.

    반환 개수로 STEP 4가 분기:
      0개 → 폐기 / 1개 → 재크롭 / 2개 이상 → 개별 분리
    """
    rgb = crop.convert("RGB")
    W, H = rgb.size
    if W < 8 or H < 8:
        return []

    arr = np.asarray(rgb).astype(np.int16)
    maxc = arr.max(axis=2)
    minc = arr.min(axis=2)
    sat = maxc - minc
    dark = maxc < 95
    colored = (sat > 26) & (maxc < 248)
    nonpaper = maxc < 235

    # 채도 영역 + 어두운(비종이) 영역을 시각 요소로 본다.
    mask = colored | (dark & nonpaper)
    mask_img = Image.fromarray((mask * 255).astype("uint8"))
    # (a) 인접 사진을 붙이지 않도록 팽창 커널 축소 (원본 15 → 9)
    mask_img = mask_img.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(5))
    small = mask_img.resize((math.ceil(W / 4), math.ceil(H / 4)), Image.Resampling.NEAREST)
    smask = np.asarray(small) > 0

    # 1/4 축소 마스크 기준 최소 면적 (crop 상대값)
    min_area = max(20, int((W * H) / 16 * 0.0006))
    raw = connected_components(smask, min_area=min_area)

    boxes: list[Box] = []
    for x0, y0, x1, y1, _area in raw:
        box = (x0 * 4, y0 * 4, min(x1 * 4, W), min(y1 * 4, H))
        bx0, by0, bx1, by1 = box
        bw, bh = bx1 - bx0, by1 - by0
        if bw < W * 0.06 or bh < H * 0.04:
            continue
        if bw * bh < W * H * 0.01:
            continue
        # crop 거의 전체를 덮는 박스 제외
        if bw > W * 0.92 and bh > H * 0.82:
            continue
        # 전체폭 얇은 띠 (머리/꼬리) 조기 제외 → 사진과 병합되지 않도록
        if bw > W * 0.80 and bh < H * 0.10:
            continue
        boxes.append(box)

    # (a) 박스 병합 안 함: connected_components가 이미 개별 사진을 분리했고,
    #     bleed 레이아웃에선 박스가 겹쳐 병합 시 다시 한 덩어리가 되므로 생략.
    #     단일 사진의 파편화는 위 형태학적 닫기(MaxFilter→MinFilter)로 완화한다.

    # 대부분 텍스트인 희소 블록 제거
    filtered: list[Box] = []
    for box in boxes:
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0, y1 - y0
        cr = np.asarray(rgb.crop(box)).astype(np.int16)
        if cr.size == 0:
            continue
        crop_sat = (cr.max(axis=2) - cr.min(axis=2) > 26).mean()
        crop_dark = (cr.max(axis=2) < 95).mean()
        if crop_sat < 0.015 and crop_dark < 0.06:
            continue
        if bw / max(bh, 1) > 8 and crop_sat < 0.04:
            continue
        filtered.append(box)

    # 더 큰 박스에 포함된 박스 제거
    keep: list[Box] = []
    for i, b in enumerate(filtered):
        x0, y0, x1, y1 = b
        area = (x1 - x0) * (y1 - y0)
        contained = False
        for j, c in enumerate(filtered):
            if i == j:
                continue
            cx0, cy0, cx1, cy1 = c
            carea = (cx1 - cx0) * (cy1 - cy0)
            if carea > area * 1.2 and x0 >= cx0 - 5 and y0 >= cy0 - 5 and x1 <= cx1 + 5 and y1 <= cy1 + 5:
                contained = True
                break
        if not contained:
            keep.append(b)

    # (b) 컬럼 분리 없이 캡션 행만 trim → (c) 최종 거부 필터
    refined = [trim_caption_rows(rgb, box) for box in keep]
    refined = [box for box in refined if is_keep_figure(rgb, box)]
    return sorted(refined, key=lambda r: (r[1], r[0]))
