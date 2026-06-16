# 전처리 파이프라인 v2 구현 계획서

## 개요

PDF 문서를 입력받아 **본문 텍스트 / 목차 / 이미지 / 캡션**을 추출하고 전처리하는 통합 파이프라인.  
v1 대비 이미지·캡션 파이프라인 추가, OpenCV 이미지 정제 포함, 텍스트 정제는 LLM으로 통합.

**입력:** PDF 파일 경로  
**출력:** `result/{pdf이름}_vN/` 폴더

```bash
python pipeline_v2.py --pdf "../data/raw/통계기초.pdf"
python pipeline_v2.py --pdf "../data/raw/통계기초.pdf" --debug
```

---

## 파이프라인 구조

```
PDF 입력
  │
  ▼
[STEP 1] 스캔 / 디지털 판별
  │   PyMuPDF로 중간 2페이지 평균 글자 수 확인
  │   평균 < 100자 → 스캔 PDF
  │
  ├──── 스캔 PDF ──────────────────────────────────┐
  │                                                │
  └──── 디지털 PDF                                  │
           │                                       │
           ▼                                       ▼
  [STEP 2-MU] PyMuPDF 추출              [STEP 2-CU] CU API 추출
    이미지: type==1 블록 bbox 크롭         raw_response.json 캐시
    텍스트: 페이지별 추출 + [pageN]          (재실행 시 API 재호출 스킵)
    캡션: STEP 5에서 LLM으로 생성            │
           │                               ▼
           │                      [STEP 3-CU] 이미지/텍스트/캡션 분리
           │                        <figure> bbox → 크롭
           │                        본문 텍스트 추출
           │                        <figcaption> → 캡션 추출
           │                               │
           ▼ ◄─────────────────────────────┘
  [STEP 4] 이미지 후처리 (OpenCV) — CU 경로만
    Type A: 페이지 전체 오탐 → 폐기 또는 재크롭
    Type B: 복수 이미지 병합 → 서브 이미지 분리
           │
           ▼
  [STEP 5] LLM 정제 및 목차 추출
    본문 텍스트 정제 (LaTeX 오류·OCR 노이즈 교정)
    캡션 정제 / 생성
      - CU 경로: 추출된 캡션 정제
      - PyMuPDF 경로: 이미지 기반 캡션 생성
    목차 추출 → toc.txt
           │
           ▼
결과 저장
  result/{pdf이름}_vN/
  ├── img/               ← 이미지
  ├── txt/
  │   ├── content.txt        ← 본문 텍스트 (순수 텍스트, 페이지 번호 없음)
  │   ├── content_paged.txt  ← 본문 텍스트 + 페이지 번호 ([pageN] 마커 포함)
  │   ├── toc.txt            ← 목차 (LLM 생성)
  │   └── caption.txt        ← 캡션 (페이지 번호 포함)
  └── raw_response.json  (CU 경로만)
```

---

## STEP 1 — 스캔 / 디지털 판별

| 판단 기준 | 값 |
|-----------|-----|
| 검사 페이지 | 문서 중간 2장 (`len(doc) // 2`, `len(doc) // 2 + 1`) |
| 글자 수 임계값 | 평균 100자 미만 → 스캔 |
| 라이브러리 | PyMuPDF (`fitz`) |

```python
doc = fitz.open(pdf_path)
mid = len(doc) // 2
pages = [mid, min(mid + 1, len(doc) - 1)]
avg = sum(len(doc[i].get_text().strip()) for i in pages) / len(pages)
doc.close()
is_scan = avg < 100
```

- 표지·목차 편향 없이 문서 중간을 대표 페이지로 사용, 2장 평균으로 단일 이상 페이지 영향 완화
- `--scan` 인자로 수동 강제 지정 가능
- PyMuPDF 미설치 시 스캔으로 간주하고 CU 경로 사용

**판별 결과에 따른 경로:**

| PDF 유형 | 추출 방법 |
|----------|-----------|
| 스캔 | Content Understanding API |
| 디지털 | PyMuPDF |

---

## STEP 2-CU — Content Understanding API 추출 (스캔 PDF)

**참조:** `extract/content-understanding/extract.py`

