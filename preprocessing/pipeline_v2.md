# 전처리 파이프라인 v2 구현 명세서

> ⚠️ **수정 원칙**: 기능 변경·실험은 먼저 `steps/` 의 개별 스텝 파일에서 진행하고 검증한다.
> `pipeline_v2.py` 는 **steps/ 의 함수를 import 하는 얇은 오케스트레이터**이므로,
> steps/ 를 고치면 통합본에도 자동 반영된다(별도 복제·동기화 불필요).

## 개요

PDF 문서를 입력받아 **본문 텍스트 / 목차 / 이미지 / 캡션**을 추출·전처리해
GraphRAG 입력용 산출물을 만드는 통합 파이프라인.

- 스캔 PDF: Azure Content Understanding(CU) API 경로
- 디지털 PDF: PyMuPDF 경로
- 이미지 후처리(STEP 4)는 **문서 레이아웃 검출 모델(doclayout-yolo)** 사용 (CU 경로 전용)
- 텍스트·캡션 정제는 LLM(Azure OpenAI)이 담당

**입력:** PDF 파일 경로   **출력:** `result/{pdf이름}_vN/` 폴더

```bash
python pipeline_v2.py --pdf "../data/raw/통계기초.pdf"
python pipeline_v2.py --pdf "../data/raw/국사교과서.pdf" --scan
python pipeline_v2.py --pdf "../data/raw/국사교과서.pdf" --debug
```

---

## 파이프라인 구조

```
PDF 입력
  │
  ▼
[STEP 1] 스캔 / 디지털 판별 (PyMuPDF, 중간 2페이지 평균 글자수 < 100 → 스캔)
  │
  ├──── 스캔 PDF ─────────────────────────────────────────┐
  │                                                       │
  └──── 디지털 PDF                                         │
           │                                              │
           ▼                                              ▼
  [STEP 2-MU] PyMuPDF 추출                  [STEP 2-CU] CU API 추출
    이미지: type==1 블록 bbox 크롭            raw_response.json 캐시(재호출 스킵)
    텍스트: 페이지별 + [pageN]                무수식 분석기(enableFormula=False)
    캡션: STEP 5에서 생성                     │
           │                                  ▼
           │                        [STEP 3-CU] 이미지/텍스트/캡션 분리
           │                          - 헤더/꼬리말 로고 figure 제외
           │                          - figure bbox(source) 크롭
           │                          - 본문 텍스트 추출(+캡션/푸터 분리)
           │                          - 캡션 → figure 페이지 단위 매칭
           │                                  │
           │                                  ▼
           │                        [STEP 4] 이미지 후처리 (doclayout-yolo) ← CU 전용
           │                          면적비 게이트(0.10) 통과분만 모델 추론
           │                          객체 0 폐기 / 1 재크롭 / N 분리(독립 figure 승격)
           │                          분리 자식 ↔ figure_caption 박스 매칭→vision 전사
           ▼ ◄───────────────────────────────┘
  [STEP 5] LLM 정제 및 목차 추출
    본문 정제(OCR/수식 교정) → content.txt / content_paged.txt
    캡션: caption_done 보존 / 추출분 충실 정제(temp=0) / 빈 캡션 이미지 생성
          (디지털 생성 캡션은 수식 유니코드화)
    목차 추출 → toc.txt
           │
           ▼
결과 저장  result/{pdf이름}_vN/  (img/ · txt/ · meta/figures.json · run_log.md · raw_response.json[CU])
```

---

## STEP 1 — 스캔 / 디지털 판별  (`steps/step1_detect.py`)

| 판단 기준 | 값 |
|-----------|-----|
| 검사 페이지 | 문서 중간 2장 (`len(doc)//2`, `+1`) |
| 글자 수 임계값 | 평균 100자 미만 → 스캔 |
| 라이브러리 | PyMuPDF (`fitz`) |

