"""
STEP 2-PREMASK — CU 전송 전, 스캔 PDF 페이지에서 PII 영역을 검은 박스로 가린다.

왜 필요한가:
    스캔 PDF 는 글자가 이미지뿐이라 Azure CU(외부 OCR)로 보내야 텍스트가 나온다.
    원본 PDF 를 그대로 보내면 PII 가 외부로 나간다. 그래서 CU 전송 *전*에:
        1. PDF 를 페이지 이미지로 래스터화 (로컬 PyMuPDF, SCALE=STEP3 와 동일)
        2. 로컬 OCR(PaddleOCR)로 "글자 + 좌표(bbox)" 를 뽑는다 (위치 탐지용, 텍스트는 버림)
        3. ko-pii 로 각 글자가 PII 인지 판정 → PII 인 bbox 만 추린다
        4. 원본 페이지 이미지의 그 bbox 를 검은 박스로 칠한다
        5. 가려진 페이지 이미지를 저장한다 (CU 입력 + STEP3 크롭 소스)

좌표 정합:
    STEP3(step3_parse_cu)는 CU figure bbox(인치)를 _inch_to_px(bbox, SCALE)로
    픽셀화해 같은 SCALE 로 렌더한 페이지에서 크롭한다. 마스킹 페이지도 *같은 SCALE*
    로 만들어 out_dir/masked/page_{N}.png 에 저장하면, CU 가 그 이미지를 보고 준
    bbox 와 STEP3 가 크롭하는 이미지가 동일 좌표계가 된다(자동 정합).

미탐 = 누출 원칙:
    OCR 이 880101 을 88O1O1 로 잘못 읽으면 ko-pii 패턴이 빗나가 PII 가 마스킹 없이
    CU 로 샌다. 이를 줄이려고 두 그물을 친다:
        - ko-pii: PARANOID(LOW 이상 모두) 로 의심 영역을 넉넉히 가린다.
        - 정규식 안전망: OCR 원시 글자에 결정적 PII(주민/전화/카드/이메일/사업자) 형식
          정규식을 한 번 더 돌려, ko-pii 가 놓쳐도 형식만 맞으면 마스킹한다.

PII 카테고리 정책(역사 도메인):
    이름·국가·주소·직책·나이·생년월일은 콘텐츠라 가명화 대상에서 제외(KO_PII_EXCLUDE).
    실제 개인정보(주민/전화/이메일/카드/계좌/사업자/여권 등)만 가린다.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

logger = logging.getLogger("preprocessing.premask")

# STEP3(step3_parse_cu.SCALE)와 반드시 동일. 좌표계 정합의 핵심.
SCALE = 2.0

# 역사 도메인: 콘텐츠성 카테고리는 가리지 않는다(지식그래프 보존). 결정적 PII 만 가린다.
KO_PII_EXCLUDE = {"PERSON", "ADDRESS", "NATIONALITY", "POSITION", "AGE", "DOB"}

# 미탐 대비 정규식 안전망 — 결정적 PII 형식만. OCR 오인식 흡수용이라 느슨하게 잡고,
# 과탐(본문 약간 손실)은 미탐(PII 누출)보다 안전하다는 원칙으로 recall 우선.
_SAFETY_PATTERNS = [
    re.compile(r"\d{6}\s*[-–]\s*\d{7}"),                 # 주민/외국인등록번호 6-7
    re.compile(r"01[016789]\s*[-–]?\s*\d{3,4}\s*[-–]?\s*\d{4}"),  # 휴대폰
    re.compile(r"0\d{1,2}\s*[-–]\s*\d{3,4}\s*[-–]\s*\d{4}"),      # 유선전화
    re.compile(r"\d{3,4}\s*[-–]\s*\d{2}\s*[-–]\s*\d{5}"),         # 사업자/계좌류
    re.compile(r"(?:\d[ -]?){13,19}"),                   # 카드/계좌 무구분 13~19자리
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # 이메일
    re.compile(r"\b[MSPRG]\d{8}\b"),                     # 여권(M/S/PP 등 prefix + 8)
]


def _render_page(page: "fitz.Page") -> "Image.Image":
    """페이지를 SCALE 배율로 렌더해 PIL 이미지로 돌려준다(STEP3 와 동일 방식)."""
    from PIL import Image

    pix = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE))
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


# ── 로컬 OCR (PaddleOCR) — lazy 싱글톤 ──────────────────────────────────────
# App Service RAM 경쟁(README: 인덱싱 subprocess 와 메모리 다툼) 때문에 모델은
# 최초 호출 때만 로드하고 프로세스 수명 동안 재사용한다. 단일 워커 전제라 락 불필요.
_OCR = None
_OCR_FAILED = False


def _get_ocr():
    """PaddleOCR 한국어 모델을 lazy 로드. 실패하면 None(안전망 정규식만으로 폴백)."""
    global _OCR, _OCR_FAILED
    if _OCR is not None or _OCR_FAILED:
        return _OCR
    try:
        # Windows DLL 순서: paddle 이 torch 보다 먼저 로드되면 torch 가 shm.dll
        # 의존 로드에서 WinError 127 로 깨진다(둘이 런타임 DLL 공유). paddleocr 의
        # import 가 paddle 을 먼저 끌어오므로 torch 를 *먼저* 임포트해 순서를 고정.
        import torch  # noqa: F401  (순서 고정용 선임포트)
        from paddleocr import PaddleOCR

        # PaddleOCR 3.x API(레포 설치 버전). lang="korean": 한글+숫자+영문.
        # device="cpu": CPU 휠 전제. enable_mkldnn=False: paddle 3.3.1 에서 OneDNN
        # 융합 conv 가 'fused_conv2d ... input Filter' 로 터지는 것을 막는다.
        #
        # 좌표 정합 핵심: 3.x 는 기본으로 문서 보정(UVDoc 언워핑)·방향분류를 전처리로
        # 돌려, rec_boxes 를 *보정된 이미지* 좌표로 돌려준다. 그 박스를 원본 페이지에
        # 그리면 한 줄씩 어긋나 PII 가 노출된다. premask 는 입력 이미지 좌표가
        # 반드시 필요하므로 둘 다 꺼서 raw 입력 위에서 검출·반환하게 한다.
        # (textline_orientation 도 끈다 — 회전 보정이 박스 좌표를 틀어 같은 문제 유발.)
        # text_detection_model_name="PP-OCRv5_mobile_det": 기본 검출은 server 모델
        # (대형)이라 CPU 에서 페이지당 수십 초가 든다. premask 는 PII 위치(bbox)만
        # 필요하고 정밀 인식 품질은 덜 중요하므로, 경량 mobile 검출로 바꿔 CPU 추론을
        # 크게 단축한다(인식은 어차피 mobile_rec).
        _OCR = PaddleOCR(
            lang="korean",
            device="cpu",
            enable_mkldnn=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_detection_model_name="PP-OCRv5_mobile_det",
        )
        logger.info("PaddleOCR(korean) 로드 완료")
    except Exception as e:  # noqa: BLE001 — 어떤 로드 실패든 안전망으로 폴백
        _OCR_FAILED = True
        logger.warning("PaddleOCR 로드 실패 → 정규식 안전망만 사용: %s", e)
    return _OCR


def _ocr_boxes(pil_img) -> list[tuple[str, list[float]]]:
    """이미지에서 (텍스트, [x0,y0,x1,y1]) 목록을 뽑는다.

    PaddleOCR 3.x predict() 가 주는 축정렬 rec_boxes 를 그대로 쓴다(없으면
    rec_polys 4점을 min/max 로 환산). OCR 미가용/추론 실패 시 빈 목록 →
    그 페이지는 마스킹 0(정규식 안전망도 검사할 텍스트가 없어 무의미).
    """
    import numpy as np

    ocr = _get_ocr()
    if ocr is None:
        return []
    arr = np.array(pil_img)
    try:
        result = ocr.predict(arr)
    except Exception as e:  # noqa: BLE001
        logger.warning("OCR 추론 실패(page 건너뜀): %s", e)
        return []

    boxes: list[tuple[str, list[float]]] = []
    # PaddleOCR 3.x: predict -> 페이지별 dict 리스트. rec_texts 와 평행하게
    # rec_boxes(축정렬 [x0,y0,x1,y1]) / rec_polys(4점) 가 온다(점수 필터 없음 —
    # premask 는 PII recall 우선이라 모든 박스를 PII 판정에 넘긴다).
    for res in result:
        texts = res.get("rec_texts", [])
        rboxes = res.get("rec_boxes", [])
        polys = res.get("rec_polys", [])
        for i, text in enumerate(texts):
            if i < len(rboxes) and rboxes[i] is not None:
                x0, y0, x1, y1 = (float(v) for v in rboxes[i])
            elif i < len(polys):
                xs = [p[0] for p in polys[i]]
                ys = [p[1] for p in polys[i]]
                x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
            else:
                continue
            boxes.append((text, [x0, y0, x1, y1]))
    return boxes


# ── ko-pii 판정 — lazy 싱글톤 ───────────────────────────────────────────────
_ANON = None
_ANON_FAILED = False


def _get_anonymizer():
    """ko-pii Anonymizer(PARANOID) 를 lazy 로드. 실패하면 None(안전망만)."""
    global _ANON, _ANON_FAILED
    if _ANON is not None or _ANON_FAILED:
        return _ANON
    try:
        from ko_pii import Anonymizer, ProcessingMode

        # PARANOID: LOW 이상 모두 차단(미탐 최소화). AUDIT 가 아니라 검출 자체가 목적이라
        # strategy 는 무의미(우린 .text 가 아니라 검출 좌표만 쓴다). redact 로 둔다.
        _ANON = Anonymizer(
            mode=ProcessingMode.PARANOID,
            strategy="redact",
            exclude=KO_PII_EXCLUDE,
        )
        logger.info("ko-pii Anonymizer(PARANOID, exclude=%s) 로드", sorted(KO_PII_EXCLUDE))
    except Exception as e:  # noqa: BLE001
        _ANON_FAILED = True
        logger.warning("ko-pii 로드 실패 → 정규식 안전망만 사용: %s", e)
    return _ANON


def _text_has_pii(text: str) -> bool:
    """한 OCR 조각이 PII 를 포함하는지: ko-pii 검출 OR 안전망 정규식 매칭."""
    if not text or not text.strip():
        return False
    # 1) 안전망 정규식(결정적 형식) — OCR 오인식·ko-pii 미로드에도 동작
    for pat in _SAFETY_PATTERNS:
        if pat.search(text):
            return True
    # 2) ko-pii 검출(맥락 기반). 결과 텍스트가 원문과 다르면 무언가 가려졌다는 뜻.
    anon = _get_anonymizer()
    if anon is not None:
        try:
            result = anon.process(text)
            # redact 전략은 PII 를 [카테고리]로 바꾸므로, 바뀌었으면 PII 존재.
            if result.text != text:
                return True
            # summary 가 있으면 by_label 비어있지 않은지로도 확인(버전별 호환).
            summary = getattr(result, "summary", None)
            if summary and summary.get("by_label"):
                return True
        except Exception as e:  # noqa: BLE001
            logger.debug("ko-pii process 예외(무시): %s", e)
    return False


# 텍스트 스크럽 전용 패턴: 결정적 PII 만 고정밀로. premask 의 _SAFETY_PATTERNS 에서
# '무구분 13~19자리'(catch-all)는 본문 숫자/연도 나열을 오탐해 지식그래프를 망치므로
# 제외한다(스캔은 OCR 오인식 흡수용으로 필요했지만, 디지털 텍스트엔 과탐만 됨).
_SCRUB_PATTERNS = [p for p in _SAFETY_PATTERNS if "{13,19}" not in p.pattern]

# 텍스트 스크럽용 ko-pii 는 *BALANCED* (이미지 마스킹의 PARANOID 와 분리). PARANOID 는
# 본문의 긴 숫자(예: GDP 17500000)를 전화번호로 오탐해 지식그래프를 망친다. BALANCED 는
# 그 오탐을 없애면서도 무구분 전화 등 실제 PII 는 잡는다(검증됨). 텍스트는 그래프로
# 직행하므로 recall(이미지)보다 precision(텍스트)을 택한다.
_ANON_SCRUB = None
_ANON_SCRUB_FAILED = False


def _get_scrub_anonymizer():
    """텍스트 스크럽용 ko-pii(BALANCED) lazy 로드. 실패 시 None(정규식만)."""
    global _ANON_SCRUB, _ANON_SCRUB_FAILED
    if _ANON_SCRUB is not None or _ANON_SCRUB_FAILED:
        return _ANON_SCRUB
    try:
        from ko_pii import Anonymizer, ProcessingMode

        _ANON_SCRUB = Anonymizer(
            mode=ProcessingMode.BALANCED, strategy="redact", exclude=KO_PII_EXCLUDE,
        )
        logger.info("ko-pii Anonymizer(BALANCED, 텍스트 스크럽용) 로드")
    except Exception as e:  # noqa: BLE001
        _ANON_SCRUB_FAILED = True
        logger.warning("ko-pii(스크럽) 로드 실패 → 정규식만: %s", e)
    return _ANON_SCRUB


def scrub_text_pii(text: str) -> tuple[str, int]:
    """텍스트에서 PII 를 *제거* 한다(토큰 안 남김 — 디지털 경로 + 스캔 안전망용).

    스캔의 이미지 마스킹(검은 박스→OCR 0=텍스트에 없음)과 동일한 결과(코퍼스에 PII
    부재)를 만든다. [PII] 같은 리터럴 토큰을 남기면 GraphRAG 가 빈도 높은 가짜 노드로
    뽑을 위험이 있어, 토큰 치환이 아니라 해당 구간을 들어낸다. 디지털 PDF 는 텍스트가
    로컬 추출이라 마스킹 대상 이미지가 없으므로 추출 텍스트에 직접 적용해 STEP5(LLM)·
    index(GraphRAG)로 PII 가 새는 것을 막는다.

    그래프 무결성: ko-pii 는 검출 *스팬(위치)* 만 제거하므로 [pageN]·[그림 1] 등 본문
    괄호는 건드리지 않고, 인물·지명(KO_PII_EXCLUDE)도 보존된다.

    Returns: (PII 제거된 텍스트, 제거 건수).
    """
    if not text:
        return text, 0
    count = 0
    # 1) 결정적 정규식(고정밀) → 제거. 주민/전화/카드(구분자)/이메일/여권.
    for pat in _SCRUB_PATTERNS:
        text, n = pat.subn("", text)
        count += n
    # 2) ko-pii(BALANCED) 맥락 탐지 → 검출 스팬만 위치로 들어낸다(뒤에서 앞으로 잘라
    #    오프셋 보존). label/text 가 아니라 start/end 로 제거해 본문 괄호를 안 건드린다.
    anon = _get_scrub_anonymizer()
    if anon is not None:
        try:
            res = anon.process(text)
            # action==BLOCK 만 제거한다. ko-pii 는 REVIEW/ALLOW(예: 본문 큰 숫자 GDP)도
            # detections 에 담지만 실제 가리지(.text) 않으므로, 그걸 지우면 본문이 깨진다.
            blocked = [
                r for r in res.detections
                if getattr(r.action, "name", str(r.action)) == "BLOCK"
            ]
            for rec in sorted(blocked, key=lambda r: r.detection.start, reverse=True):
                s, e = rec.detection.start, rec.detection.end
                if 0 <= s < e <= len(text):
                    text = text[:s] + text[e:]
                    count += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("scrub ko-pii 예외(무시): %s", exc)
    # 제거로 생긴 이중 공백만 정리(줄바꿈=페이지 구조는 보존).
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text, count


def _mask_page(pil_img, boxes: list[tuple[str, list[float]]]) -> int:
    """PII 로 판정된 box 를 검은 사각형으로 덮는다. 가린 개수를 반환."""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(pil_img)
    masked = 0
    for text, (x0, y0, x1, y1) in boxes:
        if _text_has_pii(text):
            # 2px 여유로 글자 가장자리까지 확실히 덮는다(과탐 안전 원칙).
            draw.rectangle([x0 - 2, y0 - 2, x1 + 2, y1 + 2], fill=(0, 0, 0))
            masked += 1
    return masked


def premask_pdf(pdf_path: str, out_dir: Path) -> dict:
    """스캔 PDF 를 페이지별로 마스킹해 out_dir/masked/page_{N}.png 로 저장한다.

    Returns:
        {
          "masked_dir": Path,                 # 마스킹 페이지 PNG 디렉터리
          "page_paths": {page_no(1-based): Path},  # STEP3 가 크롭 소스로 쓴다
          "total_masked": int,                # 가린 PII box 총수(로깅/감사용)
          "scale": float,                     # 좌표 정합 기준(STEP3 와 동일해야)
        }
    """
    masked_dir = out_dir / "masked"
    masked_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    page_paths: dict[int, Path] = {}
    total_masked = 0

    for page_idx in range(len(doc)):
        page_no = page_idx + 1
        pil_img = _render_page(doc[page_idx])
        boxes = _ocr_boxes(pil_img)
        n = _mask_page(pil_img, boxes)
        total_masked += n

        out_png = masked_dir / f"page_{page_no}.png"
        pil_img.save(out_png, format="PNG")
        page_paths[page_no] = out_png
        logger.info(
            "premask page=%d ocr_boxes=%d masked=%d -> %s",
            page_no, len(boxes), n, out_png.name,
        )

    doc.close()
    logger.info("premask 완료: %d 페이지, PII box %d개 마스킹", len(page_paths), total_masked)

    # 마스킹 PDF 도 만든다 — CU 의 :analyzeBinary 가 PDF 를 받으므로(이미지 묶음 PDF).
    masked_pdf = out_dir / "masked.pdf"
    _images_to_pdf([page_paths[p] for p in sorted(page_paths)], masked_pdf)

    return {
        "masked_dir": masked_dir,
        "masked_pdf": masked_pdf,
        "page_paths": page_paths,
        "total_masked": total_masked,
        "scale": SCALE,
    }


def _images_to_pdf(image_paths: list[Path], out_pdf: Path) -> None:
    """마스킹된 페이지 PNG들을 한 PDF 로 묶는다(CU analyzeBinary 입력용)."""
    from PIL import Image

    if not image_paths:
        raise RuntimeError("마스킹 페이지가 없어 PDF 를 만들 수 없음")
    imgs = [Image.open(p).convert("RGB") for p in image_paths]
    imgs[0].save(out_pdf, format="PDF", save_all=True, append_images=imgs[1:])
    logger.info("masked.pdf 생성: %d 페이지 -> %s", len(imgs), out_pdf.name)
