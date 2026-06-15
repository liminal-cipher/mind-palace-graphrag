# ai_school canary 진단: 국사 튜닝 파이프라인의 새 도메인 일반화

날짜: 2026-06-12
입력: `input/ai_school/ai_school.txt` (통계 기초 교안, 슬라이드 추출 텍스트, 9,604자)
비교 기준: korean_history (조선 전기, repro_run3 스냅샷)
커밋 안 함. 국사 canonical 미변경(아래 확인 섹션).

## 한 줄 결론

LLM이 도메인 라벨로 구동되는 단계(TOC, Stage A 루브릭, Stage B keep/demote)는 통계 도메인에 깨끗하게 적응했다. 깨진 곳은 전부 국사 데이터 모양에 맞춰 박아둔 결정적/문자열 단계다: (1) export가 제목 정규화 충돌로 하드 크래시 → `ai_school.palace.json` 생성 실패(파이프라인 끝까지 못 감), (2) 국사용 entity_types 화이트리스트가 통계엔 무의미해 type이 66종으로 폭발, (3) 슬라이드 이중언어 글로스와 반복 헤더 때문에 같은 개념이 두 엔티티로 중복 추출되고 char-overlap 방 배정이 흔들림.

## 파이프라인 진행 상태

| 단계 | 결과 | 산출물 |
|---|---|---|
| 1. 인덱싱 | 완료 | `results/snapshots/ai_school/` (엔티티 121, 관계 101, 커뮤니티 5) |
| 2a. TOC | 완료, 깨끗 | `palace/tests/runs/ai_school/ai_school.toc_llm.json` (6 섹션) |
| 2b. phase_rooms | 완료, 단 빈 방 2개로 6→4 축소 | `palace/tests/runs/ai_school/ai_school.json` |
| 2c. export | 크래시(SystemExit) | `ai_school.palace.json` 생성 안 됨 |
| 3. match_images | 입력 없음(figure 0) | 스킵 |

산출물(추가만, 추적 안 함):
- `proj_ai_school/settings.yaml` (인덱싱 스코프용 별도 root)
- `palace/configs/ai_school.json`
- `results/snapshots/ai_school/` (스냅샷)
- `palace/tests/runs/ai_school/ai_school.{toc_llm.json,json}`
- `output/ai_school/`, `cache/ai_school/`, `cache/palace/ai_school/`, `logs/ai_school_*` (gitignore 영역)

## 1. 인덱싱

repro_run3를 만든 root `settings.yaml`을 그대로 본떠 `proj_ai_school/settings.yaml`로 적용(같은 모델 gpt-4.1-mini 추출 + text-embedding-3-small, 같은 청킹 size=1200/overlap=100, max_cluster_size=15, use_lcc=true, 전체 워크플로). 입력·출력 경로만 ai_school용으로 분리해 국사 산출물과 격리.

결과: 엔티티 121, 관계 101, 커뮤니티 5개(전부 level 0). 추출·커뮤니티 생성 정상. 비용 약 $0.10.

한 가지 함정(국사와 무관, 환경 차이): 현재 설치된 `graphrag_vectors`의 IndexSchema 기본 `vector_size`가 3072(text-embedding-3-large 기준)라, text-embedding-3-small(1536)을 lancedb에 쓸 때 `list_size` 에러로 첫 인덱싱이 임베딩 0개로 끝났다. repro_run3는 당시 버전에서 이 명시 없이도 됐지만 지금 버전은 안 된다. `vector_store.vector_size: 1536` 한 줄을 추가해 해결(모든 index schema에 적용). 재인덱싱은 LLM 캐시 hit이라 임베딩 write만 다시 돌아 빠르게 완료. 결과 entity_description 테이블 121행 × 1536차원, 전수 커버. 이건 도메인 일반화 문제가 아니라 graphrag 버전 드리프트이므로 별도 기록만.

## 2. TOC (가장 잘 일반화된 곳)

6 섹션, `monotonic=True`, `distinct=True`, 경고 0. start_marker는 6개 모두 코퍼스 원문 줄에 exact 그라운딩(섹션1만 forced_zero).

