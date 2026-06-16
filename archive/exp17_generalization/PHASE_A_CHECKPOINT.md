# exp17 Phase A checkpoint (pre-indexing STOP)

> 인덱싱은 아직 안 돌렸음. 확인 받기 전엔 extract_graph 진행 금지.

## 1. 코퍼스 정리 (deterministic, no LLM)

| | chars | lines | blank_lines |
|---|---|---|---|
| 원문 `input/ai_slides/AI_교안.txt` | 9603 | 648 | 323 |
| 정제 `input/ai_gyoan/AI_교안_정제.txt` | 9604 | 648 | 324 |

수행 작업: BOM 제거, CRLF/CR → LF 정규화, per-line rstrip, 연속 빈 줄 2개+ → 1개, 끝 빈 줄 제거. 글자 수 변화 +1자(끝 개행 보정). 발견된 노이즈: 0(하이픈 줄바꿈, 페이지번호, 연속 중복 라인 모두 없음). 반복되는 슬라이드 헤더는 슬라이드 경계라 보존.

OCR 자체가 이미 깨끗한 편: 비어 보이는 한 줄짜리 단락 사이마다 빈 줄 1개씩 들어 있는 더블 스페이스 포맷. 이걸 줄이지 않은 이유: 빈 줄을 살려두면 회랑의 regex 섹션 파서가 "blank-bounded short line" 으로 슬라이드 헤더를 잡을 수 있을지(Phase B에서 평가).

## 2. settings.yaml (이 디렉토리 기준)

확정 변경:
- `cluster_graph.use_lcc: true → false`
- `extract_graph_nlp:` 블록 통째로 제거 (LLM extract_graph 사용, 미사용 블록)
- `workflows:` 에서 `extract_covariates` 제거 (claims disabled). `create_communities`는 보존.
- `extract_graph.entity_types: [개념, 기법, 분포, 지표, 사례, 인물]` (단일 단어, 코퍼스 주제 맞춤)
- `extract_graph.prompt: "prompts/extract_graph.txt"` (이 프로젝트 루트의 로컬 폴더로 격리)
- `summarize_descriptions.prompt: "prompts/summarize_descriptions.txt"` (동일)
- 나머지(community_reports, search 류) 프롬프트 경로는 `../../prompts/` 그대로 (해당 워크플로 안 돌아 무해)

baseline(`<REPO>/prompts/`) 충돌 확인: 메인 `settings.yaml`이 `prompts/extract_graph.txt` 사용, exp9 `proj_pagesplit`도 `../prompts/extract_graph.txt`로 같은 폴더 사용. **exp17 로컬 폴더 `archive/exp17_generalization/prompts/`는 baseline과 겹치지 않음.** prompt-tune이 baseline을 덮어쓸 위험 0.

## 3. entity_types: 최종 6개

`개념, 기법, 분포, 지표, 사례, 인물`

- **개념**: 통계학, 모집단, 표본, 사건, 확률, 표본공간, 신뢰구간, 유의수준, 귀무가설, 대립가설, 상관관계, 추론, 추정 등.
- **기법**: 무작위 표본 추출, 층화 표본 추출, 가설 검정, 점추정, 구간추정, 상관분석, 적합도 검정, 분산 분석, t-검정, 카이제곱 검정 등.
- **분포**: 정규 분포, 베르누이 분포, 이항 분포, 푸아송 분포, 카이제곱 분포, t-분포, 균일 분포, 지수 분포 등.
- **지표**: 평균, 중앙값, 최빈값, 분산, 표준편차, 범위, 사분위수 범위, 왜도, 첨도, 피어슨 상관계수, P-value 등.
- **사례**: 동전 던지기, 제품 검수, 콜센터 전화 수, 임상 실험 진통제, 키-몸무게 등.
- **인물**: 강명호(저자) 그리고 본문에 직접 이름이 나오는 통계학자가 있다면 (Pearson/Spearman/Kendall는 영문 표기로 등장).

도구·시스템 카테고리 제외: 소프트웨어·도구 언급 없음(수식·이론 위주). 오류 유형(1종/2종 오류)·확률 변수 유형(이산/연속)은 "개념"으로 포섭.

## 4. max_gleanings

repro_run3 스냅샷 아카이브된 설정·로그(`results/snapshots/repro_run3/repro_run3_run.log`, `stats.json`, `repro_run3_results.json`)에서 `max_gleanings` 키 안 잡힘. 메인 `settings.yaml`은 `2`이지만 스냅샷이 실제 사용했다는 보증은 없음. **baseline 값 미확인, exp17은 GraphRAG 기본인 `1`로 설정.** Phase B에서 entity 수 차이 비교 시 참고.

## 5. prompt-tune 실행

명령: 
```
.venv/Scripts/python.exe -m graphrag prompt-tune --root . --no-discover-entity-types --domain "통계학 기초 강의 자료 (모집단·표본·확률 분포·가설 검정·상관분석)" --language Korean --output prompts --selection-method top --limit 2 --min-examples-required 2
```

