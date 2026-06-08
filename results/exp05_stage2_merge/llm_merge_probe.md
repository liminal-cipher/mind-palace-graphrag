# exp5 LLM 병합 들여다보기 (partition v1, assignment v2)

읽기 전용 정리. 새로 돌리지 않았다. 기존 산출물(`llm_reliability.json`, `llm_v2_reliability.json`, `stage2_llm_v2_K5_run{1,2,3}.json`, 입력 `stage1_payloads.json`)로 충분.

공통 조건: gpt-4.1-mini, temperature=0, response_format=json_object, 입력 페이로드 동일(repro_run3 level-0 community 40개의 title+summary+members, payload 약 9.2k 토큰).

## 1. partition v1 (`exp5_llm.py`)

### 프롬프트가 정확히 뭘 줬나
- system: "방 40개를 의미가 가까운 것끼리 묶어 **정확히 K개**의 새 그룹으로 만들라. 출력 members 합이 입력 40개와 동일해야 하고 누락/중복 금지. 출력은 `{"merged_rooms": [{"new_id":0, "new_title":"...", "members":[c,c,...]}, ...]}`."
- user: payload 텍스트(community 0~39의 title+summary+members 직렬화) + "위 40개 방을 정확히 K개 그룹으로 완전 분할하라."
- 검증 실패 시 같은 호출 스레드 안에서 `[이전 시도 피드백] 누락된 community: [...], 중복: [...]` 한 줄 붙여 최대 4회 재시도.

### 16회가 왜 실패했나
`llm_reliability.json` 기준 16/16 실패 패턴:

| K | run | atte mpt | missing | duplicate |
|---|---|---|---|---|
| 5 | a | 1 | none | 22,27,29,38 |
| 5 | a | 2 | 3,18 | none |
| 5 | a | 3 | 1 | 0,29 |
| 5 | a | 4 | 18 | none |
| 5 | b | 1 | none | 27 |
| 5 | b | 2 | 1 | none |
| 5 | b | 3 | 8,18 | none |
| 5 | b | 4 | none | 26 |
| 8 | a | 1 | 9,10 | 29 |
| 8 | a | 2 | none | 0,2,16,19,24,29,36 |
| 8 | a | 3 | 10,11,28 | 29 |
| 8 | a | 4 | 1,6 | none |
| 8 | b | 1 | 1,18 | none |
| 8 | b | 2 | 9,26,28 | 22,29 |
| 8 | b | 3 | 1 | 31,32 |
| 8 | b | 4 | 18 | 0,2,16,19,20,29,31,32,36 |

판정: **JSON 파싱은 16번 다 통과**. 실패 사유는 전부 의미적 partition을 짤 때 community ID 회계가 안 맞은 것(누락 1~3개 또는 중복 1~9개). 즉 모델이 "전체 40개 = K개 그룹의 멤버 합"이라는 구조적 제약을 응답을 만드는 동안 잃어버린다.

**맥락창 탓은 아니다**. 입력 9.4k 토큰, 출력 300~430 토큰. gpt-4.1-mini의 128k 안에 들어옴. 진짜 원인은 두 가지가 합쳐진 구조 문제:
1. partition은 모델이 K개 리스트를 동시에 관리하면서 "지금까지 어느 community를 어디 넣었는가"를 누적 추적해야 한다. 한 응답 안에서 그 회계가 깨지면 누락/중복이 나온다.
2. 재시도 피드백("누락: [3,18] 수정하라")이 새 회계 오류를 유발한다. 18을 끼워넣는 동안 1이 빠지거나, dup이 새로 생기거나. 4회 다 다른 자리에서 다른 오류가 나는 게 그 증거.

K=8이 K=5보다 더 심한 것도 같은 결: 분할 대상 그룹이 늘수록 동시에 관리할 리스트 수가 늘어 회계 부담이 커진다.

부수 관찰: community 29(양반)와 18(상공업)이 dup/missing에 자주 등장. 두 community 모두 큰 정치·경제 lump의 경계에 있는 모호한 항목이라, 모델이 "여기 넣을까 저기 넣을까" 흔들리며 회계가 깨지는 진원지일 가능성. 그래도 본질은 partition 프롬프트 설계.

## 2. assignment v2 (`exp5_llm_v2.py`)

### 변경점
프롬프트만 바꿈: "방 40개 각각에 0~4 라벨을 매겨라. 출력은 `{"0":2, "1":0, ...}` 딕셔너리 하나만." 재시도 없음, 3런 독립 호출. 파서가 `object_pairs_hook`으로 dup key를 잡음.

`llm_v2_reliability.json`: 3런 모두 parsed=true, valid=true, missing=0, dup=0, out_of_range=0. **구조적 회계 오류는 0**. 다만 run1은 `groups_used=4` (라벨 2를 안 씀), run2/3는 5.

### 3런 방 묶음 (사람 읽기용)

각 community의 size는 `stage1_payloads.json` 기반. group size는 community 멤버 수의 합.

#### run1 (groups_used=4, 라벨 2 비어 있음)

