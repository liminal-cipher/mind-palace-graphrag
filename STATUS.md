# 회랑(Hoerang) GraphRAG 파이프라인 — 프로젝트 현황 (STATUS)

> 새 작업 세션이나 팀원이 맥락을 빠르게 잡기 위한 핸드오프 문서다.
> 세션 메모리에 기대지 말고 이 문서 + 코드/결과 파일을 기준으로 한다.
> 마지막 갱신: 2026-06-03

## 레포 상태
- 정리 완료, 첫 커밋 `e6cfb37` (master, 루트). working tree clean.
- 리포트는 `results/reports/` 아래 `NN_slug.md` 형식. frontmatter 규약: `results/reports/REPORT_TEMPLATE.md`. 원본에서 현재 파일로의 매핑: `results/reports/INDEX.md`.
- 시크릿: 키와 엔드포인트 모두 환경변수 참조. `GRAPHRAG_API_KEY`, `GRAPHRAG_API_BASE`. 로컬은 `.env`로 주입(gitignored), 신규 셋업은 `.env.example` placeholder 복사 후 채움.
- gitignore: `output/`, `logs/`, `results/snapshots/`, `input/`, `cache/`, `.env`, `.venv/`, `__pycache__/`, `*.pyc`.

## 프로젝트 한 줄
학습 자료(예: 한국사 교과서)를 GraphRAG로 돌려 개념을 커뮤니티("방")로 묶고,
level 0 커뮤니티를 "건물"로 써서 1인칭 3D 기억의 궁전으로 만드는 암기 도구.
이 레포는 그중 GraphRAG 파이프라인 + 방 병합 실험 부분이다.

## 절대 제약
건물(level 0 커뮤니티)은 권장 5개, 최대 10개. 건물마다 3D 인테리어를 손으로 만들어서
건물 수 = 3D팀 작업량이다. 11개 이상 제작 불가.

## 핵심 문제
- 자동 묶기가 건물을 31~40개 뱉는다 (천장 10의 3~4배).
- 하이퍼파라미터로 건물 수 못 줄임 (확인됨).
- use_lcc=true는 40에서 16으로 줄지만 핵심 개념 31%(측우기·의병·사료 등) 소실 → 탈락.
- 결론: 작은 방을 큰 방에 "흡수(병합)". 버리지 않고 합친다. 이게 실험 5.

## 베이스 스냅샷 (중요)
- `results/snapshots/repro_run3/` = 고정된 작업 베이스. 357 entities, level 0 = 40 커뮤니티(ID 0~39).
- GraphRAG 추출은 같은 설정이어도 ±10 흔들린다(재현성 문제). 그래서 매번 새로 추출하지 말고
  이 스냅샷만 입력으로 쓴다. 팀원도 이 스냅샷에서 출발해야 재현된다.

## 실험 5 현황 (지금 여기)
방 40개를 ≤10개로 병합하는 두 방법 비교 중.

### 임베딩 병합 — 성공, 결정적
- `community_full_content` 방 벡터(level 0, 40×1536, L2 정규화)를 scipy hierarchical로 클러스터링.
- ward linkage가 average보다 좋음 (silhouette K=5 0.083 / K=8 0.099 / K=10 0.098).
- 두 번 돌려 완전히 동일(run_a == run_b). 결과: `results/exp5/stage2_emb_K{5,8,10}.json`.

### LLM 병합 (partition 방식) — 완전 실패
- gpt-4.1-mini에 방 40개 주고 "K개 그룹 만들고 멤버 ID 다 나열" 시킴.
- K=5/8 양쪽, run 2회, 매 시도 4회 전부 실패. 매번 다른 community 누락/중복.
- temp=0인데도 재시도 피드백이 prompt를 바꿔 응답이 변함.
- 원인: LLM은 40개 ID를 빠짐없이 분배하는 "부기" 작업에 약함. 로그: `results/exp5/llm_reliability.json`.
- LLM stage2 파일은 생성 안 됨(성공 0회).

## 확정된 설계 결정
- 비교 K 고정: K=5(제품 권장치)와 K=8.
- 네이밍은 묶기와 분리: 두 방법 모두 "멤버 방 중 size 최대인 방 title 빌리기(borrow)"로 이름 지음.
  LLM이 만든 이름은 `llm_suggested_title`로 따로 저장만 하고 head-to-head 이름엔 안 씀.
- 누락 community를 코드로 끼워넣어 메우기 금지 (방법 오염). 못 하면 "실패"로 기록.
- 3D 슬롯 JSON 결정: Building.summary = 멤버 방 title 리스트(A2) / Locus.order = degree 내림차순(B1) /
  relationship 미노출(C) / 큰 건물 size 그대로 노출하되 리스크 명시(D1).

