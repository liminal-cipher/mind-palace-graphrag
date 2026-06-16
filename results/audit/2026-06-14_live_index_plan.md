# (B) 라이브 인덱싱 구현 계획 (정찰 산출물)

날짜: 2026-06-14
범위: orchestrator의 index 단계를 scaffold(프리베이크 스냅샷 포인터)에서 진짜 GraphRAG
인덱싱으로 바꾸는 능력 구현 계획. 정찰만, 코드 변경 0.
git 확정: c1796e5, 32ccf1b, 0964fa2 모두 origin/main HEAD a5077cf 에 존재함을 확인
(`git branch -a --contains` 결과 main + remotes/origin/main).

틀 주의: 이 문서는 "라이브 업로드를 인덱싱하는 능력"만 다룬다. "무대 즉석 인덱싱이냐
미리 돌려두기냐"는 매니저/팀 ADR 콜이며 여기서 채택하지 않는다(능력만 설계, 타이밍은 메모만).

---

## [A] 현재 index seam + scaffold↔real 분기

### 현재 index 단계
`orchestrator/stages.py::index(job, store, sleep_seconds, *, domain=None, entity_types=None)`
(stages.py:54-89). 동작:
1. `store.update(job.job_id, state=State.INDEXING)`
2. `await asyncio.sleep(sleep_seconds)` (스텁 지연)
3. `snapshot_dir = config.SHOWCASE_SNAPSHOTS.get(job.domain)`, 없으면 `ValueError`
4. 결정 기록 `_index_scaffold.json` 을 잡 폴더(var)에만 기록
5. `store.update(job.job_id, snapshot_path=snapshot_dir)` 로 snapshot_path 를 프리베이크
   dir(results/snapshots/...)로 가리킴

★ 워커는 스테이지를 위치 인자로만 호출한다: `await stage(job, self.store, self.sleep_seconds)`
(worker.py:104-105). 따라서 `domain`/`entity_types` kwarg 는 절대 전달되지 않는다. build_palace 가
빌드 모드를 kwarg 가 아니라 config 에서 끌어내는 것과 같은 패턴(stages.py:179-182). 라이브
인덱싱도 도메인/entity_types 를 kwarg 가 아니라 store/config 에서 끌어내야 한다.

### (b)가 남긴 clean seam
- build_palace 는 snapshot_path 를 store 에서 fresh 로 다시 읽는다:
  `fresh = store.get(job.job_id) or job; ... _build_job_palace_config(fresh, fresh.snapshot_path)`
  (stages.py:173-174). 그 값이 per-job palace config 의 `cfg["snapshot"]`/`cfg["snapshot_rel"]`
  로 들어간다(stages.py:137-138).
- 즉 index 가 snapshot_path 에 무엇을 쓰든 build_palace 가 그대로 소비한다. **이 한 줄
  (`store.update(snapshot_path=...)`)이 scaffold↔real 의 교체 지점**이다. 스테이지 시그니처,
  워커, build_palace 는 손 안 대도 된다.
- `config.SHOWCASE_SNAPSHOTS` 와 `config.PALACE_CONFIGS` 는 **별개의 평행 레지스트리**
  (config.py:33-45). build_palace 는 SHOWCASE_SNAPSHOTS 를 참조하지 않으므로 scaffold 가정이
  빌드로 새지 않는다.

### store 갱신 계약 (index 가 진짜가 되면)
index 는 다음을 보장해야 한다:
1. `var/jobs/<id>/` 아래 진짜 스냅샷 dir 생성. palace/run.py 의 `_stop_if_missing`
   (palace/run.py:76-91)이 요구하는 산출: `entities.parquet`, `text_units.parquet`,
   `documents.parquet`, `lancedb/`. export_palace 는 추가로 `relationships.parquet` 필요.
   즉 GraphRAG 표준 출력(parquet 7종 + lancedb)을 그대로.
