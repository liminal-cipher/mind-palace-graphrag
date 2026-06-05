# LLM+라그 UI 우선 방 설계 플로우

## 핵심 관점

답변은 GraphRAG 지식망을 사용하고, 방은 사용자가 보는 UI 구조로 사용한다.

## 단계

1. GraphRAG 원본 로드
- source: C:\Users\USER\Desktop\3차 프로젝트\3cha-project\그래프라그\graphrag_quickstart\output\그래프라그 방나누기\LLM+라그\2차\overlap100\graphrag_root\output
- 엔티티, 관계, 커뮤니티, 원문 근거 ID를 답변용 백엔드 지식망으로 유지한다.

2. LLM UI 방 설계
- GPT-5.4 mini 사용
- GraphRAG 커뮤니티를 그대로 방으로 쓰지 않는다.
- 사용자가 보기 좋은 시대/주제 흐름을 우선한다.
- 작은 주제는 background/search_only로 보존할 수 있다.

3. 로컬 검증
- 모든 community_id가 내부 coverage에 정확히 한 번 포함되는지 검사한다.
- 중복 entity_id를 제거한다.
- core/supporting이 전체 대비 일정 비율을 넘으면 supporting/search_only로 낮춘다.

4. 결과 해석
- visible/core/supporting은 UI 노출용이다.
- background/search_only는 GraphRAG 답변 근거로 유지된다.
- 따라서 UI가 깔끔해도 질문 답변은 GraphRAG 전체 구조를 사용할 수 있다.
