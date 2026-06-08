# GraphRAG 작업 인수인계 요약

작성일: 2026-06-08

이 문서는 데스크톱에서 진행한 GraphRAG + LLM 방 구성 실험과 Codex 대화 흐름을 다른 컴퓨터에서 이어가기 위한 요약이다. API 키, 엔드포인트 등 민감정보는 포함하지 않는다.

## 1. 현재 목표

한국사/학습용 PDF 또는 TXT를 입력받아 3D 기억의 궁전에서 사용할 수 있는 학습방을 만든다.

핵심 목표는 두 가지다.

- 사용자가 보기 좋은 UI용 방 구성과 학습 흐름 만들기
- 실제 질의응답은 GraphRAG 원본 엔티티, 관계, 커뮤니티, 원문 근거를 기반으로 유지하기

즉, 방 구성은 UI/학습 동선이고 답변 로직은 GraphRAG 원본 검색/생성 구조를 따른다.

```text
방 구조 = UI / 학습 동선
답변 = GraphRAG 원본 기반 검색 / 생성
```

## 2. 지금까지 확인한 문제

GraphRAG 커뮤니티를 그대로 3D 방으로 쓰면 다음 문제가 있었다.

- 커뮤니티 수가 너무 많거나 너무 세세하게 나뉨
- 역사 학습에 필요한 시간 순서와 GraphRAG 관계 중심 커뮤니티가 어긋남
- 조선 주제 안에 고조선 등 뜬금없는 내용이 섞이는 경우 발생
- 한 방이 너무 크거나, 반대로 특정 방은 엔티티가 거의 없는 경우 발생
- 잘린 인명, 중복 엔티티, 관계 누락, orphan degree 문제가 일부 확인됨

따라서 GraphRAG 커뮤니티를 최종 방으로 바로 쓰지 않고, 후처리 레이어가 필요하다는 결론을 냈다.

## 3. 실험 계열 정리

### 3.1 overlap200 방식

`overlap200`은 단순히 chunk overlap 값만 뜻하는 것이 아니라, 현재 프로젝트에서 만든 UI 우선 파이프라인을 가리킨다.

```text
원문 TXT
→ GraphRAG 실행
   - chunk_size = 1200
   - chunk_overlap = 200
   - entities / relationships / communities / community_reports 생성
→ GraphRAG communities와 entity 정보를 LLM에 제공
→ LLM이 UI용 방을 재설계
→ 로컬 검증기가 coverage / duplicate / density 확인
→ 필요 시 누락 community repair, 약한 supporting entity를 search_only로 내림
```

특징:

- GraphRAG 커뮤니티를 그대로 방으로 쓰지 않는다.
- LLM이 GraphRAG 결과를 참고해서 학습자가 보기 좋은 방 제목과 흐름을 만든다.
- UI 품질과 학습 흐름은 좋지만, 구조 검증과 재현성은 exp10보다 약하다.

현재 overlap200 결과 기준:

```text
방 개수: 6개
UI 설계 결과 엔티티: 214개 unique entity_id
core: 29개
supporting: 87개
search_only: 98개
background: 0개
```

방별 엔티티 수:

```text
1번방 조선 건국과 왕권 강화: 20개
2번방 세종의 문화·과학 혁신: 18개
3번방 임진왜란과 병자호란의 국가 위기: 33개
4번방 붕당 정치와 탕평 개혁: 43개
5번방 실학과 경제 개혁: 26개
6번방 조선 후기 사회 변화와 지리·국어학: 74개
```

주요 약점:

- 6번방이 catch-all 성격으로 너무 큼
- 일부 커뮤니티는 방 제목과 의미 정합성이 낮아 검토 후보로 표시됨

### 3.2 exp10 방식

`exp10`은 GraphRAG snapshot의 entity embedding을 기반으로 방을 구성하고 검증하는 실험이다.

주요 흐름:

```text
GraphRAG snapshot
→ entity embedding 기반 ward clustering
→ oversized cluster split
→ K개 방으로 merge
→ LLM이 room name + keep_titles 판단
→ keep 외 entity는 demoted
→ invariant check로 누락/중복/node_budget 검증
```

특징:

- K를 명시적으로 줄 수 있다.
- kept/demoted 구조가 명확하다.
- node_budget과 invariant check가 강하다.
- 모든 entity가 정확히 한 번 배치되는지 확인하기 좋다.
- 다만 embedding cluster 중심이라 UI용 학습 흐름과 방 제목은 overlap200보다 딱딱할 수 있다.

비유:

```text
kept = 3D 방에서 보여줄 주요 엔티티
Demoted = 방에는 덜 보이지만 답변에는 쓸 수 있는 배경 엔티티
```

현재 프로젝트의 visibility와 매핑하면 다음과 같다.

```text
exp10 kept → core + supporting
exp10 demoted → search_only + background
```

## 4. 최종 권장 방향: 하이브리드

둘 중 하나만 쓰기보다 다음 구조가 가장 안정적이다.

