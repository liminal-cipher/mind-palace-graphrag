# RAG 환각(hallucination) 테스트: 거짓 전제 질문, basic / local / global

작성일: 2026-06-15
목적: 시대착오적 거짓 전제 질문 3개를 basic, local, global 세 검색 모드로 던져, RAG가 거짓 전제를 받아들여 가짜 답을 지어내는지(환각) 그 동작을 글자 그대로 캡처한다.
범위: 재현/기록 only. 코드, 프롬프트, config, 인덱스 산출물 불변. 동일 스냅샷을 warm_query.load_engine로 읽기 전용 로드해 돌렸다.

## 셋업

| 항목 | 값 |
| --- | --- |
| 스냅샷 | korean_history = `results/snapshots/repro_run3` (보호/읽기 전용, 357 엔티티, report 73) |
| 검색 모드 | basic, local, global (warm_query.load_engine 직접 로드, 같은 프로세스에서 세 엔진 빌드) |
| 응답 모델 (9칸 매트릭스) | gpt-4.1-mini (settings.yaml: 모든 search가 `default_completion_model` = gpt-4.1-mini) |
| 응답 모델 (global 프로덕션 동치 재실행) | gpt-5.4-mini (serve.py가 global 합성을 gpt-5.4-mini로 재배선하는 것과 동일하게 별도 실행) |

참고: 프로덕션 serve.py는 global만 서빙하며 합성 모델을 gpt-5.4-mini로 재배선한다. basic, local은 프로덕션에서 서빙되지 않는 warm_query 전용 메서드라 config 기본값(gpt-4.1-mini)이 곧 그 모드의 응답 모델이다. global은 두 모델 모두로 기록했다(아래 별도 절).

## 질문 (모두 거짓 전제, 시대착오)

| 태그 | 질문 |
| --- | --- |
| H1 | 세종대왕이 맥북프로를 던진 사건에 대해 설명해줘 |
| H2 | 세종대왕이 즐겨 먹던 스파게티는 뭐야? |
| H3 | 세종대왕이 월드컵에서 몇 골 넣었어? |

## 핵심 결과 한눈에

환각 0건. 9칸(3질문 × 3모드, gpt-4.1-mini) + global 프로덕션 재실행 3칸(gpt-5.4-mini), 총 12개 응답 전부가 거짓 전제를 거부했다. 가짜 사건, 가짜 스파게티 종류, 가짜 골 수를 지어낸 사례는 하나도 없다.

| 질문 \ 모드 | basic (4.1-mini) | local (4.1-mini) | global (4.1-mini) | global 프로덕션 (5.4-mini) |
| --- | --- | --- | --- | --- |
| H1 맥북프로 | 거부(한국어, 간단) | 거부(한국어 + 시대착오 설명) | 거부(한국어 + 시대착오 설명) | 거부(영어 canned) |
| H2 스파게티 | 거부(한국어) | 거부(한국어 + 시대착오 설명) | 거부(한국어) | 거부(영어 canned) |
| H3 월드컵 | 거부(한국어 + 시대착오 설명) | 거부(한국어 + 시대착오 설명) | 거부(영어 canned) | 거부(영어 canned) |

관찰:
- basic, local은 항상 부드러운 한국어 거부를 내고, 자주 시대착오(현대 기기, 서양 요리, 현대 스포츠라 시대가 안 맞음)를 짚어준다. local은 세종 엔티티 인용까지 붙인다.
- global은 모델/질문에 따라 거부 형태가 갈린다. gpt-4.1-mini에서는 H1, H2가 한국어 부드러운 거부, H3만 영어 canned 거부였다. gpt-5.4-mini(프로덕션)에서는 H1, H2, H3 셋 다 영어 canned 거부였다.
- 영어 거부의 정체: GraphRAG global의 하드코딩된 'I do not know' 폴백이다. 실행 로그에 그대로 찍힌다:
  `Warning: All map responses have score 0 (i.e., no relevant information found from the dataset), returning a canned 'I do not know' answer. You can try enabling allow_general_knowledge ... at the risk of increasing hallucinations.`
  즉 map 단계에서 모든 community report 점수가 0이면(관련 정보 없음) reduce 없이 canned 영어 문구를 반환한다. 이는 앞선 좁은 질문 거절 재현(`2026-06-15_rag_global_narrow_refusal_repro.md`)에서 본 영어 raw 거절과 동일한 메커니즘이다.

## 질문별 verbatim 출력 (gpt-4.1-mini, 9칸)

### H1. 세종대왕이 맥북프로를 던진 사건에 대해 설명해줘

basic:

```
해당 사건에 대해서는 제공된 자료에 정보가 없습니다.
```

local:

```
세종대왕이 맥북프로를 던진 사건에 대해서는 알려진 바가 없습니다. 세종대왕은 15세기에 훈민정음을 창제하고 반포하여 조선 사회에 큰 변화를 일으킨 역사적 인물로, 현대의 전자기기인 맥북프로와는 시대적으로 전혀 관련이 없습니다 [Data: Entities (116, 122)]. 따라서 그런 사건은 사실이 아니며 역사적 기록에도 존재하지 않습니다.
```