| # | 섹션명 | start_marker | marker 등장수 |
|---|---|---|---|
| 1 | 통계학 개요와 표본추출 | 통계의 기본 개념 | 4 |
| 2 | 중심경향과 산포도 측정 | 중심경향 측정 | 5 |
| 3 | 확률과 확률분포 | 확률 변수와 확률 분포 | 2 |
| 4 | 추정과 가설검정 | 추론 | 4 |
| 5 | 가설검정 방법과 오류 | 가설 검정 - 오류 | 1 |
| 6 | 상관분석 기법 | 상관분석 - 개요 | 1 |

평가: 기대(5~6 섹션)에 정확히 맞고 학습 흐름이 코퍼스 순서와 일치. 그라운딩 메커니즘(LLM이 원문 한 줄 선택 → string-find offset)은 도메인 무관해서 그대로 작동.

주목할 반전: `toc_gen.py`의 SYS_PROMPT는 사실 국사가 아니라 통계 교안 쪽으로 박혀 있다. "한국어 강의 자료(슬라이드 텍스트)", "슬라이드 헤더처럼 짧은 줄", 그리고 line 35 "첫 섹션은 자료 도입(통계학 정의 등)을 포함한다"까지 통계학을 도입 예시로 하드코딩. 즉 이 프롬프트는 국사에선 오히려 약간 어긋난 채 쓰였고, ai_school에선 자연 적합. TOC가 잘 된 건 우연이 아니라 프롬프트가 원래 이 도메인을 상정했기 때문.

약점(치명적이진 않음): start_marker 6개 중 4개가 반복 등장 줄(occ 2~5). 슬라이드 덱은 "통계의 기본 개념", "추정과 가설검정 상관분석"(5회), "중심경향 측정"(5회) 같은 구분 헤더를 슬라이드마다 반복한다. `resolve_offsets`가 "이전 offset 이후 첫 등장"을 잡아 이번엔 monotonic/distinct를 지켰지만, 비유일 마커는 섹션 경계가 헤더 반복 위치에 따라 흔들릴 여지가 있다. 국사 산문엔 이런 반복 네비 헤더가 없어 안 드러났던 지점.

## 3. K / 방

raw 방 크기(char-overlap 배정): `[0, 45, 29, 28, 0, 19]`. 6개 섹션 중 2개가 0노드 빈 방:
- 섹션1 "통계학 개요와 표본추출" (0~760자, 도입부): 0노드.
- 섹션5 "가설검정 방법과 오류" (7709~8363자, 654자): 0노드.

`absorb_empty_rooms`가 빈 방을 후속 방으로 흡수 → 최종 4개 방(요청 K=6 대비 4). 빈 방 자체는 크래시 없이 처리됐지만, K의 1/3이 사라졌다.

원인(국사와 다른 지점):
1. 짧은 섹션이 char-overlap에서 진다. 섹션1(760자), 섹션5(654자)는 span이 짧아 어떤 엔티티의 text_unit 겹침도 그쪽에서 최대가 되지 않는다. 국사 6방은 섹션 길이가 더 고르게 나왔다.
2. 반복 네비 헤더로 인한 조기 오배치. 최종 room0("통계 핵심 개념 및 표본추출")의 kept 상위가 `가설검정, 상관분석, 무작위 표본 추출 ...`이다. 가설검정·상관분석은 섹션4~6 주제인데 첫 방에 박혔다. 이유는 "추정과 가설검정 상관분석" 네비 헤더가 코퍼스 앞쪽을 포함해 5회 반복돼, 이 엔티티들의 occurrence-weighted 위치가 섹션1 span에서 인공적으로 떴기 때문. 결과적으로 섹션5의 자연 엔티티(1종/2종 오류, t-검정 등)는 다른 방으로 빨려가 섹션5가 빈 방이 됐다.

node_budget=20 효과: 흡수로 커진 room0(raw 45)이 20 kept / 25 demoted로 잘렸다. 절반 이상이 budget 때문에 demote. demote 목록에 `통계학, 데이터, 표본` 같은 도입 개념이 밀려 있어, "도입부 한 방"이 사라진 것과 맞물린다.

요약: 방 단계는 크래시는 없지만 (빈 방 2 → 4방 축소, 첫 방 과밀+오배치) 품질이 국사 골든(6방 균형, 전수보존)보다 확실히 나쁘다. 근본 원인은 슬라이드 특유의 짧은 도입/마무리 섹션 + 반복 헤더이고, 둘 다 char-overlap 배정 로직이 국사 산문 모양을 가정한 데서 온다.