## 데이터 함정 (틀리면 다 깨짐)
- join 키 = 정수 community 컬럼(0~72). level 0 필터 필수 (40개, ID 0~39).
- lancedb `community_full_content`는 73개 전부 들고 있음 → level 0만 골라야 40개.
- 방 멤버 = `communities.entity_ids`(UUID 리스트) → `entities.id`(UUID)로 조회.
- relationships는 source/target이 "이름"이라 ID 조인 불가 → 미사용.
- ID 3종: community_reports/lancedb = 128자 해시, entities/communities = UUID, community 컬럼 = 정수.

## 알려진 품질 문제
- 194 덩어리: 임베딩에서 13개 community [4,5,9,10,13,17,23,24,27,29,30,33,34]가 한 건물(size 194)로
  뭉쳐 K=8에서도 안 쪼개짐. 그래프의 주요 연결 컴포넌트(LCC). 건물 하나가 과대 → 쪼개기 필요.
- silhouette 낮음(~0.08~0.10): 묶음 경계가 흐릿함. 한국사 주제가 원래 서로 얽혀서 그런 면도 있음.
  객관 지표가 약하니 품질 판단을 이 숫자에만 기대면 안 됨.

## 다음 할 일 (방향)
1. **지금 바로**: exp5 LLM 병합 v2 (assignment 방식). "K개 그룹 만들어라"가 아니라 "community 0~39 각각에 그룹 라벨을 붙여라". 입력을 훑으며 라벨만 다니까 누락·중복이 구조적으로 거의 안 생김. v1 partition 실패의 공정 재시험.
2. 하이브리드: 임베딩이 묶고 LLM이 검수(필요하면 교정). LLM 검수는 주제를 안 가려서 다른 자료로 확장 가능.
3. 3-way 비교: 임베딩 / LLM(v2) / 하이브리드 × {완전성, 재현성, 품질, 크기분포, 시간, 비용}.
4. 재현 패키지: README/requirements.txt/.env.example/.gitignore는 완료. `run_all.py`는 3-way 비교 끝난 뒤. 코드 재구성(루트 `exp5_*.py` 이동 등)도 동시점. 지금 옮기면 경로/import 깨짐.

## 품질 검사(QA) 방침 (gold label 없음)
- 개인용 암기 도구라 "객관적 정답 묶음"은 없다. 최종 품질 = 사용자가 자기 궁전을 수긍하는가.
  런타임 HITL = 2D 미리보기 → OK/다시묶기 루프(제품 설계에 이미 있음).
- 개발 단계 평가: 한국사 "같이/떨어져" 체크리스트(임진왜란끼리 한 건물, 임진왜란과 조선건국은 다른 건물 등)
  5~10개로 채점. 이 체크리스트는 LLM 검수기가 사람 판단과 맞는지 보정하는 용도로도 씀.
  (맞으면 규칙 못 만드는 다른 자료에도 검수기를 믿고 확장 가능.)

## 재현성 두 층
- 임베딩(수학) 부분: 완벽 재현. 팀원이 돌리면 숫자까지 동일.
- LLM 부분: 재현 안 됨 + API 과금. → 결과 JSON을 기록으로 남기고, 코드도 남겨 누구나 재실행 가능하게.
- 스냅샷은 반드시 공유. 없으면 재현 불가. 용량 크면 일반 git 말고 공유 드라이브나 git-lfs.

## 환경
- Azure OpenAI: gpt-4.1-mini(병합) + text-embedding-3-small(추출). 키와 엔드포인트 모두 환경변수(`GRAPHRAG_API_KEY`, `GRAPHRAG_API_BASE`). 로컬은 `.env`로 주입(gitignored).
- 패키지: openai 2.38.0, scipy 1.17.1, scikit-learn 1.8.0, pandas, numpy, lancedb. Python 3.13.

## 실험 히스토리 맵
- baseline: 첫 측정, 건물 약 31개.
- exp2 (max15): max_cluster_size 테스트. 스냅샷 `snapshots/exp2_max15`.
- exp4_lcc_true: use_lcc=true 테스트. 핵심 31% 소실로 탈락. 스냅샷 `snapshots/exp4_lcc_true`.
- repro_run2 / repro_run3: 재현성 확인 런. run3 = 실험 5 베이스(357 ent, 40방).
- snap_max10 / snap_max20: max_cluster_size 스냅샷.
- exp5: 방 병합 실험 (현재). 코드는 `results/exp5/` 아래 `exp5_lib.py` / `exp5_embed.py` / `exp5_llm.py` / `exp5_llm_v2.py` / `type_select_test.py`.
- 리포트(`results/reports/`): `00_baseline`, `01_max15`, `02_snap_max10`, `02_snap_max20`, `03_repro_step{1_snapshot, 2_variance, 3_summary}`, `04_use_lcc`, `05_exp5_data_contract`. 규약과 매핑은 `REPORT_TEMPLATE.md`, `INDEX.md`.