- Azure AI Content Understanding API (`2025-11-01-preview`)
- Analyzer ID: `pdf-content-extractor`
- 환경변수: `CONTENT_UNDERSTANDING_ENDPOINT`, `CONTENT_UNDERSTANDING_KEY`
- **캐시 전략:** `raw_response.json`이 이미 존재하면 API 재호출 없이 파일 로드

---

## STEP 2-MU — PyMuPDF 추출 (디지털 PDF)

**참조:** `extract/pymupdf/approach3/test_approach3.py`

```
PDF 페이지
    ↓
get_text("dict")로 블록 목록 파싱
    ├── type == 0 (텍스트 블록) → 페이지 텍스트로 수집
    └── type == 1 (이미지 블록) → bbox 기록 + 크롭
```

| 항목 | 내용 |
|------|------|
| 이미지 감지 | type==1 블록 bbox (래스터 이미지만, 벡터 차트 불가) |
| 텍스트 추출 | 페이지별 `get_text()` + `[pageN]` 마커 삽입 |
| 캡션 | 추출하지 않음 → STEP 5에서 LLM으로 생성 |

---

## STEP 3-CU — 이미지 / 텍스트 / 캡션 분리

`raw_response.json → result.contents[].markdown` 파싱

### 3-1. 이미지 추출

```python
for figure in result["figures"]:
    bbox = figure["boundingRegions"][0]["polygon"]
    page = figure["boundingRegions"][0]["pageNumber"]
    # PyMuPDF로 해당 페이지 렌더링 후 bbox 크롭
    # → img/fig_{page}_{idx}.png 저장
```

### 3-2. 본문 텍스트 추출

```
markdown 원본
    → <table>...</table> 제거
    → <figure>...</figure> 제거
    → <!-- PageBreak --> → [pageN] 마커로 변환
    → 나머지 HTML 주석 제거
    → $$...$$ / $...$ 수식 제거
    → 마크다운 heading(#) 기호 제거
    → 다중 공백 정리
    → content_raw.txt (STEP 5 LLM 정제 전 원본)
```

### 3-3. 캡션 추출

```python
# 1순위: <figcaption> 태그
fig_pat = re.compile(r'<figcaption>(.*?)</figcaption>', re.DOTALL)

# 2순위: raw_response.json의 figure.caption 필드
caption = figure.get("caption", {}).get("content", "")

# 3순위: 없으면 빈 문자열 → STEP 5에서 LLM 정제
```

**본문 혼입 캡션 감지 패턴:**

| 패턴 | 예시 |
|------|------|
| `\|` 구분자 포함 짧은 행 (≤ 100자) | `경복궁 근정전 \| 서울 종로` |
| `그림 N.` / `Figure N.` 시작 행 | `그림 1. 정규분포 곡선` |

감지된 혼입 캡션은 본문에서 제거 후 caption 목록으로 이동.

---

## STEP 4 — 이미지 후처리 (OpenCV) — CU 경로 전용

**참조:** `extract/content-understanding/cv/cv_refine_plan.md`

PyMuPDF 경로는 블록 단위 크롭이라 오탐 발생률이 낮으므로 CU 경로에만 적용.

### 오탐 유형 분류

| 유형 | 조건 | 처리 |
|------|------|------|
| **Type A** (페이지 전체 오탐) | bbox 면적 / 페이지 면적 ≥ 0.80 AND OpenCV 서브 블록 ≤ 1 | 서브 블록 0개: 폐기 / 1개: 해당 블록만 크롭 |
| **Type B** (복수 이미지 병합) | OpenCV 서브 블록 ≥ 2 AND 블록 간 갭 ≥ 이미지 높이 3% | 서브 이미지로 분리 크롭 |
| **Type C** (정상) | 위 조건 미해당 | 원본 유지 |

---

## STEP 5 — LLM 정제 및 목차 추출

**환경변수:** `OPEN_AI_ENDPOINT`, `OPEN_AI_KEY`, `OPEN_AI_DEPLOYMENT_NAME`

NLP 전처리 없이 LLM이 정제·생성·추출을 모두 담당한다.

### 5-1. 본문 텍스트 정제

```
입력: content_raw.txt (추출 직후 원본, [pageN] 마커 포함)
처리: LaTeX 오류 교정, OCR 노이즈 제거, 문장 정렬
출력:
  txt/content_paged.txt  ← [pageN] 마커 유지한 정제 텍스트
  txt/content.txt        ← [pageN] 마커 제거한 순수 텍스트
```