| 방 라벨 | community 목록 (개수, ent 합) | 주제 |
|---|---|---|
| 0 | c2, c5, c14, c15, c22, c28, c35, c38, c39 (9개, 56 ent) | 임진왜란, 의병, 권율, 김시민, 효종 북벌, 선조 의주, 이괄, 충주 방어선, 포르투갈 조총 |
| 1 | c0, c7, c8, c11, c16, c18, c19, c20, c25, c26, c31, c32, c36 (13개, 43 ent) | 농촌, 농업, 관청, 훈민정음 국문학, 김정호 지도, 상공업, 정상기 지도, 역원, 이제마, 서당, 음운학, 유희, 이중환 |
| 3 | c1 (1개, 4 ent) | 세곡 조운 단독 |
| 4 | c3, c4, c6, c9, c10, c12, c13, c17, c21, c23, c24, c27, c29, c30, c33, c34, c37 (17개, **224 ent**) | 세조, 광해군, 세종 국방, 정조, 붕당/사림, 군역, 성리학/실학, 이성계, 태조/호패, 영조 탕평, 삼사, 외척/사화, 양반/지방, 숙종/환국, 정도전 건국, 현종 예송, 중앙군/지방군 |

#### run2 (groups_used=5)

| 방 라벨 | community 목록 (개수, ent 합) | 주제 |
|---|---|---|
| 0 | c2, c5, c14, c15, c22, c28, c35, c38, c39 (9개, 56 ent) | run1 group 0과 동일 |
| 1 | c0, c7, c18 (3개, 13 ent) | 농촌, 농업, 상공업 |
| 2 | c8, c11, c16, c19, c25, c26, c31, c32, c36 (9개, 32 ent) | 관청, 훈민정음, 지도, 사상의학, 교육, 음운학, 택리지 |
| 3 | c1, c20 (2개, 11 ent) | 조운 + 역원 (교통) |
| 4 | c3, c4, c6, c9, c10, c12, c13, c17, c21, c23, c24, c27, c29, c30, c33, c34, c37 (17개, **224 ent**) | run1 group 4와 동일 |

#### run3 (groups_used=5)

| 방 라벨 | community 목록 (개수, ent 합) | 주제 |
|---|---|---|
| 0 | c2, c5, c14, c15, c22, c28, c35, c37, c38, c39 (10개, 60 ent) | run2 group 0 + c37 (중앙군/지방군) |
| 1 | c0, c7, c18 (3개, 13 ent) | run2 group 1과 동일 |
| 2 | c8, c11, c16, c19, c20, c25, c26, c31, c32, c36 (10개, 39 ent) | run2 group 2 + c20 (역원) |
| 3 | c1 (1개, 4 ent) | run1 group 3과 동일 (단독) |
| 4 | c3, c4, c6, c9, c10, c12, c13, c17, c21, c23, c24, c27, c29, c30, c33, c34 (16개, **221 ent**) | run1/run2 group 4에서 c37 빠짐 |

### run 간 차이 (어디가 흔들리나)

안정(3런 동일): 
- "임진왜란/전란/군사 인물" 핵심 9개 community (c2, c5, c14, c15, c22, c28, c35, c38, c39)
- "정치/왕권 lump" 핵심 16개 (c3, c4, c6, c9, c10, c12, c13, c17, c21, c23, c24, c27, c29, c30, c33, c34)
- c1 (조운)이 거의 singleton

흔들림:
- **c20 (역원/교통)**: run1은 "문화" 묶음(group 1), run2는 "조운"과 한 짝(group 3), run3는 "교육·지리·학술" 묶음(group 2). 3런 다 다른 방.
- **c18 (상공업/상인)**: run1 "문화" 묶음, run2/3는 "농촌·농업" 묶음.
- **c37 (중앙군/지방군/잡색군)**: run1/run2는 "정치 lump" 안, run3는 "전란/군사" 묶음으로 이동.
- **groups_used**: run1=4 (라벨 2를 안 써서 실효 K=4), run2/3=5. 큰 흔들림이라기보다 라벨 인덱스를 모델이 일관 안 씀.

### 왜 채택 안 했는지

(a) 가장 큰 방이 **221~224 ent (3런 전부)**. embedding ward 병합과 비교: K=8 community-merge 최대 194, K=10 community-merge 최대 160. assignment v2는 가장 균형이 맞아야 할 LLM 방식인데도 정치·왕권 community 16~17개가 단일 lump로 응고된다. (b) 이 lump 안에는 정조, 광해군, 세종 국방, 영조 탕평, 양반, 정도전 건국, 현종 예송, 군역 등 시대도 주제도 다른 항목이 다 섞여 있어 "방"으로 부르기 부적합. (c) 작은 묶음(c1, c18, c20, c37)은 run마다 자리를 옮겨 partition signature가 3런 다 다름. 즉 valid는 통과하지만 결과 자체가 결정적이지 않다. (d) embedding ward는 (b) lump를 K가 커지면 부분적으로 쪼개기라도 하는데(K=10에서 160으로 줄어듦), assignment LLM은 K=5 안에서 그 lump가 그대로 살아남는다.

종합: partition v1은 산출이 안 나옴(완전 실패). assignment v2는 산출은 나오지만 (1) 결정적이지 않고 (2) embedding 대비 큰 덩어리 문제가 더 심함. 그래서 후속 실험(exp6, exp10)은 LLM 병합 대신 임베딩 직접 ward로 갔고, LLM은 cluster centroid 매핑(exp10 `_merge_llm`)과 방 위 keep/demote 분류(exp7, exp10 stage B)에만 얹는 방향으로 분업이 정리됐다.