`--limit 15`(기본) 으로는 코퍼스가 작아 `pandas sample n > population` 에러. `--selection-method top --limit 2`로 우회. 시드 안 박혔지만 top selection 이라 결정적.

`--domain`: `통계학 기초 강의 자료 (모집단·표본·확률 분포·가설 검정·상관분석)`. 이유: 도메인 자동 추론에 맡기지 말고 코퍼스 표지(통계 기초, 추정과 가설검정 상관분석, 확률 분포)를 그대로 명시.

생성 파일: `prompts/extract_graph.txt`, `prompts/summarize_descriptions.txt`, `prompts/community_report_graph.txt` (community_report는 워크플로에서 제외했으니 안 씀).

## 6. 생성된 extract_graph.txt 점검

도메인은 잘 잡힘: 예시 본문이 평균·중앙값·산포도 등 정제된 코퍼스 본문 그 자체. 기본 뉴스 예시 아님.

**entity_type 라벨이 settings.yaml의 6개 타입과 안 맞음** (점검 필요):

| 본문 | 라벨링 |
|---|---|
| 22개 entity decl 중 11개 | 영문 (`STATISTICAL MEASURE, CENTRAL TENDENCY`, `STATISTICAL MEASURE, DISPERSION`, `CONCEPT, STATISTICAL MEASURE`) |
| 11개 | 한글이지만 settings 외 어휘 (`통계지표, 중심경향 측정`, `통계지표, 산포도 측정`, `개념, 통계지표`) |
| settings 일치 | `개념`(loose), `지표`(loose via "통계지표")만 등장. `기법`, `분포`, `사례`, `인물` 0건 |

샘플:
```
("entity"<|>중심경향성<|>CONCEPT, STATISTICAL MEASURE<|>...)
("entity"<|>평균<|>STATISTICAL MEASURE, CENTRAL TENDENCY<|>...)
("entity"<|>중심경향성(CENTRAL TENDENCY)<|>개념, 통계지표<|>...)
("entity"<|>평균(MEAN)<|>통계지표, 중심경향 측정<|>...)
```

`extract_graph.txt`의 Steps 섹션에는 명시적 entity_types 목록이 없음(graphrag 기본 prompt가 그렇고, prompt-tune도 안 끼움). 실제 추출 때 모델은 examples를 보고 타입을 베끼는데, 그 examples 가 위처럼 영문·다른 한국어 어휘.

`summarize_descriptions.txt`도 자동 생성됨 (statistician persona, Korean output 지시). 무해.

## 7. 결정 필요 (사용자 확인)

prompt-tune이 도메인은 잘 잡았지만 **entity_types 라벨이 settings.yaml 6개와 안 맞음**. 진행 옵션:

(a) **그대로 진행**: settings.yaml의 `entity_types`가 다운스트림(entities.parquet의 type 컬럼 가공, 필요 시 community report)에 직접 쓰이는지에 의존. 예시 라벨이 영문/다른 한글이라도 추출 자체는 됨. type 컬럼이 settings 목록 외 값으로 채워질 가능성 큼.

(b) **examples 라벨만 수동 보정**: 생성된 `prompts/extract_graph.txt`의 두 example output 블록에서 entity_type 토큰만 6개 중 하나로 치환(예: `CONCEPT, STATISTICAL MEASURE` → `개념, 지표`). 본문·관계는 그대로. 결정적·검증 가능.

(c) **prompt-tune 재실행**: 코퍼스가 작아 selection 옵션 바꿔도 같은 결과 나올 가능성 크지만 `--n-subset-max`나 chunk-size 조정 가능. 권장 안 함.

내 추천은 (b). 라벨만 6개로 매핑하면 모델이 6개 안에 머무를 가능성이 높고 결정적임. 본문은 안 건드림.

## 8. 산출물

- `input/ai_gyoan/AI_교안_정제.txt` (정제된 코퍼스)
- `archive/exp17_generalization/clean_corpus.py` (결정적 정리 스크립트)
- `archive/exp17_generalization/cleanup_report.json` (정리 통계)
- `archive/exp17_generalization/settings.yaml` (exp17 설정)
- `archive/exp17_generalization/prompts/extract_graph.txt` (생성, 라벨 점검 필요)
- `archive/exp17_generalization/prompts/summarize_descriptions.txt` (생성)
- `archive/exp17_generalization/prompts/community_report_graph.txt` (생성, 안 씀)
- `archive/exp17_generalization/PHASE_A_CHECKPOINT.md` (이 보고서)

## 9. STOP

확인 받을 항목:
1. entity_types 6개 (`개념, 기법, 분포, 지표, 사례, 인물`) OK?
2. max_gleanings=1 OK? (baseline 미확인)
3. `--domain` 문구 OK?
4. **examples 라벨 처리** 어떻게 (a/b/c)?

확인 떨어지면 다음 단계(인덱싱+스냅샷 저장+regex 섹션 파서 평가)로 진행. 그 전에는 graphrag index 실행 안 함.