- 표지·목차 편향 없이 문서 중간을 대표로 사용, 2장 평균으로 단일 이상치 완화
- `--scan` 으로 수동 강제 지정 가능
- 통합 파이프라인에서 판별 결과(`is_scan`)는 STEP 5까지 전달된다
  (단계별 단독 실행 시 step5는 `--scan` 플래그로만 스캔 여부를 안다)

---

## STEP 2-CU — Content Understanding API 추출 (스캔)  (`steps/step2_extract_cu.py`)

- Azure AI Content Understanding API (`2024-12-01-preview`)
- **Analyzer ID: `pdf-content-extractor-noform`** — `enableFormula=False` 로 생성
  - 한글 캡션을 LaTeX 수식(`$\lambda…$`)으로 오인식하는 문제 방지
    (예: '시호'가 `$\lambda | \widetilde{\bar{\mathcal{G}}}$` 로 잘못 읽히던 현상 제거)
  - 분석기 설정 변경 시 기존 분석기를 지우고 재생성해야 반영됨 →
    `steps/manage_analyzer.py --list / --delete <id>`
- 환경변수: `CONTENT_UNDERSTANDING_ENDPOINT`, `CONTENT_UNDERSTANDING_KEY`, `CONTENT_UNDERSTANDING_API_VER`
- **캐시 전략:** 동일 PDF의 `result/{stem}_vN/raw_response.json` 중 apiVersion이 일치하는 것을
  자동 재사용(API 재호출 스킵). 분석기/설정을 바꿔 새로 뽑으려면 기존 raw 들을 비켜두고 실행.

### ⚠️ API 버전과 figure bbox 반환 (중요)

STEP 3-CU 의 이미지 크롭은 응답의 **`result.contents[].figures[].source`** 필드
(예: `D(1,0.453,0.0767,...)`, 인치 좌표)에 전적으로 의존한다. 이 필드는 API 버전에 따라 반환 여부가 갈린다.

| api-version | `figures[].source` (bbox) | markdown 이미지 표기 | 비고 |
|-------------|:--:|------|------|
| `2024-12-01-preview` | ✅ 반환 | `<figure>...</figure>` | **bbox 크롭 가능 → 이 버전 사용** |
| `2025-11-01` | ❌ 미반환 | `![](figures/N.M)` | 크롭 불가 |

**버전별 요청 형식도 다르다**(버전만 바꾸면 깨짐):

| 항목 | `2024-12-01-preview` | `2025-11-01` |
|------|------|------|
| 분석기 생성 | `scenario:"document"` + `config:{returnDetails, enableOcr, enableLayout, enableFormula:false}` | `baseAnalyzerId:"prebuilt-document"` |
| analyze 제출 | `Content-Type: application/pdf` + raw 바이너리 | `application/json` + `{"inputs":[{"data":"base64"}]}` |
| 결과 조회 | 응답 헤더 `Operation-Location` GET 폴링 (공통) | 동일 |

---

## STEP 2-MU — PyMuPDF 추출 (디지털)  (`steps/step2_extract_mu.py`)

| 항목 | 내용 |
|------|------|
| 이미지 감지 | `get_text("dict")` 의 type==1 블록 bbox (래스터만, 벡터 차트 불가) |
| 텍스트 추출 | 페이지별 `get_text()` + `[pageN]` 마커 |
| 캡션 | 추출 안 함 → STEP 5에서 이미지 기반 생성 |
| 산출 | `txt/content_raw.txt`, `img/`, `meta/figures.json`(항상 저장) |

---

## STEP 3-CU — 이미지 / 텍스트 / 캡션 분리  (`steps/step3_parse_cu.py`)

### 3-1. 이미지 크롭
- `figures[].source` 의 `D(page,x0,y0,…)` 인치 좌표 → PyMuPDF 페이지 렌더 후 크롭 → `img/fig_{page}_{idx}.png`
- **헤더/꼬리말 로고 제외**: figure 가 참조하는 paragraph 의 role 이 전부 `pageHeader`/`pageFooter` 이면
  본문 이미지가 아니므로 건너뜀(매 페이지 반복되는 기관 로고 등 ~50개 제거).