```text
Step 1. GraphRAG 1회 실행
→ entities, relationships, communities, reports, text_units 생성

Step 2. UI에서 방 개수 K 결정
→ 사용자가 직접 입력하거나 자동 추천 K 사용
→ K는 코드 하드코딩이 아니라 UI/사용자 선택값으로 취급

Step 3. GraphRAG community 기반 LLM UI room design
→ overlap200 방식 사용
→ GraphRAG community를 그대로 방으로 쓰지 않고 학습 흐름 중심으로 재배치
→ 학습자용 room title / learning_flow / community assignment 생성

Step 4. exp10 방식으로 entity exposure control
→ 각 room 안에서 core/supporting/search_only/background 결정
→ kept/demoted 개념 확장 적용

Step 5. invariant check
→ community coverage
→ entity duplicate/missing
→ node_budget
→ room density
→ hallucinated entity/title 제거

Step 6. answer retrieval
→ 방 구조와 무관하게 GraphRAG 원본 검색 사용
→ room assignment는 검색 scope hint로만 사용
```

## 5. K 입력 정책

방 개수 K는 시스템 내부 고정값이 아니라 UI 정책으로 둔다.

```text
자동 설정
- 사용자가 방 개수를 정하지 않으면 기본 모드
- PDF 규모, GraphRAG community 수, entity 수를 보고 추천 K 산출

직접 설정
- 사용자가 원하는 방 개수를 입력
- 예: 5개 방으로 압축, 10개 방으로 세분화
- 시스템은 해당 K를 목표로 삼되, 무리한 압축이면 검증 결과에 표시
```

주의:

- K가 너무 작으면 한 방에 너무 많은 내용이 들어간다.
- K가 너무 크면 3D 방 탐색 부담이 커진다.
- 추천 K와 직접 입력을 함께 제공하는 UI가 적합하다.

## 6. GraphRAG 단계에서 쓴 프롬프트

overlap200 GraphRAG 작업은 프롬프트 없이 돌아간 것이 아니다.

GraphRAG 1단계 프롬프트:

```text
- 엔티티 추출
- 관계 추출
- 커뮤니티 리포트 생성
```

관련 파일 예시:

```text
graphrag_root/prompts/extract_graph_history_learning.txt
graphrag_root/prompts/community_report_graph_history_learning.txt
```

후처리 LLM 프롬프트:

```text
- GraphRAG 결과를 보고 UI용 방 재설계
- 방 제목 생성
- core/supporting/search_only/background 분류
- 애매한 항목 표시
```

따라서 overlap200은 다음 둘이 모두 들어간 결과다.

```text
GraphRAG 단계 프롬프트 + 후처리 LLM 프롬프트
```

## 7. 답변 로직과 UI 방 구분

중요한 결론:

```text
UI 방 설계가 LLM 기반이어도 답변이 LLM 방 배치만 따라가면 안 된다.
```

답변은 다음 원본 근거를 기반으로 해야 한다.

```text
- GraphRAG entities
- GraphRAG relationships
- community reports
- text_units/source evidence
- local/global search 결과
```

방은 검색 범위를 좁히는 힌트로만 사용한다.

예:

```text
사용자가 방 3에서 질문
→ 우선 방 3의 entity/community를 검색 hint로 사용
→ 부족하면 GraphRAG 전체 검색으로 확장
→ 최종 답변은 source evidence 기반으로 생성
```

## 8. 남은 과제

- overlap200의 UI 품질과 exp10의 검증 구조를 실제 코드로 통합
- K 직접 입력/자동 추천 UI 설계
- node_budget을 고정값으로 둘지 전체 entity 수 대비 비율로 둘지 결정
- search_only/background entity를 답변 검색에서 어떻게 사용할지 결정
- 중복 엔티티 병합과 orphan degree 보강은 가능하면 LLM보다 알고리즘 우선 적용
- 최종 방 결과에서 의미상 애매한 항목은 UI에서 사용자에게 별도 표시하고 수동 이동 가능하게 하기

## 9. 작업 시 주의

- `.env`, API key, Azure endpoint는 GitHub에 올리지 않는다.
- 3D 방 관련 대용량 파일은 GraphRAG 작업 인수인계에 필수는 아니다.
- GraphRAG 원본 결과와 후처리 결과는 구분해서 보존한다.
- 방 설계 결과가 좋아 보여도, 답변은 반드시 GraphRAG 원본 evidence 기반으로 생성해야 한다.

## 10. 참고 파일 경로

로컬 기준 주요 파일:

```text
graphrag_quickstart/output/그래프라그 방나누기/LLM+라그/2차/overlap200/UI우선_방설계.md
graphrag_quickstart/output/그래프라그 방나누기/LLM+라그/2차/overlap200/UI우선_방설계.json
graphrag_quickstart/output/그래프라그 방나누기/LLM+라그/2차/overlap200/UI우선_플로우_정리.md
graphrag_quickstart/output/그래프라그 방나누기/LLM+라그/2차/overlap200/UI우선_방_엔티티_시각화.html
```

하이브리드 논의 문서:

```text
GraphRAG_overlap200_exp10_하이브리드_정리.md
```

## 11. 한 줄 결론

```text
GraphRAG는 지식망과 답변 근거를 만든다.
LLM은 사용자가 보기 좋은 방 구조를 설계한다.
exp10식 검증은 엔티티 보존, 노출량, 누락/중복 방지를 담당한다.
```