2. `store.update(job.job_id, snapshot_path=<그 dir>)`.
3. snapshot_path 는 serve 의 허용 루트 검증을 통과해야 한다. `var/jobs` 는 이미 허용 루트
   (serve.py:61-64, `_ALLOWED_REGISTER_ROOTS`). rag 단계가 그대로 register 함(변경 불필요).

### ★ 분기 위험 (가장 중요)
현재 "쇼케이스냐 라이브냐" 트리거는 **`/upload` 의 `domain` 쿼리 파라미터 하나**다
(app.py:57). index 는 `job.domain` 을 SHOWCASE_SNAPSHOTS 의 키로 직접 쓴다. smoke_e2e.py 가
이를 못박는다: "index(scaffold) 는 업로드 내용이 아니라 domain 으로 스냅샷을 고른다"
(smoke_e2e.py:96-102).

결과 누수: 심사위원이 한국사 PDF 를 올리며 domain="korean_history" 를 주면(또는 감지 라벨이
그렇게 나오면) scaffold 가 repro_run3 를 골라 **그들 파일 대신 프리베이크 국사가 뜬다.**
도메인 라벨이 스냅샷 선택과 결합돼 있는 게 근본 원인.

요구 분기 설계:
- 스냅샷 선택과 도메인 라벨을 **분리**한다. 도메인 라벨은 prompt-tune/toc 에만 쓰고
  스냅샷 선택엔 절대 안 쓴다.
- 쇼케이스 트리거를 별도 신호로 둔다. 셋 중 하나(권장 1):
  1. (권장) 명시적 `showcase` 플래그/예약 키. 예: `/upload?showcase=korean_history`
     또는 쇼케이스 전용 엔드포인트 `/showcase/{name}`. 이 명시 신호가 있을 때만
     SHOWCASE_SNAPSHOTS 매핑 → scaffold.
  2. 일반 업로드(`/upload` + 파일 바이트)는 **무조건 라이브 인덱싱**. domain 파라미터가
     무엇이든 scaffold 로 안 간다.
- index 단계 의사코드:
  ```
  if job.is_showcase and job.showcase_key in SHOWCASE_SNAPSHOTS:
      snapshot_dir = SHOWCASE_SNAPSHOTS[job.showcase_key]   # 기존 scaffold, fallback 유지
  else:
      snapshot_dir = live_index(job)                        # 진짜 인덱싱 → var/jobs/<id>/snapshot
  store.update(job.job_id, snapshot_path=snapshot_dir)
  ```
- 라이브가 scaffold 로 새지 않는 보장: 라이브 경로는 SHOWCASE_SNAPSHOTS 를 아예 조회하지
  않는다. 감지 도메인 라벨(korean_history 든 뭐든)은 live_index 안에서 prompt-tune/toc
  파라미터로만 흐른다.

설계 메모: 이를 위해 잡 모델에 쇼케이스 신호를 실어야 한다. Job 스키마는 현재 domain 만
가진다(jobs.py:40-52). 명시 플래그를 store 컬럼이나 예약 domain 규약으로 추가하는 것은
구현 단계 결정(스키마 변경 = 마이그레이션 1줄, `_SCHEMA` jobs.py:69-84).

---

## [B] ②의 수동 (a) 경로 재현

### ai_school 인덱싱
- 별도 GraphRAG root: `proj_ai_school/`(settings.yaml). repro_run3 root 를 본떠 모델
  (gpt-4.1-mini 추출 + text-embedding-3-small), 청킹 size=1200/overlap=100,
  max_cluster_size=15, use_lcc=true 동일. 입력/출력만 분리
  (canary 문서 results/audit/2026-06-12_ai_school_canary.md:31).
- settings 경로(루트 상대): `input_storage.base_dir: ../input/ai_school`,
  `output_storage.base_dir: ../output/ai_school`, cache/reporting 동일 패턴
  (proj_ai_school/settings.yaml:41-57).
