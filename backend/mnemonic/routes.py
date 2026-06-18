"""연상법 생성 엔드포인트 (배선 = 내 소유, 프롬프트 = 팀원 소유 prompt.py).

사용자가 3D 씬에서 핫스팟(오브젝트)을 누를 때만 프론트가 호출한다(투명성). 프론트는
핫스팟 라벨(object)과 좌표, 그리고 그 핫스팟에 매칭된 학습 노드(개념/요약/키워드)를
보낸다. 백엔드는 무상태로 prompt.build_messages 로 프롬프트를 조립해 LLM 을 호출하고
생성된 마크다운 장면을 돌려준다.

배선: app.py 에서 include_router(mnemonic.routes.router) (serve mount('/') 앞).
  POST /mnemonic -> {markdown}

입력 계약: 시각 묘사는 LLM 이 추론(프론트가 안 보냄), 노드 정보는 프론트가 전송.
camelCase(JS) 와 snake_case 둘 다 받는다(populate_by_name + alias).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.llm import call_llm
from backend.mnemonic import prompt

router = APIRouter()

_MAX_OUTPUT_TOKENS = 1500


class MnemonicRequest(BaseModel):
    # camelCase(프론트 JS) 우선, snake_case 도 허용.
    model_config = ConfigDict(populate_by_name=True)

    object: str = Field(..., description="핫스팟 라벨(예: 꽃병, 의자)")
    node_name: str = Field(..., alias="nodeName", description="연결할 학습 노드 이름(개념)")
    node_description: str = Field(..., alias="nodeDescription", description="노드 설명(요약)")
    keywords: list[str] = Field(default_factory=list, description="관련 키워드")
    position: list[float] | None = Field(default=None, alias="markerPosition",
                                          description="3D 좌표 [x,y,z]")
    detected_class: str | None = Field(default=None, alias="detectedClass",
                                       description="탐지 분류(영문, 예: vase)")
    room_context: str | None = Field(default=None, alias="roomContext",
                                      description="룸 분위기/배경(예: 룸 title)")


class MnemonicResponse(BaseModel):
    markdown: str


@router.post("/mnemonic", response_model=MnemonicResponse)
async def create_mnemonic(req: MnemonicRequest) -> MnemonicResponse:
    fields = {
        "object": req.object,
        "node_name": req.node_name,
        "node_description": req.node_description,
        "keywords": req.keywords,
        "position": req.position,
        "detected_class": req.detected_class,
        "room_context": req.room_context,
    }
    messages = prompt.build_messages(fields)
    try:
        text = await call_llm(messages, _MAX_OUTPUT_TOKENS)
    except RuntimeError as error:
        # 자격증명 미설정/네트워크/4xx -> 업스트림 의존 실패. 502 로 명확히 구분.
        raise HTTPException(status_code=502, detail=str(error))
    if not text.strip():
        raise HTTPException(status_code=502, detail="LLM 이 빈 응답을 반환했습니다.")
    return MnemonicResponse(markdown=text)