## 4. 엔티티 추출 품질 (새 도메인에서 새로 드러난 문제)

### 4a. entity_types 화이트리스트가 무력화됨

`settings.yaml`의 `entity_types: [인물, 사건, 정책, 문물, 서적, 기관, 장소]`는 국사용이다. 통계 코퍼스엔 이 중 맞는 게 거의 없어, 추출 LLM이 화이트리스트를 무시하고 type을 자유 생성했다. 결과: 엔티티 121개에 **서로 다른 type 문자열 66종**(예: "확률 분포,수학적 모델", "통계 개념, 측정치", "방법, 절차", "통계량, 분포 특성" ...). type이 사실상 분류 기능을 못 한다(1엔티티당 거의 1type). 국사에선 7종으로 깔끔히 떨어지던 축이 새 도메인에서 무의미해졌다. entity_types를 도메인별로 바꿔주지 않으면 type 기반 후처리는 전부 신뢰 불가.

### 4b. 이중언어 글로스로 인한 개념 중복 추출

슬라이드가 용어를 "한국어 (ENGLISH)" 형태로 쓴다("정규 분포 (Normal Distribution)"). GraphRAG가 같은 개념을 **두 엔티티로** 뽑았다: 깨끗한 한국어형(`정규 분포`)과 글로스형(`정규 분포 (NORMAL DISTRIBUTION)`). room1만 봐도 kept엔 `정규 분포/이항 분포/포아송 분포/카이제곱 분포/베르누이 분포`(한국어형)가, demoted엔 `정규 분포 (NORMAL DISTRIBUTION)/이항 분포 (BINOMIAL DISTRIBUTION)/포아송 분포 (POISSON DISTRIBUTION)/카이제곱 분포 (CHI-SQUARE DISTRIBUTION)`(글로스형)이 쌍으로 들어 있다. 검정·상관계수도 마찬가지(room2의 `T-검정,분산 분석` vs room3의 `T-검정(T-TEST),분산 분석(ANOVA)`). 글로스형들이 별 엔티티로 묶여 room3에 따로 모이기까지 한다.

이건 엔티티 인플레와 의미 중복을 만들고, 4c의 크래시 원인이기도 하다. 국사 코퍼스엔 이 이중언어 패턴이 없어 안 나타났다.

## 5. Export 크래시 (파이프라인을 끝까지 막은 지점)

`palace/export_palace.py`의 `assign_palace_ids`가 제목 정규화 충돌에서 `SystemExit`로 죽는다:

```
normalized id collision: pid=ent_지수_분포_exponential_distribution from titles
'지수 분포 (EXPONENTIAL DISTRIBUTION)' and '지수 분포(EXPONENTIAL DISTRIBUTION)'
```

`normalize_title`은 `[\s\W]+ → _`로 바꾼다. 두 제목의 유일한 차이가 괄호 앞 공백 하나인데, 그 공백도 `_`로 접혀 같은 pid가 된다. export는 이를 치명 오류로 보고 중단 → `ai_school.palace.json` 미생성, `with_images`도 당연히 없음.

근원: 4b의 중복 추출. ai_school 슬라이드에 "지수 분포(...)"와 "지수 분포 (...)"가 둘 다 등장해 GraphRAG가 둘 다 엔티티로 만들었고(둘 다 degree=0 고립 노드, 같은 개념), 정규화가 둘을 한 id로 접었다. 전체 스냅샷에서 이런 충돌은 이 1쌍뿐. 즉 이 1건만 해소하면 export는 끝까지 간다.

국사가 안 깨진 이유: 국사 제목들은 공백/괄호 변이가 이 정도로 겹치지 않았고, exporter는 국사 데이터에만 노출돼 충돌 분기가 한 번도 실행된 적 없다. 이 분기는 "충돌하면 죽는다"로만 구현돼 있고 디앰비규에이션(접미 번호 등)이 없다.

권고(사용자 판단 영역이라 코드는 안 건드림): `assign_palace_ids`에서 충돌 시 죽이는 대신 pid에 `_2` 같은 접미를 붙여 분리하거나, 추출 단계에서 글로스형/한국어형을 병합. 국사엔 충돌이 없어 디앰비규에이션을 넣어도 korean_history 골든은 byte-identical 유지된다(충돌 분기가 국사에선 실행 안 됨). 어느 쪽이든 파이프라인 수정이라 결정은 보류.