### 3-2. 본문 텍스트
- `<table>` / `<figure>` 제거, `<!-- PageBreak -->` → `[pageN]`, 주석·수식·heading 정리 → `content_raw.txt`
- 본문에 흘러든 캡션(`주제 | 시·도 설명` 패턴)은 추출해 캡션 풀로 보내고 본문에서 제거

### 3-3. 캡션 → figure 매칭 (핵심)
캡션 출처는 셋이며 우선순위·중복 처리가 있다.

1. **`figures[].caption`** (CU 구조화 캡션) — figure 에 직접 결합돼 가장 신뢰도 높음. 1순위로 사용.
2. **`<figcaption>` 마크다운** + **본문 캡션**(`| 시·도`) — 문서 위치 순서로 페이지별 풀 구성.
3. **페이지 단위 매칭**: figure.caption 이 없는 figure 에 한해, **같은 페이지의 미사용 캡션**을 위→아래로 배정
   (전역 순서 매칭이 유발하던 페이지 간 오배정 제거).

추가 처리:
- **중복 제거**: figure.caption 과 동일한 텍스트가 `<figcaption>` 으로 풀에도 있으면 제외
- **푸터 스트립**: 캡션 끝에 붙은 러닝푸터(`쪽번호 + 로마자 단원기호 + 단원명`) 제거
- **병합 캡션 분리**: 한 figure.caption 에 `… | 시·도 …` 형태의 별개 캡션이 `\n` 으로 묶여 있으면,
  첫 캡션만 남기고 떼어낸 캡션을 같은 페이지의 빈 figure 로 배정
  (작가표기 `| 김홍도` 등은 제외 → STEP 4 이미지 분리 로직과 충돌 방지)
- `meta/figures.json` 은 **항상 저장**(STEP 4·5로 넘기는 필수 핸드오프)

---

## STEP 4 — 이미지 후처리 (레이아웃 모델)  (`steps/step4_cv_refine.py`, `_layout.py`)

CU 가 크롭한 figure 의 오탐을 **doclayout-yolo** 로 정제한다. (PyMuPDF 경로는 블록 단위라 적용 안 함)

- 모델: `juliozhao/DocLayout-YOLO-DocStructBench` / 가중치 `doclayout_yolo_docstructbench_imgsz1024.pt`
  (HF 최초 1회 자동 다운로드 후 캐시, `imgsz=1024` · `conf=0.2`)
- **면적비 게이트(`DEFAULT_AREA_THR=0.10`)**: bbox면적/페이지면적 < 0.10 이면 모델 호출을 건너뛰고 그대로 통과
  (작은 잡동사니는 스킵해 속도 확보, 게이트 아래는 폐기하지 않음)
- crop 안에서 figure 객체를 검출해 **개수로 분기**:

| 검출 수 | 처리 | `false_positive_type` |
|--------|------|:--:|
| 0개 | 폐기 (파일 삭제 + figures 제외) | A |
| 1개 | 해당 박스로 재크롭(원본 덮어쓰기) | A |
| N개 | 각 박스를 **독립 figure 로 승격 분리**(부모 폐기, id `{부모}_cv_{i}`) | B |

- `_cleanup`: 겹침/포함 박스 정리. 큰 박스가 작은 박스들 합집합 밖에 고유 영역(≥25%)을 가지면
  **잔여 밴드를 별개 사진으로 유지**(아래 가로 bleed 사진 복구), 아니면 병합 오탐으로 제거.
- **캡션 연계(분리 자식)**: 모델이 함께 내는 `figure_caption` 박스를 자식 figure 에 위치 매칭 →
  해당 영역을 **vision LLM(gpt-4o)으로 전사** → `caption` + `caption_done=True`(STEP 5에서 정제 스킵).
  매칭 실패 시 부모 figcaption 을 줄 단위로 상속(없으면 빈 값 → STEP 5 생성).

> 한계: 사진 위에 겹친 인셋, 캡션 자체 미인식 등은 모델/CU 차원의 한계로 일부 누락될 수 있음.

---

## STEP 5 — LLM 정제 및 목차 추출  (`steps/step5_llm.py`, `_oai.py`)

