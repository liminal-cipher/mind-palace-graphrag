# 전처리 파이프라인 v2

PDF 문서에서 **본문 텍스트 / 목차 / 이미지 / 캡션**을 자동 추출하는 통합 파이프라인.

> 상세 설계 및 각 스텝별 구현 명세는 [pipeline_v2.md](pipeline_v2.md)를 참조하세요.

---

## 최종 산출물

| 종류 | 위치 |
| --- | --- |
| 이미지 | `img/` 폴더 |
| 캡션 | `txt/caption.txt` |
| 텍스트 | `txt/content_paged.txt` |
| 목차 | `txt/toc.txt` |

---

## 파이프라인 구조 요약

```
PDF 입력
  │
  ▼
[STEP 1] 스캔 / 디지털 판별  (중간 2페이지 평균 글자수 < 100 → 스캔)
  │
  ├── 스캔 PDF ──────────────────────────────────────────┐
  │                                                      │
  └── 디지털 PDF                                          │
        │                                                ▼
        ▼                              [STEP 2-CU] Azure Content Understanding API
[STEP 2-MU] PyMuPDF 추출                 (무수식 분석기 · raw_response.json 캐시)
  이미지: type==1 블록 크롭                       │
  텍스트: 페이지별 + [pageN]                       ▼
  캡션: STEP 5에서 생성             [STEP 3-CU] 이미지/텍스트/캡션 분리
        │                            로고 figure 제외 · bbox 크롭
        │                            캡션 → figure 페이지 단위 매칭
        │                                        │
        │                                        ▼
        │                          [STEP 4] 이미지 후처리 (doclayout-yolo) ← CU 전용
        │                            객체 0 폐기 / 1 재크롭 / N 분리
        │                            분리 자식 캡션 vision 전사
        ▼ ◄──────────────────────────────────────┘
[STEP 5] LLM 정제 및 목차 추출
  본문 정제 (OCR/수식 교정)
  캡션: 추출분 충실 정제(temp=0) / 빈 캡션 이미지 생성
  목차 추출 → toc.txt
        │
        ▼
result/{pdf이름}_vN/  (img/ · txt/ · meta/figures.json · run_log.md · raw_response.json[CU])
```

| 경로       | 추출 방법    | 이미지 후처리 | 속도(예) | 비용 |
| ---------- | ------------ | ------------- | -------- | ---- |
| 디지털 PDF | PyMuPDF      | —             | ~40s     | 무료 |
| 스캔 PDF   | Azure CU API | doclayout-yolo| ~175s    | 유료 |

---

## 파일 구성

```
pipeline_v2/
├── pipeline_v2.py          ← 메인 실행(오케스트레이터, steps/ 를 import)
├── pipeline_v2.md          ← 상세 설계 문서
├── README.md               ← 이 문서
├── step4_plan.md           ← STEP 4 설계/결정 기록
├── steps/                  ← 스텝별 구현 (단일 진실원본)
│   ├── step1_detect.py
│   ├── step2_extract_cu.py
│   ├── step2_extract_mu.py
│   ├── step3_parse_cu.py
│   ├── step4_cv_refine.py
│   ├── step5_llm.py
│   ├── _layout.py          ← doclayout-yolo 래퍼
│   ├── _oai.py             ← 공용 Azure OpenAI 헬퍼
│   └── manage_analyzer.py  ← CU 분석기 관리
└── result/                 ← 실행 결과 (자동 생성)
    └── {pdf이름}_vN/
```

> `pipeline_v2.py` 는 steps/ 의 함수를 import 한다. 실행 시 `steps/` 디렉토리가 함께 있어야 한다.

---

## 환경 설정

### 1. 패키지 설치

```bash
pip install python-dotenv openai pymupdf pillow requests \
            doclayout-yolo torch huggingface_hub
```

> 스캔 PDF 후처리(STEP 4)는 `doclayout-yolo` · `torch`(CPU 가능) · `huggingface_hub` 가 필요합니다.
> 가중치는 최초 1회 자동 다운로드됩니다. 디지털 PDF만 처리하면 이 패키지들은 불필요합니다.