```
system: 당신은 한국어 교육 문서 편집 전문가입니다.
        LaTeX 수식 오류, OCR 잡음, 불필요한 특수문자를 교정하고
        자연스러운 문장 흐름으로 정리하세요. 내용은 변경하지 마세요.

user:   아래 텍스트를 정제해 주세요.
        [추출 원본 텍스트]
```

### 5-2. 캡션 정제 / 생성

**CU 경로 (정제):**
```
입력: 추출된 figcaption 텍스트
처리: 불완전 캡션 보완, OCR 오류 교정
출력: txt/caption.txt
```

**PyMuPDF 경로 (생성):**
```
입력: 크롭된 이미지 (base64)
처리: 이미지 내용 분석 → 한국어 캡션 생성
출력: txt/caption.txt
```

```
system: 당신은 교육 자료의 이미지를 설명하는 전문가입니다.

user:   아래 이미지의 내용을 간결하게 설명하는 캡션을 한 문장으로 작성해 주세요.
        [이미지 base64]
```

### 5-3. 목차 추출

```
입력: txt/content.txt (정제된 본문)
출력: txt/toc.txt
```

```
system: 당신은 한국어 교육 문서를 분석하는 전문가입니다.
        주어진 텍스트에서 문서의 핵심 목차 항목을 추출하세요.

user:   이 문서의 목차 항목을 5개에서 10개 사이로 추출해 주세요.
        번호와 제목만 간결하게 작성해 주세요.
        [정제된 본문 텍스트]
```

- 텍스트 최대 40,000자 제한

---

## 저장 파일 구조

### 기본 실행

```
result/{pdf이름}_v1/
├── raw_response.json         ← CU 경로만 (API 재호출 방지)
├── img/
│   ├── fig_1_1.png
│   ├── fig_7_2_cv_1.png      ← OpenCV 분리 이미지 (Type B, CU 경로)
│   └── ...
└── txt/
    ├── content.txt           ← 본문 텍스트 (순수 텍스트, 페이지 번호 없음)
    ├── content_paged.txt     ← 본문 텍스트 + 페이지 번호 ([pageN] 마커 포함)
    ├── toc.txt               ← 목차 (LLM 생성)
    └── caption.txt           ← 캡션 (페이지 번호 포함)
```

### `--debug` 실행 (중간 파일 추가)

```
result/{pdf이름}_v1/
├── raw_response.json
├── img/
├── txt/
│   ├── content_raw.txt       ← LLM 정제 전 추출 원본
│   ├── content.txt           ← 본문 텍스트 (순수 텍스트)
│   ├── content_paged.txt     ← 본문 텍스트 + 페이지 번호
│   ├── content_raw.md        ← API 마크다운 원본 (CU 경로만)
│   ├── toc.txt               ← 목차 (LLM 생성)
│   └── caption.txt           ← 캡션 (페이지 번호 포함)
└── meta/
    └── figures.json          ← 이미지 메타데이터
```

### `figures.json` 스키마

```json
[
  {
    "id": "1.1",
    "page": 1,
    "bbox": [140, 334, 770, 540],
    "img_path": "img/fig_1_1.png",
    "caption": "경복궁 근정전 | 서울 종로",
    "false_positive_type": null,
    "sub_crops": []
  },
  {
    "id": "7.2",
    "page": 7,
    "bbox": [12, 30, 980, 850],
    "img_path": "img/fig_7_2.png",
    "caption": "",
    "false_positive_type": "B",
    "sub_crops": [
      { "crop_idx": 1, "bbox": [12, 30, 980, 420], "img_path": "img/fig_7_2_cv_1.png", "caption": "..." },
      { "crop_idx": 2, "bbox": [12, 460, 980, 850], "img_path": "img/fig_7_2_cv_2.png", "caption": "" }
    ]
  }
]
```

---

## 파일 구성 및 개발 방식

### 개발 단계 — 스텝별 별도 파일

각 스텝을 독립 파일로 개발하여 단독 실행·검증 후 다음 스텝으로 진행.