- 텍스트 모델 `OPEN_AI_DEPLOYMENT_NAME_4.1_MINI`, 비전 모델 `OPEN_AI_DEPLOYMENT_NAME_4O`
- 본문/캡션은 페이지·figure 단위로 **병렬 처리**(`OAI_MAX_WORKERS`, 기본 6)

### 5-1. 본문 정제
- `content_raw.txt` → 페이지 단위 정제(OCR 잡음·깨진 수식 복원, 줄바꿈 정리; `[pageN]` 마커는 코드가 재부착)
- 출력: `content_paged.txt`([pageN] 유지) / `content.txt`(마커 제거)

### 5-2. 캡션 정제 / 생성  (`_process_caption`)
- 캡션의 줄바꿈/연속 공백은 단일 공백으로 정규화
- `caption_done=True`(STEP 4 전사) → **그대로 보존**
- 스캔 + 캡션 있음 → **충실 정제**(`_refine_caption`, **temperature=0**)
  - 띄어쓰기·명백한 오탈자만 교정. 재서술·요약·축약·완성·말투변경·삭제 **금지**
  - 단, 순서가 뒤바뀐 문장 조각은 **재배열만** 허용(단어 변경·추가·삭제 없이)
- 스캔 + 캡션 빈 값 → 이미지로 **생성 폴백**(`_generate_caption`, 수식 규칙 미적용)
- 디지털 → 모든 figure **이미지 생성**(`math_unicode=True`: 수식을 LaTeX 대신 유니코드 평문 σ μ ² ₁ √ 로)
- 출력: `txt/caption.txt`([page N] 포함)

### 5-3. 목차 추출
- `content.txt` 앞부분 → 핵심 목차 5~10개 → `txt/toc.txt`

---

## 저장 파일 구조

```
result/{pdf이름}_vN/
├── raw_response.json         ← CU 경로만 (API 재호출 방지)
├── img/                      ← 이미지 (fig_{p}_{i}.png, 분리: fig_{p}_{i}_cv_{k}.png)
├── txt/
│   ├── content.txt           ← 본문 (순수, 페이지번호 없음)
│   ├── content_paged.txt     ← 본문 + [pageN]
│   ├── toc.txt               ← 목차
│   └── caption.txt           ← 캡션 ([page N] 포함)
├── meta/
│   └── figures.json          ← 이미지/캡션 메타 (항상 저장)
└── run_log.md                ← 실행 로그
```

`--debug` 추가 산출: `txt/content_raw.txt`, `txt/content_raw.md`, `txt/caption_raw.txt`, `meta/step4_debug/`(검출 박스 이미지)

### `figures.json` 스키마

```json
[
  {
    "id": "1.2",
    "page": 1,
    "bbox_inch": [0.34, 0.47, 7.99, 11.33],
    "img_path": "img/fig_1_2.png",
    "caption": "경복궁 근정전 | 서울 종로 조선은 건국 후 한양을 …",
    "false_positive_type": null,
    "sub_crops": []
  },
  {
    "id": "23.2_cv_1",
    "page": 23,
    "bbox_inch": [...],
    "img_path": "img/fig_23_2_cv_1.png",
    "caption": "행주 산성 충장사 | 경기 고양 …",
    "false_positive_type": "B",
    "caption_done": true,
    "sub_crops": []
  }
]
```

- `bbox_inch`: 인치 좌표(분리 자식은 부모 crop 기준 재계산)
- `false_positive_type`: STEP 4 처리 표식 (`A`=폐기/재크롭, `B`=분리 자식, `null`=게이트 통과/원본)
- `caption_done`: STEP 4에서 vision 전사 완료(STEP 5 정제 스킵). 분리 자식은 독립 figure 로 승격되며,
  `sub_crops` 는 사용하지 않는다(잔존 필드).

---

## 파일 구성

