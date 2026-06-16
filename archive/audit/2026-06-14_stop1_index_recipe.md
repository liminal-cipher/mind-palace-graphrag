# STOP-1 해소: ② ai_school 인덱싱 레시피 재구성 + entity_types 출처 판정

날짜: 2026-06-14
범위: (1) ② ai_school 인덱싱 정확 명령 재구성, (2) 레포의 ~15종 entity_types 가 discover
자동생성인지 손지정인지 판정. 코드/커밋/push 0. 검증용 prompt-tune 재실행은 불필요(아래 이유).
증거 출처: CC 세션 로그(.claude/projects/.../35eabb67-*.jsonl = 6/14 재튜닝 세션,
4a5dce3c-*.jsonl = 6/12 canary 세션), PSReadLine 히스토리, git, 레포 파일.

---

## 한 줄 결론

레포의 ~15종 entity_types 는 **prompt-tune discover ON 이 자동 생성한 것**이다(원래 Notion
결정이 맞음). 직전 STOP-1 추론(`--no-discover` 손지정)은 **틀렸다.** canary 의 "66종 폭발"은
discover 실행 결과가 아니라, prompt-tune 을 아예 안 돌리고 국사 entity_types 화이트리스트를
통계 코퍼스에 쓴 별개 실행의 결과다. 즉 비교 축은 "손지정 vs discover"가 아니라
"무튜닝(잘못된 정적 화이트리스트) vs discover ON"이다.

증거가 결정적이라 비싼 재실행 결정 테스트는 실행하지 않았다(불필요).

---

## (1) 재구성한 정확한 명령

### 단계 A. prompt-tune (discover ON)
세션 35eabb67 line 317-322. Windows 유니코드 안전을 위해 args 리스트로 subprocess 호출.
domain 문자열은 `palace/configs/ai_school.json` 의 `domain` 필드에서 읽음.

첫 시도(실패): discover ON, 기본 selection(random).
```
.venv/Scripts/python.exe -X utf8 -m graphrag prompt-tune \
  --root proj_ai_school \
  --domain "통계 기초 교안 (기술통계·확률분포·추정·가설검정·상관분석)" \
  --language Korean \
  --output prompts_tuned \
  --chunk-size 1200 --overlap 100
```
실패 원인: 코퍼스가 작아 청크 수 < 기본 limit 15 → random 샘플링에서 에러.

성공 시도(채택): `--selection-method all` 추가.
```
.venv/Scripts/python.exe -X utf8 -m graphrag prompt-tune \
  --root proj_ai_school \
  --domain "통계 기초 교안 (기술통계·확률분포·추정·가설검정·상관분석)" \
  --language Korean \
  --selection-method all \
  --output prompts_tuned \
  --chunk-size 1200 --overlap 100
```
핵심: **`--no-discover-entity-types` 플래그 없음 → discover-entity-types 가 기본값으로 ON.**
산출: `proj_ai_school/prompts_tuned/{extract_graph.txt, summarize_descriptions.txt,
community_report_graph.txt}`. discover 가 발견한 entity_types 가 extract_graph.txt 에 baked.

### 단계 B. settings.yaml entity_types 동기화 (수동)
discover 가 만든 목록을 `proj_ai_school/settings.yaml:78` 에 같은 순서로 복사. settings 의 주석이
이를 명시: "entity_types 는 prompt 안에 리터럴로 baked 되어 있어 추출을 실제로 구동하지만,
일관성을 위해 같은 목록을 여기에도 둔다." 즉 **추출의 실제 구동자는 baked 프롬프트**이고
settings 의 목록은 가독성용 사본. 출처는 어느 쪽이든 discover.

### 단계 C. graphrag index
세션 35eabb67 line 362 (6/14 재튜닝 후 재인덱싱):
```
.venv/Scripts/python.exe -X utf8 -m graphrag index --root proj_ai_school
```
(참고: 6/12 canary 세션 4a5dce3c line 112/122 에서는 `graphrag index --root proj_ai_school
--dry-run --skip-validation` → `--skip-validation` 로 돌렸다. 6/14 재인덱싱은 위처럼 플래그
없이.) base_dir `../input/ai_school` → 레포 input/ai_school 입력, `../output/ai_school` 출력.
vector_store.vector_size: 1536 필수(text-embedding-3-small 1536 vs lancedb 기본 3072 mismatch).

### 단계 D. output → snapshot 복사 (PowerShell)
세션 35eabb67 line 375:
```
$dst = "results\snapshots\ai_school"
if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
Copy-Item -Recurse "output\ai_school" $dst
```
graphrag 출력(parquet 7종 + lancedb + stats.json)을 통째로 스냅샷 dir 로 복사.

### (B) index subprocess 명령 템플릿 (요약)
per-job 라이브 인덱싱은 위 A~D 를 잡 root 로 옮긴 형태:
1. (선택) prompt-tune discover ON, `--root <jobroot> --selection-method all --output prompts`
   (작은 코퍼스는 selection all 필수).
2. `python -m graphrag index --root <jobroot>` (subprocess, `_run_palace` 와 동형 seam).
3. output → `var/jobs/<id>/snapshot` 복사 후 `store.update(snapshot_path=...)`.

---

## (2) entity_types 출처 판정

