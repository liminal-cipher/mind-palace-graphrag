"""step5 캡션 분리 헬퍼 단위 검증 (LLM 호출 없음).

실행: python -m pytest preprocessing/steps/test_caption_split.py
또는:  python preprocessing/steps/test_caption_split.py
"""
import importlib.util
from pathlib import Path

# step5_llm 은 import 시 .env 로드/환경 읽기만 하고 네트워크는 안 탄다.
_spec = importlib.util.spec_from_file_location(
    "step5_llm", Path(__file__).with_name("step5_llm.py")
)
_s5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_s5)
split = _s5._split_printed_caption
parse = _s5._parse_caption_json


CASES = [
    # (입력, 기대 caption_title, 기대 caption)
    ("도산 서원 | 경북 안동 사림은 서원을 세워 학문 연구와 교육에 힘썼다.",
     "도산 서원", "도산 서원 | 경북 안동 사림은 서원을 세워 학문 연구와 교육에 힘썼다."),
    ("15세기 초의 세계 각 지역 주요 국가 및 제국의 분포를 보여주는 지도.",
     "", "15세기 초의 세계 각 지역 주요 국가 및 제국의 분포를 보여주는 지도."),
    ("태조 어진(전북 전주 경기전 소장)", "태조 어진", "태조 어진(전북 전주 경기전 소장)"),
    ("4군과 6진", "4군과 6진", "4군과 6진"),
    ("교지 왕이 신하에게 벼슬, 시호, 토지 등을 내려 주는 문서이다.",
     "", "교지 왕이 신하에게 벼슬, 시호, 토지 등을 내려 주는 문서이다."),
    ("", "", ""),
]


def test_split_printed_caption():
    for text, want_title, want_cap in CASES:
        title, cap = split(text)
        assert (title, cap) == (want_title, want_cap), (text, title, cap)
        # caption 은 빈 입력 외엔 항상 비어 있지 않다(빈 caption = 매칭 자동 미배치).
        if text.strip():
            assert cap.strip(), text


def test_parse_caption_json():
    assert parse('{"caption_title": "호패", "caption": "신분 증명패이다."}') == {
        "caption_title": "호패", "caption": "신분 증명패이다."
    }
    # 코드펜스 감싼 응답.
    fenced = '```json\n{"caption_title": "교지", "caption": "문서이다."}\n```'
    assert parse(fenced) == {"caption_title": "교지", "caption": "문서이다."}
    # 파싱 실패 -> 전체를 caption 으로 폴백(제목 없음).
    assert parse("그냥 설명 문장입니다.") == {
        "caption_title": "", "caption": "그냥 설명 문장입니다."
    }


if __name__ == "__main__":
    test_split_printed_caption()
    test_parse_caption_json()
    print("all caption-split tests passed")