- 인덱싱 명령(STOP-1 확장에서 세션 로그로 확정, 2026-06-14_stop1_index_recipe.md 참조):
  `.venv/Scripts/python.exe -X utf8 -m graphrag index --root proj_ai_school`.
  base_dir 가 `..` 로 시작하므로 root 를 proj_ai_school 로 주면 input/output 이 레포 루트의
  input/ai_school, output/ai_school 로 해소됨.
- 출력 → 스냅샷(확정): PowerShell `Copy-Item -Recurse "output\ai_school" "results\snapshots\ai_school"`
  (기존 dst 는 Remove-Item -Recurse -Force 후 복사). parquet 7종 + lancedb + stats.json 통째.
  측정 인덱싱 시간: `results/snapshots/ai_school/stats.json` total_runtime 75.8s
  (extract_graph 57s), 비용 약 $0.10(canary).
- ★ lancedb 함정: 현재 `graphrag_vectors` 기본 vector_size 3072 가 text-embedding-3-small
  (1536)과 mismatch → lancedb write 시 list_size 에러. `vector_store.vector_size: 1536`
  한 줄로 해결(proj_ai_school/settings.yaml:59-65). **라이브 root 템플릿에 필수 포함.**

### prompt-tune (66종→16종)
- ★ 정정(STOP-1 확장, 2026-06-14_stop1_index_recipe.md): ai_school 의 ~15종 entity_types 는
  **discover ON 자동 생성**이다(아래 --no-discover 서술은 exp17 전용, ai_school 에 오투영했던
  오류). ai_school 실제 명령:
  `python -m graphrag prompt-tune --root proj_ai_school --domain "통계 기초 교안 (...)"
  --language Korean --selection-method all --output prompts_tuned --chunk-size 1200 --overlap 100`
  (`--no-discover` 없음 = discover ON; 작은 코퍼스라 `--selection-method all` 필수).
- 레포에 정확히 기록된 prompt-tune 호출은 exp17(별개 실험):
  `archive/exp17_generalization/PHASE_A_CHECKPOINT.md:50`:
  ```
  .venv/Scripts/python.exe -m graphrag prompt-tune --root . --no-discover-entity-types \
    --domain "통계학 기초 강의 자료 (모집단·표본·확률 분포·가설 검정·상관분석)" \
    --language Korean --output prompts --selection-method top --limit 2 --min-examples-required 2
  ```
  산출: `archive/exp17_generalization/prompts/`.
- ai_school(proj_ai_school/prompts_tuned/) 을 만든 **정확한 호출은 레포에 없음**. exp17
  패턴의 유추 = `--root proj_ai_school --output prompts_tuned --domain "통계 기초 교안 ..."`
  (구현 전 확인 필요, 미해결).