## 6. 이미지 매칭

ai_school엔 figure/caption 자체가 없다. `input/ai_school/`엔 `ai_school.txt` 하나뿐, img 디렉토리·captions 파일 없음. 코퍼스 본문에도 figcaption 마크업이 없다. 따라서 `match_images` 단계는 입력이 없어 스킵했고, `ai_school_with_images.palace.json`/unplaced 산출물도 없다.

다만 사용자가 지목한 "국사 데이터에 맞춘 토크나이저" 지점은 코드 검토로만 코멘트한다: `match_images.py`의 name-match는 `tokenize_caption`(공백 토크나이저 + prefix 매칭, 한국어 조사 흘려보내기)과 `_surface_variants` 기반 prefix/exact 매칭이다. docstring(line 162-166)에 "Swap this function per domain"이라고 한국어 의존을 명시해 둔 상태다. 이중언어 글로스("정규 분포 (Normal Distribution)")가 많은 통계 캡션이 실제로 있었다면, 조사 prefix 다이얼보다 영문 괄호·약어(PDF, PMF, ANOVA) 매칭이 관건이 됐을 것이다. 이번 코퍼스엔 figure가 없어 실측 불가. figure 있는 통계 교안이 들어오면 여기가 가장 깨질 확률 높은 지점이라는 사용자 예측은 4b로 보아 타당하다(캡션 토큰 모양이 국사와 근본적으로 다름).

## 무엇이 일반화됐고 무엇이 안 됐나

일반화 잘 됨(도메인 라벨로 LLM 구동):
- TOC 생성 + start_marker 그라운딩 (애초에 통계 교안 상정 프롬프트라 자연 적합)
- Stage A 루브릭: config의 `domain` 문자열만으로 통계용 규칙 5개를 적절히 도출(P-VALUE/T-검정/귀무가설 등 실제 엔티티 인용, 국사 누수 없음)
- Stage B keep/demote: 방별 keep 목록이 통계 핵심 개념 위주로 합리적

일반화 깨짐(국사 데이터 모양에 박힌 결정적/문자열 단계):
- export 제목 정규화 충돌 → 하드 크래시(palace.json 미생성). headline.
- entity_types 화이트리스트(국사 7종) → 통계에선 무력, type 66종 폭발
- char-overlap 방 배정: 짧은 도입/마무리 섹션이 빈 방 → 6방 요청이 4방으로, 첫 방 과밀+오배치
- 반복 슬라이드 헤더가 TOC 마커 유일성과 엔티티 위치를 동시에 오염(국사 산문엔 없던 모양)
- 이중언어 글로스로 같은 개념 2엔티티 중복(인플레 + 충돌 원인)

성격 요약: 파이프라인의 "지능" 부분(LLM 단계)은 도메인 이식이 쉽다. "배관" 부분(타입 화이트리스트, 제목 정규화, 위치 기반 배정)이 국사 코퍼스의 형태적 가정(깨끗한 산문, 유일 헤더, 단일언어 제목)에 묶여 있어 슬라이드 추출 텍스트에서 깨진다.

## 국사 canonical 미변경 확인

`git status --short`에 수정(M) 항목 없음, 신규 추가(??)만:
- `palace/configs/ai_school.json`, `proj_ai_school/`, `results/snapshots/ai_school/`
- (results/audit/의 다른 파일들은 이번 세션 이전부터 있던 것)

대조 확인: `results/snapshots/repro_run3/`(2026-06-02), `palace/configs/korean_history.json`, `settings.yaml`, `palace/export_palace.py`, `palace/handoff/korean_history*.json`, `palace/tests/golden/korean_history*` 모두 미수정. output/cache/logs/tests-runs는 gitignore 영역이고 전부 ai_school 전용 하위 경로에만 썼다(국사 output/ 루트·cache/ 루트 미접촉).

## 다음 결정(사용자 몫)

1. export 충돌 디앰비규에이션을 넣어 `ai_school.palace.json`까지 뽑을지(국사 골든 불변 보장).
2. ai_school용 entity_types를 통계 도메인으로 교체해 재인덱싱할지(type 폭발·이중언어 중복 완화 기대).
3. 이 ai_school 스냅샷/산출물을 추적(commit)할지.
