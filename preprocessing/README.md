# 전처리 파이프라인 v2

PDF 문서에서 **본문 텍스트 / 목차 / 이미지 / 캡션**을 자동 추출하는 통합 파이프라인.

> 상세 설계 및 각 스텝별 구현 명세는 [pipeline_v2.md](pipeline_v2.md)를 참조하세요.

---

## 파이프라인 구조 요약

```
PDF 입력
  │
  ▼
[STEP 1] 스캔 / 디지털 판별
  │   문서 중간 2페이지 평균 글자 수 기준 (< 100자 → 스캔)
  │
  ├── 스캔 PDF ─────────────────────────────────────────┐
  │                                                     │
  └── 디지털 PDF                                         │
        │                                               │
        ▼                                               ▼
[STEP 2-MU] PyMuPDF 추출              [STEP 2-CU] Azure Content Understanding API 추출
  이미지: type==1 블록 bbox 크롭         (raw_response.json 캐시로 API 재호출 방지)
  텍스트: 페이지별 추출 + [pageN] 마커      │
  캡션: STEP 5에서 LLM 생성              ▼
        │                     [STEP 3-CU] 이미지 / 텍스트 / 캡션 분리
        │                       figure bbox 크롭, figcaption 추출
        │                               │
        ▼ ◄────────────────────────────┘
[STEP 4] 이미지 후처리 (OpenCV) ← CU 경로에만 적용
  Type A: 페이지 전체 오탐 → 폐기 또는 재크롭
  Type B: 복수 이미지 병합 → 서브 이미지 분리
        │
        ▼
[STEP 5] LLM 정제 및 목차 추출
  본문 텍스트 정제 (LaTeX 오류 · OCR 노이즈 교정)
  캡션 정제 / 생성 (CU: 정제, PyMuPDF: 이미지 기반 생성)
  목차 추출 → toc.txt
        │
        ▼
result/{pdf이름}_vN/
├── img/               ← 추출 이미지
├── txt/
│   ├── content.txt        ← 순수 본문 텍스트
│   ├── content_paged.txt  ← 페이지 번호 포함 본문
│   ├── toc.txt            ← 목차
│   └── caption.txt        ← 이미지 캡션
└── raw_response.json  ← CU 경로 캐시
```

| 경로 | 추출 방법 | 속도 | 비용 |
|------|-----------|------|------|
| 디지털 PDF | PyMuPDF | ~1–5s | 무료 |
| 스캔 PDF | Azure CU API | ~30–90s | 유료 |

---

## 파일 구성

```
pipeline_v2/
├── pipeline_v2.py          ← 메인 실행 파일
├── pipeline_v2.md          ← 상세 설계 문서
├── steps/                  ← 스텝별 개발/검증 파일
│   ├── step1_detect.py
│   ├── step2_extract_cu.py
│   ├── step2_extract_mu.py
│   ├── step3_parse_cu.py
│   └── step5_llm.py
└── result/                 ← 실행 결과 (자동 생성)
    └── {pdf이름}_vN/
```

---

## 환경 설정

### 1. 패키지 설치

```bash
pip install python-dotenv openai pymupdf opencv-python pillow requests
```

### 2. 환경변수 설정

프로젝트 루트의 `.env` 파일(`c:\Users\USER\ms-project3\preprocess\.env`)에 아래 항목을 설정합니다.

```env
# Azure Content Understanding (스캔 PDF 처리용)
CONTENT_UNDERSTANDING_ENDPOINT=https://...
CONTENT_UNDERSTANDING_KEY=...

# Azure OpenAI (LLM 정제용)
OPEN_AI_ENDPOINT=https://...
OPEN_AI_KEY=...
OPEN_AI_DEPLOYMENT_NAME_4.1_MINI=...
```

> 디지털 PDF만 처리하는 경우 CU 환경변수는 불필요합니다.

---

## 실행 방법

### 기본 실행

```bash
# pipeline_v2/ 폴더에서 실행
python pipeline_v2.py --pdf "../data/raw/통계기초.pdf"
```

### 디버그 모드 (중간 파일 포함 저장)

```bash
python pipeline_v2.py --pdf "../data/raw/통계기초.pdf" --debug
```

디버그 모드에서는 다음 파일이 추가로 저장됩니다.

| 파일 | 내용 |
|------|------|
| `txt/content_raw.txt` | LLM 정제 전 추출 원본 |
| `txt/content_raw.md` | API 마크다운 원본 (CU 경로만) |
| `meta/figures.json` | 이미지 메타데이터 |

### PDF 유형 수동 지정

자동 판별이 부정확할 경우 `--scan` 플래그로 강제 지정합니다.

```bash
# 스캔 PDF로 강제 지정 (CU API 사용)
python pipeline_v2.py --pdf "../data/raw/문서.pdf" --scan
```

---

## 출력 구조

```
result/{pdf이름}_vN/
├── img/
│   ├── fig_1_1.png
│   ├── fig_7_2_cv_1.png   ← OpenCV 분리 이미지 (Type B)
│   └── ...
├── txt/
│   ├── content.txt        ← 순수 본문 텍스트 (페이지 번호 없음)
│   ├── content_paged.txt  ← 본문 + [pageN] 마커
│   ├── toc.txt            ← 목차 (5–10개 항목)
│   └── caption.txt        ← 이미지별 캡션
├── raw_response.json      ← CU API 응답 캐시 (CU 경로만)
└── run_log.md             ← 실행 로그
```

> 같은 PDF를 재실행하면 새 버전 폴더(`_v2`, `_v3`, ...)가 생성되어 기존 결과가 보존됩니다.
> CU 경로는 이전 버전의 `raw_response.json`을 자동으로 재사용합니다.

---

## 주의사항

- PyMuPDF 경로는 **벡터 그래픽(차트 등)을 감지하지 못합니다.** 벡터 차트가 많은 문서는 `--scan` 플래그로 CU 경로를 사용하세요.
- LLM 정제 시 본문이 40,000자를 초과하면 현재 버전에서는 잘립니다.
- OpenCV 후처리 임계값(면적 비율 0.80, 갭 3%)은 실험적 값으로, 문서 유형에 따라 오탐이 발생할 수 있습니다.