```
pipeline_v2/
├── pipeline_v2.py          ← 오케스트레이터 (steps/ 함수 import + 배선·버전폴더·로그)
├── pipeline_v2.md          ← 이 문서
├── README.md               ← 사용 안내
├── step4_plan.md           ← STEP 4 설계/결정 기록
└── steps/
    ├── step1_detect.py     ← STEP 1 스캔/디지털 판별
    ├── step2_extract_cu.py ← STEP 2-CU CU API 추출
    ├── step2_extract_mu.py ← STEP 2-MU PyMuPDF 추출
    ├── step3_parse_cu.py   ← STEP 3-CU 이미지/텍스트/캡션 분리·매칭
    ├── step4_cv_refine.py  ← STEP 4 이미지 후처리(레이아웃 모델)
    ├── step5_llm.py        ← STEP 5 LLM 정제·캡션·목차
    ├── _layout.py          ← doclayout-yolo 래퍼(검출·cleanup·캡션 매칭)
    ├── _oai.py             ← 공용 Azure OpenAI 헬퍼(+ read_caption 전사)
    ├── _cv.py              ← 휴리스틱 CV(초기 실험, 현재 미사용)
    └── manage_analyzer.py  ← CU 분석기 목록/삭제(설정 변경 시)
```

각 스텝은 단독 실행도 지원(예시는 파일 상단 docstring 참조).

---

## 추출 방법별 특성 비교

| 항목 | Content Understanding (스캔) | PyMuPDF (디지털) |
|------|:----:|:----:|
| 이미지 bbox | ✅ figure source | ✅ type==1 블록 |
| 벡터 차트 감지 | ✅ | ❌ |
| 캡션 | ✅ 추출 + STEP 4 전사 | ❌ → 이미지 생성 |
| 이미지 후처리(STEP 4) | ✅ doclayout-yolo | — |
| API 비용 | 유료 | 무료 |
| 처리 속도(예) | ~175s (모델·LLM 포함) | ~40s |

---

## 환경 설정

```bash
pip install python-dotenv openai pymupdf pillow requests \
            doclayout-yolo torch huggingface_hub
```

> STEP 4(doclayout-yolo)는 `torch`(CPU 가능)·`huggingface_hub` 필요. 디지털 PDF만 처리하면 CU·STEP 4 관련 패키지는 불필요.

**`.env` 위치:** `c:\Users\USER\ms-project3\preprocess\.env`

| 환경변수 | 용도 |
|----------|------|
| `CONTENT_UNDERSTANDING_ENDPOINT` / `_KEY` | Azure CU API |
| `CONTENT_UNDERSTANDING_API_VER` | CU API 버전 (**`2024-12-01-preview`** — bbox 반환) |
| `OPEN_AI_ENDPOINT` / `OPEN_AI_KEY` | Azure OpenAI |
| `OPEN_AI_DEPLOYMENT_NAME_4.1_MINI` | 텍스트 정제 모델(본문·캡션) |
| `OPEN_AI_DEPLOYMENT_NAME_4O` | 비전 모델(캡션 전사/생성) |
| `OAI_MAX_WORKERS` | STEP 5 병렬 요청 수 (선택, 기본 6 — 429 시 감소) |

---

## 버전 관리 / 미결 사항

- 결과 폴더 `result/{pdf이름}_vN/` 자동 증가, 재실행 시 기존 결과 보존
- `raw_response.json` 은 이전 버전에서 자동 재사용(CU 경로)

| 항목 | 상태 | 비고 |
|------|------|------|
| 본문 텍스트 40,000자 초과 | 부분 | 문단 단위 분할 후 LLM 호출(`_split_by_size`) |
| 사진 위 인셋·전면 bleed 분리 | 한계 | doclayout-yolo 가 인셋/합성을 구조적으로 못 잡음(일부 누락 수용) |
| CU 미인식 캡션 | 한계 | 일부 캡션은 CU OCR 단계에서 누락 → 비전 재판독 필요(미적용) |
| PyMuPDF 벡터 차트 누락 | 미해결 | type==1 블록 밖 벡터 그래픽 감지 불가 |
| Azure Blob 저장 | 추후 | 현재 로컬 저장 |
