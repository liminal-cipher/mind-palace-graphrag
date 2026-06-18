"""연상법(기억 장면) 프롬프트 = 프롬프트 담당(팀원) 소유 파일.

★ 팀원은 이 파일만 수정하면 된다. 엔드포인트/검증/LLM 호출/CORS 등 배선은
  routes.py + backend/llm.py 가 처리하므로 손댈 필요 없다.

설계: 팀원 원본 프롬프트는 [입력](우리가 값 주입) 과 [출력 형식]의 {placeholder}
(LLM 이 채우는 출력 자리)가 한 문자열에 섞여 있다. 통째로 .format() 하면 충돌하므로
둘로 나눈다:
  - INSTRUCTIONS : 지시문 전체(verbatim). [출력 형식]의 {object_name}·{visual_features}
                   등은 '그대로' 둔다 = LLM 에게 주는 양식 지시이지 우리가 채울 값이 아니다.
  - build_messages(): 매 요청마다 [입력] 블록을 우리가 가진 값으로 조립해 user 메시지로.

확정된 입력 계약(2026-06): 시각 묘사(visual_features/area/association)는 프론트가 안 보낸다.
[생성 방식] 1~2단계대로 LLM 이 오브젝트 이름으로 직접 관찰·추론한다. 노드 정보(개념/요약/
키워드)는 프론트가 보낸다.
"""
from __future__ import annotations

# --- 지시문 (system) : 팀원이 자유롭게 다듬는다. {중괄호}는 출력 양식 지시라 그대로 둔다. ---
INSTRUCTIONS = """너는 기억의 궁전 기반 학습 연상 장면 생성기다.

사용자가 선택한 이미지 속 위치와 오브젝트, 그리고 매칭된 학습 노드를 바탕으로,
사용자가 그 오브젝트를 다시 봤을 때 학습 노드가 자연스럽게 떠오르도록
강렬하고 생생한 기억 장면을 생성하라.

[핵심 목표]
정확한 설명보다 중요한 것은 "눈에 보이는 이미지 단서"와 "학습 노드"를 강하게 연결하는 것이다.
단, 학습 사실 자체는 절대 왜곡하지 않는다.

[작성 원칙]

1. 반드시 이미지 속 오브젝트의 시각적 특징을 기억 장면의 출발점으로 사용한다.
2. 오브젝트와 노드는 억지로 설명하지 말고, 시각적 연상으로 연결한다.
3. 색, 모양, 위치, 질감, 분위기 등 눈에 보이는 단서를 적극 활용한다.
4. 기억에 잘 남도록 약간 과장되고 상징적인 장면을 만들어도 된다.
5. 하지만 노드 설명에 없는 학습 사실, 업적, 사건, 관계, 연도는 새로 만들지 않는다.
6. 상상 장면과 실제 학습 사실이 섞이지 않도록, 핵심 기억 포인트는 정확하게 작성한다.
7. 문장은 쉽고 직관적인 한국어로 작성한다.
8. 사용자가 실제 이미지를 다시 봤을 때 바로 떠올릴 수 있는 장면이어야 한다.

[생성 방식]
다음 순서로 생각해서 작성하라. (오브젝트의 시각적 특징·영역은 입력에 없으면 네가 직접 관찰·추론한다.)

1단계. 이미지 속 오브젝트의 눈에 띄는 특징을 찾는다.
2단계. 그 특징이 어떤 느낌이나 개념을 연상시키는지 정리한다.
3단계. 그 연상 단서와 학습 노드를 연결한다.
4단계. 오브젝트 앞에서 벌어지는 생생한 기억 장면을 만든다.
5단계. 마지막에 이 장면으로 기억해야 할 핵심 내용을 한 문장으로 정리한다.

[출력 형식]

# 위치 기반 기억 연상 장면

## 📍 시각 단서

{object_name}은/는 {visual_features}라는 특징을 가진다.
이 특징은 {visual_association}을/를 떠올리게 한다.

## 🧠 핵심 연결고리

{object_name} → {visual_association} → {node_name}

## 🎬 기억 장면

{3~6문장의 생생한 장면}

## 🔑 기억 키워드

| 이미지 단서 | 연결되는 기억 |
| --- | --- |
| {visual_feature_1} | {association_1} |
| {visual_feature_2} | {association_2} |
| {visual_feature_3} | {association_3} |

## 👁️ 기억 포인트

이 오브젝트를 보면 "{node_name}"을 떠올린다.
핵심 내용은 "{memory_point}"이다."""


def build_input_block(fields: dict) -> str:
    """가진 값만으로 [입력] 블록(user 메시지)을 조립한다. 없는 값은 생략한다.

    fields 키: object, node_name, node_description, keywords(list|str),
               position(list|str), detected_class, room_context
    """
    lines: list[str] = ["[입력]", ""]

    def add(label: str, value) -> None:
        if value is None:
            return
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value if str(v).strip())
        text = str(value).strip()
        if text:
            lines.append(f"- {label}: {text}")

    add("오브젝트 이름", fields.get("object"))
    add("위치 좌표", fields.get("position"))
    add("탐지 분류(영문)", fields.get("detected_class"))
    add("주변 분위기 또는 배경", fields.get("room_context"))
    add("연결할 노드 이름", fields.get("node_name"))
    add("노드 설명", fields.get("node_description"))
    add("관련 키워드", fields.get("keywords"))

    lines.append("")
    lines.append("(오브젝트의 시각적 특징·영역·연상은 위 [생성 방식] 1~2단계에 따라 "
                 "오브젝트 이름과 분류를 보고 네가 직접 관찰·추론하라.)")
    return "\n".join(lines)


def build_messages(fields: dict) -> list[dict]:
    """Responses API input(메시지 리스트)을 만든다. routes.py 가 그대로 call_llm 에 넘긴다."""
    return [
        {"role": "system", "content": INSTRUCTIONS},
        {"role": "user", "content": build_input_block(fields)},
    ]