- ★ 66→16 의 진짜 비교축(STOP-1 확장 정정): "무튜닝(잘못된 정적 화이트리스트) vs discover ON".
  canary 의 66종 폭발은 prompt-tune 을 안 돌리고 국사 화이트리스트(7종)를 통계 코퍼스에 써서
  LLM 이 mismatch 목록을 무시하고 type 을 자유 생성한 결과(canary md:74-76). 해결은
  **discover ON prompt-tune** 이 도메인 적합 15종을 자동 생성한 것(proj_ai_school/
  prompts_tuned/extract_graph.txt:8 에 baked, settings.yaml:78 은 가독성용 사본). 즉 15종은
  손지정이 아니라 discover 산출. ([D] 권고는 "discover 는 유효하나 비용이 있어 알려진 도메인은
  curated 룩업이 더 싸다"로 근거를 갱신; 상세는 2026-06-14_stop1_index_recipe.md.)
- proj_ai_school/ 은 .gitignore(line 16)에 있지만 6e04738 에서 텍스트 산출물만 `-f` 로
  force-track 됨(settings.yaml + prompts_tuned 3종). output/cache/logs/lancedb 는 계속 무시.
  → 튜닝 프롬프트가 레포에 있어 **템플릿으로 재사용 가능**.

### 인덱싱 env/설정
- `.env` 에서 로드: `GRAPHRAG_API_KEY`, `GRAPHRAG_API_BASE`(settings.yaml 의
  `${...}` 치환, api_version 2024-12-01-preview). palace/run.py 도 같은 `.env` 를
  `_load_dotenv` 로 읽음(palace/run.py:60-68, 253).
- 추가 필수: vector_store.vector_size 1536(위), input.type text, 청킹/클러스터 설정.

---

## [C] per-job GraphRAG root 격리 (★핵심)

### 왜 레포 루트를 못 쓰나
- 레포 루트 `settings.yaml` 은 base_dir `input`(국사 풋건) + `output`(bare 점유) +
  국사 entity_types `[인물, 사건, 정책, 문물, 서적, 기관, 장소]`(settings.yaml:46-76).
  라이브 업로드가 레포 루트를 쓰면 국사 입력과 충돌하고 국사 출력을 덮어쓴다.

### 격리 root 세우기 (proj_ai_school 을 베이스로)
job 마다 `var/jobs/<id>/index_root/` 를 세운다:
```
var/jobs/<id>/index_root/
  settings.yaml      # 템플릿 복사 + 슬롯 치환(아래)
  input/             # 업로드 코퍼스(.txt) 한 부
  prompts/           # 도메인 추출 프롬프트 세트
  output/            # graphrag 출력(= 스냅샷 원본)
  cache/             # 잡별 콜드 캐시
```
명령: `python -m graphrag index --root var/jobs/<id>/index_root`(subprocess).
완료 후 `output/`(또는 정리 복사본 `var/jobs/<id>/snapshot/`)을 store 의 snapshot_path 로 등록.

치환할 슬롯(도메인 의존):
- `extract_graph.entity_types`: 감지 도메인의 entity_types(15~16종 또는 폴백 중립 목록)
- `extract_graph.prompt` / `summarize_descriptions.prompt` / `community_reports.graph_prompt`:
  도메인 프롬프트(풀 튜닝 산출 or 스톡, [D] 참조)
- input/output/cache base_dir: 잡 경로
- vector_store.vector_size: 1536(고정)

### 스톡 템플릿 존재 여부
- 중립 "스톡" settings 템플릿은 레포에 **없다.** 후보 둘: 레포 루트 settings.yaml(국사
  entity_types 박힘), proj_ai_school/settings.yaml(통계 entity_types + 격리 경로 + 1536 픽스 +
  튜닝 프롬프트 배선). **proj_ai_school 쪽이 격리 구조·vector_size·프롬프트 배선을 이미 갖춰
  베이스로 가장 적합.** 거기서 도메인 슬롯(entity_types/prompt)만 바꾸는 게 가능하고 권장.
  단 base_dir 의 `..` 상대경로는 잡 root 기준으로 다시 써야 한다.

### (b) 패턴 확장
build_palace 는 이미 per-job config 를 베이스에서 materialize 하고 출력/캐시를
`var/jobs/<id>/` 로 격리하며 캐시를 seed 한다(`_build_job_palace_config` stages.py:116-151).
**인덱싱 root 격리는 같은 패턴을 한 스테이지 앞에서 하는 것**이다: palace config materialize ↔
graphrag root materialize. 쇼케이스 scaffold 는 기존 root(repo 루트 / proj_ai_school) 그대로
fallback 으로 둔다.

---

## [D] 도메인 감지 + prompt-tune 배선 + 비용 대안

### 도메인 라벨 hook (단일 소스)
- 현재 도메인 감지 코드는 **없다.** domain 은 `/upload` 쿼리 파라미터일 뿐(app.py:57),
  index/build_palace 가 그 문자열을 그대로 쓴다.
- hook 위치: 업로드 직후 또는 index 진입부에 싼 LLM 1콜로 free-text 도메인 라벨 산출.
  그 라벨을 단일 소스로 두 곳에 먹인다:
  1. prompt-tune `--domain`(or entity_types 조건화, 아래)
  2. toc_gen `{domain}` 힌트. toc_gen 은 이미 domain 인자를 받아 시스템 프롬프트에 한 줄로
     엮는다(toc_gen.py:44-52, 174-187). build_palace config 도 `domain` 을 그대로 운반.
- 라벨은 [A]의 분기에서 **스냅샷 선택엔 절대 안 쓴다.** prompt-tune/toc 전용.

### ★ 비용 대안 (풀 튜닝 vs 가벼운 조건화)
- 풀 graphrag prompt-tune = 멀티 LLM 콜(코퍼스 샘플 + 예시 생성). per-job 으로 돌리면
  지연이 분 단위로 급증.
- 핵심 근거([B]): 66종 회귀의 원인은 **entity_types 화이트리스트 하나**다. canary 가
  확인하길 LLM 단계(TOC/루브릭/keep-demote)는 도메인 라벨만으로 깨끗이 일반화됐다
  (canary md:107-121). 즉 비싼 부분(예시 재생성)은 회귀와 무관.
- 따라서 더 싼 길(권장):
  - (권장) **도메인 → entity_types 룩업/템플릿 주입**. 감지 라벨로 ~12-16종 entity_types 를
    골라 settings 에 주입, 스톡 extract_graph 프롬프트 유지. 풀 튜닝 생략. 66종 폭발만
    막으면 목표 달성.
  - 중간: 싼 LLM 1콜로 감지 도메인의 entity_types ~15종을 **제안만** 받아 주입(예시 생성 X).
  - 풀 prompt-tune 은 쇼케이스 도메인용으로만 오프라인 1회(이미 proj_ai_school 에 있음),
    라이브 per-job 경로엔 넣지 않음.
- 추천: 룩업 우선, 필요 시 "entity_types 제안 1콜"로 미지 도메인 커버.

### 폴백 (라벨 없음/감지 실패)
- 현재 폴백 = 레포 루트 국사 entity_types = **66종 회귀 = 실패 모드.** 반드시 교체.
- 설계: 라벨 실패 시 **도메인 중립 generic entity_types**(예: person, organization, concept,
  method, event, location, artifact, metric 등 일반 목록)로 떨어진다. 또는 graphrag
  `--discover-entity-types`(LLM 비용 있음). 어느 쪽이든 국사 7종으로 떨어지지 않게 명시.

---

## [E] 입력 계약

- `/upload` 는 raw 본문 바이트를 `var/jobs/<id>/input/<안전파일명>` 에 그대로 쓴다
  (app.py:60-86). 파싱/추출 없음. 파일명만 sanitize.
- preprocess 는 스텁: sleep + `_preprocess.done` 터치(stages.py:42-51). **텍스트 추출 없음.**
- GraphRAG index 는 `input.type: text` 로 input base_dir 의 `.txt` 를 기대한다
  (settings.yaml:33-34). 입력 위치 = root 의 input base_dir.
- ★ **(B) 시점 지원 입력 타입 = 플레인 텍스트 `.txt` 만.**
  - PDF/슬라이드는 인덱싱 전에 텍스트 추출(PyMuPDF / Azure Document Intelligence)이 필요.
    그 추출은 현재 **어디에도 없다**(preprocess 스텁, 업로드 핸들러도 raw 저장만).
  - 비-txt 지원 = 이미지팀 preprocess(텍스트 추출) 의존. preprocess 진짜화는 (B) 스코프 밖.
- 데모 안내: 심사위원에게 **.txt(또는 미리 추출된 텍스트)** 를 올리라고 해야 한다. PDF/슬라이드
  직접 업로드는 추출 파이프라인이 붙기 전까지 빈/깨진 추출로 다운스트림이 무너질 수 있음
  (입력 품질 caveat). ai_school 코퍼스 자체가 "슬라이드 추출 텍스트"였고, 그 결과 이중언어
  글로스/반복 헤더로 방 배정이 흔들렸음(canary md:78-82, 4b) - 추출 품질이 인덱싱 품질에
  직결된다는 실증.

---

## [F] 실패 처리

- index subprocess 실패: nonzero rc → raise(build_palace 의 `_run_palace` rc 체크와 동형,
  stages.py:154-189). 워커 `_consume` 가 잡아 `store.fail(job_id, ...)`, **워커 루프는 생존**
  (worker.py:92-94, "한 잡 실패가 워커를 죽이지 않게").
- 표면화할 실패: Azure 에러(키/쿼터), 빈 추출(0 엔티티), 포맷 깨짐(비-txt raw),
  extract_graph 타임아웃, lancedb vector_size mismatch(1536 미설정 시).
- index 자체 실패 vs 다운스트림: 엔티티 부족 → build_palace 에서 K 붕괴/char-overlap 0노드.
  toc 클램프 STOP→merge 는 8ae32f9 에서 이미 처리(중복 작업 X). index 레벨에선 인덱싱 후
  엔티티 수가 0/극소면 조기 fail or warn 하는 게이트를 두는 게 좋음(미세 결정, 구현 단계).
- ★ 직렬 큐 확인: 워커는 단일 `asyncio.Queue` 로 한 번에 한 잡만 처리한다(worker.py:85-96).
  **동시 업로드는 큐로 직렬로 쌓인다. 데모 OK.** 현재 동작이 그러함을 확인.

---

## 보고 요약

### index 단계 localized swap 계획
- 바꿀 파일: `orchestrator/stages.py`(index 함수 본문), `orchestrator/config.py`(라이브 root
  템플릿 경로 + 도메인→entity_types 룩업 상수), 잡 모델에 쇼케이스 신호 추가 시
  `orchestrator/jobs.py`(+`_SCHEMA`)와 `orchestrator/app.py`(업로드 트리거).
- subprocess 호출: `python -m graphrag index --root var/jobs/<id>/index_root`
  (cwd=REPO, capture_output, encoding utf-8). build_palace 의 `_run_palace`(stages.py:154-164)
  와 동일한 subprocess seam 재사용 권장(asyncio/lancedb 격리 이유 동일).
- per-job root 격리: proj_ai_school 베이스 → `var/jobs/<id>/index_root/`(settings+input+
  prompts+output+cache), 도메인 슬롯만 치환, vector_size 1536 고정.
- store 갱신: 인덱싱 출력 dir → `store.update(snapshot_path=var/jobs/<id>/snapshot)`. 그게
  build_palace `cfg["snapshot"]` 으로, rag 의 register 로 그대로 흐름(seam 1줄).

### scaffold↔real 분기
- 명시 쇼케이스 트리거(플래그/예약키/전용 엔드포인트)일 때만 SHOWCASE_SNAPSHOTS → scaffold.
- 일반 업로드는 무조건 라이브 인덱싱. 라이브 경로는 SHOWCASE_SNAPSHOTS 미조회 → 누수 0.
- 감지 도메인 라벨은 prompt-tune/toc 전용, 스냅샷 선택과 분리.

### 도메인 라벨 hook + prompt-tune 경로
- 업로드/인덱싱 진입부 싼 LLM 1콜 → 단일 라벨 → prompt-tune(or entity_types 조건화) + toc.
- 추천: **풀 prompt-tune 대신 도메인→entity_types 룩업/주입**(회귀 원인이 entity_types 뿐).
  풀 튜닝은 쇼케이스 오프라인 전용. 폴백 = 중립 generic entity_types(국사 7종으로 안 떨어짐).

### (B) 지원 입력 타입
- **.txt(또는 미리 추출된 텍스트)만.** 비-txt(PDF/슬라이드)는 이미지팀 preprocess(텍스트
  추출, PyMuPDF/Azure DI) 의존이며 (B) 스코프 밖. 데모는 .txt 안내.

### 실패 처리 + 직렬 큐
- subprocess rc≠0 → raise → store.fail, 워커 생존. Azure/빈추출/포맷/타임아웃/1536 미스 표면화.
- 워커 단일 큐 = 동시 업로드 직렬 처리(데모 OK), 확인됨.

### (b)에서 재사용 vs 새로 만들 것
재사용:
- subprocess seam(`_run_palace` 패턴), per-job config materialize(`_build_job_palace_config`
  패턴), `var/jobs/<id>/` 격리, 캐시 seed 토글(SEED_PALACE_CACHE), store snapshot_path seam,
  serve register(이미 구현, var/jobs 허용 루트), proj_ai_school 을 root 템플릿,
  settings vector_size:1536 픽스, toc_gen domain 힌트(이미 배선).
새로:
- per-job graphrag index root materialize, 진짜 index subprocess 호출, 도메인 감지 LLM hook +
  단일 라벨, 도메인→entity_types 룩업/주입, 인덱싱 출력→snapshot 등록, 명시 쇼케이스 트리거
  (도메인 라벨과 분리), 폴백 중립 entity_types, (선택) 인덱싱 후 엔티티 게이트.

### 안 건드릴 것 (확인)
- frozen: results/snapshots/repro_run3, palace/tests/golden, palace/configs/korean_history.toc_frozen.json
- serve.py: register 엔드포인트 그대로 재사용(변경 불필요)
- build_palace 진짜 경로: seam(snapshot_path) 외 미변경
- 쇼케이스 scaffold fallback: SHOWCASE_SNAPSHOTS 유지(명시 트리거 경로로)

### 미해결 / 위험
1. (해소됨) ai_school 정확 명령 = 2026-06-14_stop1_index_recipe.md 로 세션 로그에서 확정.
   prompt-tune discover ON + selection-method all, index --root proj_ai_school, Copy-Item 복사.
2. graphrag CLI subprocess vs `graphrag.api.index.build_index`(in-process, exp09 가 사용:
   archive/exp09_rechunk/run_full.py:14,29) 선택. orchestrator 는 asyncio/lancedb 격리상
   subprocess 선호 → `python -m graphrag index --root <jobroot>` 권장.
3. proj_ai_school base_dir 의 `..` 상대경로를 잡 root 기준으로 재작성 필요.
4. 도메인→entity_types 룩업 커버리지(미지 도메인 폴백 품질).
5. 잡 모델 스키마 변경(쇼케이스 신호) 마이그레이션.

### 예상 per-job 지연
- 인덱싱: ai_school(약 20KB, 1문서) 측정 75.8s(extract_graph 57s, cold, $0.10;
  stats.json). 국사급(약 50KB) 재인덱싱은 RUNBOOK 기준 약 6.5분/$0.93. **코퍼스 크기에 대략
  선형(extract_graph 가 청크당 LLM 콜 지배).**
- prompt-tune: 풀 튜닝 경로면 멀티 LLM 콜로 분 단위 추가; entity_types 룩업/주입 경로면 약 0
  (또는 제안 1콜 수초).
- 빌드: 약 36s(task 기준; build_palace 캐시 seed 시 단축).
- 합계(권장 룩업 경로, 소형 코퍼스): 대략 인덱싱 76s + 빌드 36s ≈ 2분 내외. 대형/풀튜닝이면
  분 단위로 증가, 코퍼스 크기에 선형.

---

타이밍 메모(능력 밖): "무대 즉석 인덱싱 채택 여부"는 매니저/팀 ADR 콜. 위 per-job 지연이
즉석 인덱싱을 데모에서 감당 가능한지의 입력 자료가 됨(소형 .txt 는 2분 내외, 대형은 주의).