### 지지 가설: discover 자동생성 (원래 Notion 맞음)

증거:
1. **실제 명령**(세션 35eabb67 line 238, 309-322): "discover ON 으로 간다(--domain 만, 기본
   discover-entity-types)" 라고 명시 후, `--no-discover` 없이 prompt-tune 실행. 즉 discover ON.
2. **discover 산출 = 커밋된 목록과 일치**(세션 line 340, prompt-tune 직후 검증 grep):
   `prompts_tuned/extract_graph.txt:31: entity_types: [person, statistical concept,
   statistical method, statistical parameter, statistical distribution, sampling method,
   hypothesis, error type, data type, statistical measure, statistical test, correlation
   coefficient, statistical visualization, community member role, decision criteria]`.
   이는 레포 커밋본 `proj_ai_school/prompts_tuned/extract_graph.txt:8` + `settings.yaml:78`
   의 15종과 정확히 같다. 손편집 흔적 없음(discover 출력이 그대로 baked).
3. **66종은 discover 가 아님**: canary(6/12, 세션 4a5dce3c)는 prompt-tune 을 안 돌리고
   국사 화이트리스트 `[인물,사건,정책,문물,서적,기관,장소]` 로 통계 코퍼스를 인덱싱 →
   LLM 이 mismatch 화이트리스트를 무시하고 type 자유생성 → 66종
   (archive/audit/2026-06-12_ai_school_canary.md:74-76). 이건 "discover 의 노이즈"가 아니라
   "튜닝 부재 + 잘못된 정적 목록"의 결과.

직전 STOP-1 문서의 `--no-discover-entity-types` 추론은 exp17(별개 통계 실험)의 명령을
ai_school 에 잘못 투영한 것. exp17 은 `--no-discover` 였지만 ai_school 은 discover ON.

### ★ 핵심 판단: discover-ON 이 이 코퍼스에서 쓸 만한 타입을 내는가
**예.** ai_school 통계 코퍼스에서 discover ON 은 66종 폭발 없이 도메인 적합 15종
(통계 개념/방법/분포/검정/상관계수 등)을 냈다. 이는 임의 업로드에서 'discover 실행'을
타입 자동생성 길로 쓸 수 있음을 직접 입증한다. 단 운영 caveat 가 붙는다:

- ★ **작은 코퍼스에서 기본 selection 실패**: 청크 수 < 기본 limit 15 면 random 샘플링이
  깨진다. `--selection-method all`(또는 `--limit` 하향) 필수. 라이브 업로드는 짧은 자료가
  흔하므로 discover 경로는 selection all 을 기본값으로 박아야 한다.
- discover = 멀티 LLM 콜 → per-job 지연/비용 추가(코퍼스 크기에 따라 수십초~분).
- discover 출력 타입 수는 통제 불가하므로 type-count 새너티 게이트 + 폴백 필요.

### (B) 타입 경로 결정 근거 (discover 실행 vs curated 룩업 + generic 폴백)
- discover ON 은 **미지 도메인**에 대해 실증된 자동 타입 생성 길이다(채택 가능).
- 단 비용/지연 + 작은 코퍼스 실패 + 타입 수 통제 불가 때문에, **알려진 도메인은 curated
  룩업이 더 싸고 안정적**이다.
- 권장 하이브리드: 알려진 도메인 → curated entity_types 룩업(0콜). 미지 도메인 →
  discover ON(`--selection-method all` 고정) + type-count 게이트. 둘 다 실패 시 →
  도메인 중립 generic entity_types 폴백(국사 7종으로 절대 안 떨어지게).
- 이 판정으로 직전 STOP-1 의 "풀 prompt-tune 불필요" 결론은 **부분 수정**: discover 는
  유효하나 비용이 있고, curated 가 더 싸다는 비교는 유지. "타입이 손지정이라 튜닝이 회귀와
  무관"이라던 근거는 폐기(타입은 discover 산출).

---

## 재실행 결정 테스트: 미실행 (이유)

[검증 절차]의 싼 단계(세션 로그에서 실제 명령 + discover 직후 산출 타입 확인)가 이미
결정적이다: discover ON 명령 + 그 산출이 커밋본 15종과 byte 일치. 따라서 "discover 재실행 후
타입 비교"는 추가 확실성을 주지 못하고 LLM 비용만 든다 → 실행하지 않음. (필요 시 절차는
위 단계 A 의 성공 명령을 스크래치 `--output var/scratch_prompttune` 로 그대로 재현하면 됨,
proj_ai_school/repro_run3/golden 미접촉.)

---

## 직전 STOP-1 계획 문서 정정 사항
`archive/audit/2026-06-14_live_index_plan.md` 의 다음을 정정(해당 파일도 함께 패치):
- [B] "prompt-tune 은 --no-discover-entity-types 로 돌고 15종은 외부 명시 공급" → **틀림.**
  discover ON + `--selection-method all` 로 자동 생성.
- [B] "ai_school 정확한 prompt-tune/index 호출은 레포에 없음" → **해소됨**(본 문서 (1)).
- [D] "66→16 의 원인이 entity_types 손지정" 전제 → 정정: discover ON 이 15종 생성, 66 은
  무튜닝 canary. curated 가 더 싸다는 권고 자체는 유지(비용 근거로).