### 2. 환경변수 설정

프로젝트 루트의 `.env`(`c:\Users\USER\ms-project3\preprocess\.env`)에 설정합니다.

```env
# Azure Content Understanding (스캔 PDF)
CONTENT_UNDERSTANDING_ENDPOINT=https://...
CONTENT_UNDERSTANDING_KEY=...
CONTENT_UNDERSTANDING_API_VER=2024-12-01-preview   # figure bbox 반환 버전

# Azure OpenAI (LLM 정제/캡션)
OPEN_AI_ENDPOINT=https://...
OPEN_AI_KEY=...
OPEN_AI_DEPLOYMENT_NAME_4.1_MINI=...   # 텍스트 정제(본문·캡션)
OPEN_AI_DEPLOYMENT_NAME_4O=...         # 비전(캡션 전사/생성)
# OAI_MAX_WORKERS=6                     # (선택) STEP 5 병렬 요청 수
```

> 디지털 PDF만 처리하는 경우 CU 환경변수는 불필요합니다.

---

## 실행 방법

```bash
# pipeline_v2/ 폴더에서 실행
python pipeline_v2.py --pdf "../data/raw/통계기초.pdf"      # 디지털
python pipeline_v2.py --pdf "../data/raw/국사교과서.pdf"    # 스캔(자동 판별)
python pipeline_v2.py --pdf "../data/raw/문서.pdf" --scan   # 스캔 강제
python pipeline_v2.py --pdf "../data/raw/통계기초.pdf" --debug
```

디버그 모드 추가 산출물:

| 파일 | 내용 |
| --- | --- |
| `txt/content_raw.txt` | LLM 정제 전 추출 원본 |
| `txt/content_raw.md` | API 마크다운 원본 (CU 경로) |
| `txt/caption_raw.txt` | 매칭 전 캡션 목록 (CU 경로) |
| `meta/step4_debug/` | STEP 4 검출 박스 시각화 (CU 경로) |

> `meta/figures.json` 은 `--debug` 없이도 항상 저장됩니다(스텝 간 핸드오프).

---

## 출력 구조

```
result/{pdf이름}_vN/
├── img/
│   ├── fig_1_2.png
│   ├── fig_23_2_cv_1.png   ← STEP 4 분리 이미지(독립 figure)
│   └── ...
├── txt/
│   ├── content.txt        ← 순수 본문 텍스트 (페이지 번호 없음)
│   ├── content_paged.txt  ← 본문 + [pageN] 마커
│   ├── toc.txt            ← 목차 (5–10개 항목)
│   └── caption.txt        ← 이미지별 캡션 ([page N] 포함)
├── meta/figures.json      ← 이미지/캡션 메타데이터
├── raw_response.json      ← CU API 응답 캐시 (CU 경로만)
└── run_log.md             ← 실행 로그
```

> 같은 PDF를 재실행하면 새 버전 폴더(`_v2`, `_v3`, ...)가 생성되어 기존 결과가 보존됩니다.
> CU 경로는 이전 버전의 `raw_response.json` 을 자동 재사용합니다(분석기 설정을 바꿔 새로
> 추출하려면 기존 `raw_response.json` 들을 비켜두고 실행).

---

## 주의사항

- **스캔 PDF는 `2024-12-01-preview` CU 버전 + `enableFormula=False` 분석기**(`pdf-content-extractor-noform`)를 사용합니다.
  버전이 다르면 figure bbox가 반환되지 않아 크롭이 불가합니다. 분석기 설정 변경 시 `steps/manage_analyzer.py` 로 재생성하세요.
- **PyMuPDF 경로는 벡터 그래픽(차트 등)을 감지하지 못합니다.** 벡터 차트가 많은 문서는 `--scan` 으로 CU 경로를 쓰세요.
- doclayout-yolo는 **사진 위에 겹친 인셋이나 전면 bleed 사진**을 구조적으로 잘 분리하지 못해 일부 캡션이 누락될 수 있습니다.
- 일부 캡션은 CU OCR 단계에서 아예 누락되어, 해당 figure는 STEP 5에서 이미지 기반으로 캡션이 생성됩니다.
```