```
pipeline_v2/
├── pipeline_v2.md          ← 이 문서
└── steps/
    ├── step_extract_cu.py  ← STEP 2-CU: CU API 추출
    ├── step_extract_mu.py  ← STEP 2-MU: PyMuPDF 추출
    ├── step_parse_cu.py    ← STEP 3-CU: 이미지/텍스트/캡션 분리
    ├── step_cv_refine.py   ← STEP 4: OpenCV 이미지 후처리
    └── step_llm.py         ← STEP 5: LLM 정제 및 목차 추출
```

### 통합 단계 — 최종 파이프라인 단일 파일

각 스텝 컨펌 완료 후 함수 단위로 `pipeline_v2.py`에 통합.

```
pipeline_v2/
├── pipeline_v2.py          ← 최종 통합 파일
│     def detect_scan()         # STEP 1
│     def step2_extract_cu()    # STEP 2-CU
│     def step2_extract_mu()    # STEP 2-MU
│     def step3_parse_cu()      # STEP 3-CU
│     def step4_cv_refine()     # STEP 4
│     def step5_llm()           # STEP 5
│     def main()
├── pipeline_v2.md
└── steps/                  ← 검증 완료 후 보존 또는 삭제
```

기존 코드 재사용:
- `extract/content-understanding/extract.py` → `step_extract_cu.py`
- `pipeline/pipeline_caption.py` → `step_parse_cu.py`

---

## 추출 방법별 특성 비교

| 항목 | Content Understanding | PyMuPDF |
|------|:---------------------:|:-------:|
| 적용 대상 | 스캔 PDF | 디지털 PDF |
| 이미지 bbox | ✅ (figure 감지) | ✅ (type==1 블록) |
| 벡터 차트 감지 | ✅ | ❌ |
| 캡션 추출 | ✅ (figcaption) | ❌ (LLM 생성) |
| API 비용 | 유료 | 무료 |
| 처리 속도 | ~30~90s (API 폴링) | ~1~5s |

---

## 미결 사항 및 주의사항

| 항목 | 상태 | 비고 |
|------|------|------|
| 본문 혼입 캡션 감지 | 미구현 | 패턴 기반 감지 + 수동 검토 필요 |
| OpenCV Type A/B 임계값 | 실험값 | 면적 비율 0.80, 갭 3% — 추가 테스트 필요 |
| 텍스트 40,000자 초과 처리 | 미구현 | 청크 분할 후 LLM 호출 고려 |
| PyMuPDF 캡션 생성 비용 | 미산정 | 이미지당 Vision LLM 1회 호출 |
| PyMuPDF 경로 벡터 차트 누락 | 미해결 | Excel/PowerPoint 계열 차트 등 벡터 그래픽은 type==1 블록으로 등록되지 않아 감지 불가. 통계기초.pdf 기준 23개 중 9개가 누락됨. 필요 시 CU 경로로 전환 고려 |
| Azure Blob Storage 저장 | 추후 | 현재는 로컬 저장 |

---

## 환경 설정

```bash
pip install python-dotenv openai pymupdf opencv-python pillow requests
```

**`.env` 위치:** `c:\Users\USER\ms-project3\preprocess\.env`

| 환경변수 | 용도 |
|----------|------|
| `CONTENT_UNDERSTANDING_ENDPOINT` | Azure CU API 엔드포인트 |
| `CONTENT_UNDERSTANDING_KEY` | Azure CU API 키 |
| `OPEN_AI_ENDPOINT` | Azure OpenAI 엔드포인트 |
| `OPEN_AI_KEY` | Azure OpenAI 키 |
| `OPEN_AI_DEPLOYMENT_NAME_4.1_MINI` | 배포 모델 이름 |

---

## 버전 관리 규칙

- 결과 폴더: `result/{pdf이름}_vN/` (N은 자동 증가)
- 같은 PDF를 재실행하면 새 버전 폴더 생성 (기존 결과 보존)
- `raw_response.json`은 이전 버전에서 자동 재사용 (CU 경로)

---

## 시도 기록

실행 로그는 각 결과 폴더의 `run_log.md`에 자동 저장됩니다.

```
result/{pdf이름}_vN/
└── run_log.md   ← 파이프라인 종료 시 자동 생성
```

과거 기록:
- [통계기초_v1/run_log.md](result/통계기초_v1/run_log.md) — 2026-06-15, 디지털, 이미지 14개