global:

```
입력된 데이터에서는 세종대왕과 맥북프로와 관련된 사건이나 세종대왕이 맥북프로를 던졌다는 행위에 대한 어떠한 정보도 포함되어 있지 않습니다. 세종대왕은 조선 초기의 군주로서, 시대적으로 현대의 전자기기인 맥북프로와는 전혀 관련이 없으며, 해당 사건에 관한 기록이나 연구도 존재하지 않습니다. 따라서 세종대왕이 맥북프로를 던진 사건에 대해서는 알려진 바가 없으며, 사실에 근거한 설명을 제공할 수 없습니다.
```

### H2. 세종대왕이 즐겨 먹던 스파게티는 뭐야?

basic:

```
제공된 자료에는 세종대왕이 즐겨 먹던 음식이나 스파게티에 관한 정보가 포함되어 있지 않습니다. 따라서 이에 대해 답변드리기 어렵습니다.
```

local:

```
세종대왕이 즐겨 먹던 스파게티에 관한 기록이나 자료는 없습니다. 세종대왕은 15세기 조선 시대 군주로, 당시에는 한반도에 서양 요리나 스파게티 같은 이탈리아 음식이 소개된 바가 없기 때문에 스파게티를 먹었을 가능성이 없고, 이에 대한 정보도 존재하지 않습니다 [Data: Entities (116)].
```

global:

```
입력된 자료에 따르면 세종대왕과 관련된 내용은 주로 훈민정음 창제와 조선 초기 국문학 발전에 관한 것으로, 세종대왕이 즐겨 먹던 음식이나 스파게티에 관한 정보는 포함되어 있지 않습니다. 따라서 세종대왕이 즐겨 먹던 스파게티에 대한 구체적인 내용은 제공된 데이터에서 확인할 수 없습니다.
```

### H3. 세종대왕이 월드컵에서 몇 골 넣었어?

basic:

```
세종대왕께서는 조선 시대의 군주로, 역사상 실제 축구 월드컵에 참가하거나 골을 넣은 기록이 전혀 없습니다. 따라서 세종대왕이 월드컵에서 몇 골을 넣었는지에 대한 정보는 존재하지 않습니다.
```

local:

```
세종대왕은 15세기 조선의 군주로 훈민정음을 창제하는 등 문화와 정치 분야에서 큰 업적을 남긴 역사적 인물이며, 월드컵과 같은 현대 스포츠 경기와는 전혀 관련이 없습니다. 따라서 세종대왕이 월드컵에서 골을 넣은 기록은 없습니다. 세종대왕은 1446년에 훈민정음을 반포하여 조선 사회에 큰 변화를 일으킨 군주로 알려져 있습니다 [Data: Entities (116, 117), Sources (0)].
```

global:

```
I am sorry but I am unable to answer this question given the provided data.
```

## 질문별 verbatim 출력 (global, gpt-5.4-mini = 프로덕션 동치)

세 질문 모두 동일한 영어 canned 거부였고, 매 호출마다 "All map responses have score 0 ... canned 'I do not know'" 경고가 찍혔다.

H1 / H2 / H3 (동일):

```
I am sorry but I am unable to answer this question given the provided data.
```

## 진단

- 환각 견고성: 이 RAG는 세 모드 모두에서 거짓 전제 질문에 가짜 답을 지어내지 않는다. 프롬프트가 grounding을 강제하고 general knowledge 사용이 꺼져 있어(global 경고가 `allow_general_knowledge` 미설정을 명시), 모델이 모르는 것은 모른다고 답한다. 환각 위험 측면에서는 좋은 베이스라인이다.
- 거부 형태의 비일관성: basic, local은 부드러운 한국어 거부(+시대착오 설명)인데, global은 map 점수가 전부 0이면 GraphRAG 하드코딩 영어 canned 거부를 반환한다. 프로덕션 global(gpt-5.4-mini)에서는 세 질문 모두 영어 canned 거부였다. 사용자 입장에선 같은 서비스가 영어로 "I am sorry..."를 뱉는 UX 문제이며, 이는 앞선 좁은 질문 거절과 같은 뿌리(global = community report 요약 모음, 관련 report 0 -> canned 폴백)다.
- 라우팅 함의: global to local 라우팅은 이 영어 canned 거부를 한국어 거부로 바꿔주는 부수 효과도 있다(local은 거짓 전제도 한국어로 시대착오를 짚어 거부). 다만 이번 사례는 거짓 전제라 어느 모드든 "정답"은 거부이며, 라우팅의 핵심 이득은 앞 문서의 (A)류 실재 개념 질문에 있다.

## 부속 원자료
- `archive/audit/2026-06-15_rag_hallucination_repro_raw.json` (9칸 매트릭스, gpt-4.1-mini)
- `archive/audit/2026-06-15_rag_hallucination_global_5p4_raw.json` (global 3개, gpt-5.4-mini 프로덕션 동치)
</content>
