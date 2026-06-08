{
  "room_count_decision": {
    "selected_room_count": 6,
    "reason": "문서의 중심 축이 조선 전기 국가 형성, 세종 문화·과학, 중기 정치·전쟁, 후기 붕당 정치, 후기 실학, 후기 사회·문화/지리·국어학으로 비교적 선명하게 나뉜다. 4개로 줄이면 후기 실학과 후기 사회문화가 과밀해지고, 6개면 학습 흐름이 가장 자연스럽게 분리된다."
  },
  "rooms": [
    {
      "room_no": 1,
      "title": "조선 건국과 왕권 강화",
      "learning_flow": "위화도 회군과 조선 건국을 출발점으로, 한양 천도·경복궁·과전법·의정부/6조·호패법까지 이어지며 새 왕조의 통치 틀을 익힌다.",
      "ui_design_reason": "조선의 출발과 국가 운영의 뼈대를 한 방에 모으면 학습자가 시대의 시작을 한눈에 이해할 수 있다. 건국, 수도, 제도 정비가 서로 강하게 연결되어 있어 UI상 가장 깔끔한 첫 방이다.",
      "visible_communities": [5, 36],
      "background_communities": [
        {
          "community_id": 17,
          "reason": "계유정난과 세조 집권은 왕권 강화 흐름의 연장선이지만, 방 제목을 흐릴 수 있어 배경으로 보존한다."
        },
        {
          "community_id": 10,
          "reason": "세조의 직전법은 왕권 강화와 재정 정비의 보조 축이라 배경으로 두면 흐름이 더 정돈된다."
        }
      ],
      "source_communities": [5, 36, 17, 10],
      "subzones": [
        {
          "title": "건국의 출발",
          "source_communities": [5, 17],
          "entity_ids": [1, 12, 13, 20, 7, 199, 200, 201, 202, 203, 208]
        },
        {
          "title": "왕권과 행정 체계",
          "source_communities": [5, 36, 10],
          "entity_ids": [4, 5, 6, 21, 25, 26, 29, 30, 33, 35, 47, 48, 106, 107]
        }
      ],
      "entities": [
        {
          "entity_id": 1,
          "title": "조선 건국",
          "visibility": "core",
          "reason": "방의 출발점이 되는 핵심 사건이라 반드시 전면에 보여야 한다."
        },
        {
          "entity_id": 12,
          "title": "태조 이성계",
          "visibility": "core",
          "reason": "건국의 주체로서 방 제목과 직접 연결되는 핵심 인물이다."
        },
        {
          "entity_id": 13,
          "title": "정도전",
          "visibility": "core",
          "reason": "조선의 국가 이념과 제도 설계를 대표해 건국 학습의 핵심이다."
        },
        {
          "entity_id": 20,
          "title": "이성계",
          "visibility": "supporting",
          "reason": "태조와 같은 인물 맥락을 보강하지만 중복성이 있어 보조로 두는 편이 깔끔하다."
        },
        {
          "entity_id": 7,
          "title": "위화도 회군",
          "visibility": "supporting",
          "reason": "건국의 전사(前史)를 설명하는 중요한 전환점이라 학습 흐름을 깊게 해준다."
        },
        {
          "entity_id": 199,
          "title": "조선 제1차 왕자의 난",
          "visibility": "supporting",
          "reason": "초기 왕권 재편을 설명하는 핵심 사건이지만 건국 자체보다 한 단계 뒤라 보조가 적절하다."
        },
        {
          "entity_id": 21,
          "title": "한양 천도",
          "visibility": "core",
          "reason": "새 왕조의 공간적 중심을 보여주는 핵심 제도 변화다."
        },
        {
          "entity_id": 4,
          "title": "경복궁",
          "visibility": "supporting",
          "reason": "한양 천도의 결과를 시각적으로 이해시키는 대표 문물이라 보조로 적합하다."
        },
        {
          "entity_id": 5,
          "title": "한양",
          "visibility": "supporting",
          "reason": "수도 개념을 보강하지만 제목을 흐릴 수 있어 supporting이 적절하다."
        },
        {
          "entity_id": 6,
          "title": "과전법",
          "visibility": "core",
          "reason": "조선 초기 경제 기반과 신진 세력의 결합을 보여주는 핵심 정책이다."
        },
        {
          "entity_id": 47,
          "title": "의정부",
          "visibility": "core",
          "reason": "조선 중앙 정치 구조를 대표하는 핵심 기관이다."
        },
        {
          "entity_id": 48,
          "title": "6조",
          "visibility": "supporting",
          "reason": "의정부와 함께 중앙 행정 체계를 설명하지만 단독 핵심성은 한 단계 낮다."
        },
        {
          "entity_id": 25,
          "title": "태종 이방원",
          "visibility": "core",
          "reason": "호패법과 왕권 강화의 주체로서 방의 후반부 핵심 인물이다."
        },
        {
          "entity_id": 26,
          "title": "호패법",
          "visibility": "core",
          "reason": "인구 통제와 왕권 강화를 상징하는 대표 정책이라 직접 노출이 필요하다."
        },
        {
          "entity_id": 29,
          "title": "세조",
          "visibility": "supporting",
          "reason": "왕권 강화의 연속선상에 있으나 방 제목이 태종 중심이므로 보조로 둔다."
        },
        {
          "entity_id": 30,
          "title": "직전법",
          "visibility": "supporting",
          "reason": "재정 정비를 설명하는 중요한 정책이지만 왕권 강화의 보조 설명으로 충분하다."
        },
        {
          "entity_id": 33,
          "title": "국방 강화",
          "visibility": "search_only",
          "reason": "왕권 강화와 연결되지만 너무 일반적이라 UI 클릭 요소로는 약하다."
        },
        {
          "entity_id": 35,
          "title": "이방원",
          "visibility": "supporting",
          "reason": "태종과 동일 맥락의 인물로, 호패법 이해를 돕는 보조 개념이다."
        },
        {
          "entity_id": 106,
          "title": "신흥 무인 세력",
          "visibility": "search_only",
          "reason": "건국 배경의 세부 맥락이지만 방의 핵심 축은 아니라 검색용이 적절하다."
        },
        {
          "entity_id": 107,
          "title": "신진 사대부",
          "visibility": "search_only",
          "reason": "건국 이념의 배경 설명으로는 유용하지만 UI 전면 노출에는 다소 추상적이다."
        }
      ],
      "risk_flags": [
        "세조와 태종이 모두 왕권 강화 축에 있어 인물 중복 인상이 생길 수 있다.",
        "건국 방에 제도와 인물이 많아 보일 수 있어, 하위구역으로 시기별 분리를 유지해야 한다."
      ]
    },
    {
      "room_no": 2,
      "title": "세종의 문화·과학 혁신",
      "learning_flow": "훈민정음과 집현전에서 시작해 과학 기구, 실록 편찬, 해상 방어까지 이어지며 세종 시대의 국가 혁신을 체험한다.",
      "ui_design_reason": "세종은 문자·학문·과학·국방이 모두 연결되는 강한 중심축이라 독립 방으로 두는 것이 가장 직관적이다. 학습자가 ‘세종 시대의 성과’를 한 번에 묶어 이해하기 좋다.",
      "visible_communities": [29, 30, 1],
      "background_communities": [
        {
          "community_id": 7,
          "reason": "조선왕조실록과 역사 편찬은 세종 방의 문화·기록 축을 보강하지만, 핵심은 세종 혁신이므로 배경으로 둔다."
        }
      ],
      "source_communities": [29, 30, 1, 7],
      "subzones": [
        {
          "title": "문자와 학문",
          "source_communities": [29, 7],
          "entity_ids": [0, 8, 11, 27, 28, 88, 89, 91, 92, 97, 100, 102]
        },
        {
          "title": "북방과 해상 방어",
          "source_communities": [1, 30],
          "entity_ids": [38, 39, 40, 41, 42, 43]
        }
      ],
      "entities": [
        {
          "entity_id": 27,
          "title": "세종",
          "visibility": "core",
          "reason": "방의 중심 인물로 모든 학습 흐름을 묶는 핵심이다."
        },
        {
          "entity_id": 8,
          "title": "훈민정음",
          "visibility": "core",
          "reason": "세종 혁신의 상징이자 가장 직접적인 학습 포인트다."
        },
        {
          "entity_id": 28,
          "title": "집현전",
          "visibility": "supporting",
          "reason": "훈민정음과 학문 정책을 설명하는 핵심 기관이라 보조로 적절하다."
        },
        {
          "entity_id": 11,
          "title": "해시계(앙부일구)",
          "visibility": "supporting",
          "reason": "과학 혁신을 보여주는 대표 기구지만 훈민정음보다 비중이 낮다."
        },
        {
          "entity_id": 97,
          "title": "측우기",
          "visibility": "supporting",
          "reason": "세종 과학 성과를 구체화하는 대표 사례라 학습에 유용하다."
        },
        {
          "entity_id": 100,
          "title": "혼천의",
          "visibility": "supporting",
          "reason": "과학 기구 묶음의 일부로 의미가 크지만, 개별 핵심성은 중간 수준이다."
        },
        {
          "entity_id": 102,
          "title": "물시계(자격루)",
          "visibility": "supporting",
          "reason": "세종 과학 기술의 대표 사례로 클릭 가치가 충분하다."
        },
        {
          "entity_id": 88,
          "title": "용비어천가",
          "visibility": "supporting",
          "reason": "훈민정음 활용의 문화 성과를 보여주지만 보조 사례로 충분하다."
        },
        {
          "entity_id": 89,
          "title": "조선왕조실록",
          "visibility": "supporting",
          "reason": "기록 문화의 핵심이지만 세종 방에서는 보조 축으로 두는 편이 균형적이다."
        },
        {
          "entity_id": 0,
          "title": "국사편찬위원회",
          "visibility": "search_only",
          "reason": "실록 편찬의 현대적 맥락 설명용으로는 유용하지만 학습 핵심 개념은 아니다."
        },
        {
          "entity_id": 91,
          "title": "고려사",
          "visibility": "search_only",
          "reason": "역사 편찬의 비교 사례로는 의미가 있으나 세종 방의 중심과는 거리가 있다."
        },
        {
          "entity_id": 92,
          "title": "고려사절요",
          "visibility": "search_only",
          "reason": "고려사와 함께 묶이는 보조 문헌이라 UI 전면 노출은 과하다."
        },
        {
          "entity_id": 38,
          "title": "최윤덕",
          "visibility": "supporting",
          "reason": "북방 방어의 실제 수행 인물로 세종 국방 정책을 구체화한다."
        },
        {
          "entity_id": 39,
          "title": "김종서",
          "visibility": "supporting",
          "reason": "4군 6진과 연결되는 핵심 인물이라 북방 축에서 중요하다."
        },
        {
          "entity_id": 40,
          "title": "4군과 6진",
          "visibility": "core",
          "reason": "세종의 북방 국경 확장 정책을 대표하는 핵심 개념이다."
        },
        {
          "entity_id": 41,
          "title": "여진족 포섭·회유 정책",
          "visibility": "supporting",
          "reason": "4군 6진과 함께 세종 북방 정책의 균형을 설명한다."
        },
        {
          "entity_id": 42,
          "title": "조선 수군 강화",
          "visibility": "supporting",
          "reason": "해상 방어의 정책 축으로 의미가 있으나 세종 혁신 전체에서는 보조다."
        },
        {
          "entity_id": 43,
          "title": "세종의 쓰시마 섬 토벌",
          "visibility": "supporting",
          "reason": "해상 방어 성과를 보여주는 사건이라 학습 흐름을 보강한다."
        }
      ],
      "risk_flags": [
        "문자·과학·국방이 모두 강해 방이 넓어 보일 수 있으므로 하위구역 분리가 필요하다.",
        "조선왕조실록과 국사편찬위원회는 기록 맥락으로만 보이게 해야 제목이 흐려지지 않는다."
      ]
    },
    {
      "room_no": 3,
      "title": "임진왜란과 병자호란의 국가 위기",
      "learning_flow": "임진왜란에서 수군·의병·외교 회복을 배우고, 이어 병자호란과 북벌 운동으로 조선 중기의 대외 위기 대응을 정리한다.",
      "ui_design_reason": "전쟁과 외교 위기는 학습자가 사건 흐름으로 이해하기 쉬워 하나의 큰 방으로 묶는 것이 좋다. 임진왜란과 병자호란은 서로 이어지는 위기 서사라 UI상 연결성이 높다.",
      "visible_communities": [4, 14, 9, 23],
      "background_communities": [
        {
          "community_id": 30,
          "reason": "세종의 해상 방어는 전쟁사 배경으로 연결되지만, 이 방의 중심은 임진왜란·병자호란이므로 배경으로 둔다."
        }
      ],
      "source_communities": [4, 14, 9, 23, 30],
      "subzones": [
        {
          "title": "임진왜란의 전개",
          "source_communities": [4],
          "entity_ids": [3, 14, 15, 16, 144, 145, 153, 154, 155, 156, 157, 158, 159, 160, 161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 171, 172, 173]
        },
        {
          "title": "병자호란과 북벌",
          "source_communities": [14, 9, 23],
          "entity_ids": [146, 147, 148, 149, 150, 151, 152, 174, 175, 176, 177, 179, 182, 183, 184, 185, 186, 187, 188, 189, 190, 191, 192, 193, 194, 195, 196, 197, 198, 209, 210, 224]
        }
      ],
      "entities": [
        {
          "entity_id": 16,
          "title": "임진왜란",
          "visibility": "core",
          "reason": "방의 첫 번째 중심 사건으로, 전쟁사 전체를 여는 핵심이다."
        },
        {
          "entity_id": 3,
          "title": "이순신",
          "visibility": "core",
          "reason": "임진왜란 학습에서 가장 상징적인 인물이라 전면 노출이 필요하다."
        },
        {
          "entity_id": 14,
          "title": "조선 수군",
          "visibility": "core",
          "reason": "해상 방어의 핵심 축으로 임진왜란 이해에 필수적이다."
        },
        {
          "entity_id": 156,
          "title": "의병",
          "visibility": "supporting",
          "reason": "전쟁의 민중 동원을 설명하는 핵심 보조 개념이다."
        },
        {
          "entity_id": 145,
          "title": "행주 대첩",
          "visibility": "supporting",
          "reason": "육상 전투의 대표 승리로 전쟁 흐름을 보강한다."
        },
        {
          "entity_id": 15,
          "title": "한산도 대첩",
          "visibility": "supporting",
          "reason": "이순신과 조선 수군의 결정적 승리를 보여주는 대표 사례다."
        },
        {
          "entity_id": 171,
          "title": "통신사 파견",
          "visibility": "supporting",
          "reason": "전쟁 이후 외교 회복을 설명하는 중요한 후속 개념이다."
        },
        {
          "entity_id": 172,
          "title": "통신사",
          "visibility": "supporting",
          "reason": "통신사 파견의 주체로서 외교 흐름을 이해시키는 데 유용하다."
        },
        {
          "entity_id": 162,
          "title": "정유재란",
          "visibility": "supporting",
          "reason": "임진왜란의 연장선 사건으로 전쟁 서사를 완성한다."
        },
        {
          "entity_id": 151,
          "title": "병자호란",
          "visibility": "core",
          "reason": "조선 중기 대외 위기의 또 다른 중심 사건이라 독립적으로 강조할 가치가 있다."
        },
        {
          "entity_id": 149,
          "title": "인조",
          "visibility": "core",
          "reason": "병자호란과 외교 노선의 중심 인물이다."
        },
        {
          "entity_id": 148,
          "title": "중립 외교 정책",
          "visibility": "supporting",
          "reason": "광해군 시기의 외교 전략을 설명하는 핵심 개념이다."
        },
        {
          "entity_id": 147,
          "title": "광해군",
          "visibility": "supporting",
          "reason": "중립 외교와 인조반정의 연결고리로 중요하다."
        },
        {
          "entity_id": 182,
          "title": "인조반정",
          "visibility": "supporting",
          "reason": "병자호란 이전 정치 변동을 설명하는 핵심 사건이다."
        },
        {
          "entity_id": 183,
          "title": "정묘호란",
          "visibility": "supporting",
          "reason": "병자호란의 전초 사건으로 위기 흐름을 이어준다."
        },
        {
          "entity_id": 152,
          "title": "북벌 운동",
          "visibility": "core",
          "reason": "병자호란 이후 조선의 대응을 대표하는 핵심 개념이다."
        },
        {
          "entity_id": 185,
          "title": "효종",
          "visibility": "supporting",
          "reason": "북벌 운동의 주체로서 중요하지만 사건 축보다 한 단계 낮다."
        },
        {
          "entity_id": 209,
          "title": "김상헌",
          "visibility": "supporting",
          "reason": "항전론을 대표하는 인물로 병자호란의 정치적 긴장을 보여준다."
        },
        {
          "entity_id": 210,
          "title": "최명길",
          "visibility": "supporting",
          "reason": "강화론을 대표해 병자호란 대응의 양면성을 설명한다."
        },
        {
          "entity_id": 146,
          "title": "남한산성",
          "visibility": "supporting",
          "reason": "병자호란의 상징적 공간이지만 방 제목을 흐릴 정도로 중심적이지는 않다."
        },
        {
          "entity_id": 184,
          "title": "삼전도 강화",
          "visibility": "supporting",
          "reason": "병자호란의 결과를 보여주는 핵심 사건이라 보조로 적절하다."
        },
        {
          "entity_id": 188,
          "title": "북한산성",
          "visibility": "search_only",
          "reason": "북벌과 연결되지만 대표성은 남한산성보다 낮아 검색용이 적절하다."
        },
        {
          "entity_id": 191,
          "title": "나선 정벌",
          "visibility": "search_only",
          "reason": "병자호란 이후의 파생 군사 활동으로, 핵심 학습 흐름에서는 주변적이다."
        },
        {
          "entity_id": 192,
          "title": "청나라",
          "visibility": "supporting",
          "reason": "병자호란과 북벌의 상대 세력으로서 직접적인 이해를 돕는다."
        },
        {
          "entity_id": 174,
          "title": "후금",
          "visibility": "search_only",
          "reason": "병자호란 전사 설명에는 필요하지만 청나라와 중복되어 전면 노출은 과하다."
        },
        {
          "entity_id": 175,
          "title": "명나라",
          "visibility": "search_only",
          "reason": "중립 외교의 배경으로는 중요하지만 UI에서는 보조 설명으로 충분하다."
        },
        {
          "entity_id": 176,
          "title": "허준",
          "visibility": "search_only",
          "reason": "동의보감은 중요한 문화사이지만 이 방의 전쟁 중심성과는 거리가 있다."
        },
        {
          "entity_id": 177,
          "title": "동의보감",
          "visibility": "search_only",
          "reason": "전쟁기 보건 맥락의 주변 정보라 검색용으로 보존한다."
        },
        {
          "entity_id": 193,
          "title": "이이첨",
          "visibility": "search_only",
          "reason": "인조반정의 배경 인물로는 의미 있으나 클릭 핵심으로는 약하다."
        },
        {
          "entity_id": 194,
          "title": "정인홍",
          "visibility": "search_only",
          "reason": "정치적 배경 인물로는 유용하지만 방의 중심 흐름을 흐릴 수 있다."
        },
        {
          "entity_id": 195,
          "title": "임해군",
          "visibility": "search_only",
          "reason": "인조반정 희생자 맥락의 세부 항목이라 검색용이 적절하다."
        },
        {
          "entity_id": 196,
          "title": "영창대군",
          "visibility": "search_only",
          "reason": "정치 희생자 세부 사례로는 의미 있으나 UI 전면 노출은 과하다."
        },
        {
          "entity_id": 197,
          "title": "김제남",
          "visibility": "search_only",
          "reason": "인조반정 관련 희생자이지만 핵심 개념은 아니다."
        },
        {
          "entity_id": 198,
          "title": "능창군",
          "visibility": "search_only",
          "reason": "희생자 목록의 세부 항목으로, 학습 UI에서는 검색용이 적절하다."
        },
        {
          "entity_id": 224,
          "title": "북인",
          "visibility": "search_only",
          "reason": "붕당 정치와 연결되지만 이 방에서는 정치 세력의 세부 분류라 보조 이하가 적절하다."
        }
      ],
      "risk_flags": [
        "임진왜란과 병자호란이 모두 커서 전쟁 방이 과밀해질 수 있다.",
        "광해군·인조·효종이 함께 보여 인물 축이 복잡해질 수 있으므로 하위구역 분리가 중요하다."
      ]
    },
    {
      "room_no": 4,
      "title": "붕당 정치와 탕평 개혁",
      "learning_flow": "사림의 성장과 붕당 형성에서 출발해 예송·환국·비변사 권력화로 이어지고, 영조·정조의 탕평책으로 정리한다.",
      "ui_design_reason": "조선 후기 정치사는 갈등과 조정의 반복이므로, 붕당 정치와 탕평책을 한 방에 묶으면 흐름이 매우 선명하다. 정치 세력과 제도, 왕의 개혁이 서로 맞물려 학습 구조가 좋다.",
      "visible_communities": [24, 25, 12, 27],
      "background_communities": [
        {
          "community_id": 9,
          "reason": "광해군과 인조반정은 붕당 정치의 한 국면이지만 전쟁 방과 겹치므로 배경으로 둔다."
        }
      ],
      "source_communities": [24, 25, 12, 27, 9],
      "subzones": [
        {
          "title": "사림과 붕당의 형성",
          "source_communities": [24, 25],
          "entity_ids": [2, 9, 10, 20, 22, 23, 31, 32, 59, 70, 90, 93, 95, 105, 113, 114, 115, 117, 118, 119, 120, 121, 122, 123, 125, 126, 127, 132, 134, 135]
        },
        {
          "title": "탕평과 정치 개혁",
          "source_communities": [12, 27, 9],
          "entity_ids": [212, 213, 214, 221, 222, 223, 225, 226, 228, 229, 230, 231, 232, 233, 234, 235, 236, 237, 238, 239, 240, 241, 242, 243, 244, 147, 148, 149, 174, 175, 176, 177, 179, 182, 186, 193, 194, 195, 196, 197, 198]
        }
      ],
      "entities": [
        {
          "entity_id": 127,
          "title": "사림",
          "visibility": "core",
          "reason": "붕당 정치의 출발점이 되는 핵심 세력이다."
        },
        {
          "entity_id": 22,
          "title": "성리학",
          "visibility": "supporting",
          "reason": "사림의 이념적 기반으로서 반드시 설명이 필요하다."
        },
        {
          "entity_id": 123,
          "title": "서원",
          "visibility": "supporting",
          "reason": "사림의 학문·정치 기반을 보여주는 핵심 공간이다."
        },
        {
          "entity_id": 132,
          "title": "향약",
          "visibility": "supporting",
          "reason": "향촌 자치와 사림의 기반을 설명하는 중요한 보조 개념이다."
        },
        {
          "entity_id": 59,
          "title": "유향소",
          "visibility": "search_only",
          "reason": "사림의 지방 기반 사례이지만 서원·향약보다 비중이 낮다."
        },
        {
          "entity_id": 115,
          "title": "김종직",
          "visibility": "supporting",
          "reason": "사림 형성의 정신적 뿌리를 보여주는 대표 인물이다."
        },
        {
          "entity_id": 114,
          "title": "조광조",
          "visibility": "supporting",
          "reason": "사림 개혁 정치의 상징이지만 붕당 정치 전체에서는 보조 축이다."
        },
        {
          "entity_id": 113,
          "title": "사화",
          "visibility": "supporting",
          "reason": "사림이 정치적으로 성장하는 과정의 충격을 설명한다."
        },
        {
          "entity_id": 126,
          "title": "붕당 정치",
          "visibility": "core",
          "reason": "방의 중심 개념으로, 조선 후기 정치 구조를 직접 설명한다."
        },
        {
          "entity_id": 117,
          "title": "붕당",
          "visibility": "supporting",
          "reason": "붕당 정치의 구조를 이해시키는 기본 용어다."
        },
        {
          "entity_id": 118,
          "title": "동인",
          "visibility": "supporting",
          "reason": "붕당 분화의 대표 세력으로 클릭 가치가 높다."
        },
        {
          "entity_id": 119,
          "title": "서인",
          "visibility": "supporting",
          "reason": "동인과 함께 붕당 정치의 양축을 이루는 핵심 세력이다."
        },
        {
          "entity_id": 223,
          "title": "남인",
          "visibility": "search_only",
          "reason": "붕당 분화의 세부 축이지만 핵심 학습 흐름에서는 보조적이다."
        },
        {
          "entity_id": 224,
          "title": "북인",
          "visibility": "search_only",
          "reason": "광해군 국면과 연결되지만 붕당 방에서는 세부 분류로 충분하다."
        },
        {
          "entity_id": 225,
          "title": "예송",
          "visibility": "supporting",
          "reason": "붕당 갈등이 의례 논쟁으로 확장된 대표 사례다."
        },
        {
          "entity_id": 226,
          "title": "환국",
          "visibility": "supporting",
          "reason": "붕당 정치의 권력 교체 양상을 보여주는 핵심 사건이다."
        },
        {
          "entity_id": 120,
          "title": "이조 전랑",
          "visibility": "supporting",
          "reason": "인사권 갈등을 설명하는 중요한 제도라 학습 가치가 높다."
        },
        {
          "entity_id": 60,
          "title": "삼사",
          "visibility": "supporting",
          "reason": "붕당 정치의 견제 장치를 보여주는 핵심 기관이다."
        },
        {
          "entity_id": 49,
          "title": "사간원",
          "visibility": "search_only",
          "reason": "삼사의 구성 요소이지만 단독 노출은 과하다."
        },
        {
          "entity_id": 50,
          "title": "사헌부",
          "visibility": "search_only",
          "reason": "감찰 기관으로 의미는 있으나 붕당 방에서는 보조 이하가 적절하다."
        },
        {
          "entity_id": 51,
          "title": "홍문관",
          "visibility": "search_only",
          "reason": "삼사 구성 요소 중 하나로 검색용 보존이 충분하다."
        },
        {
          "entity_id": 228,
          "title": "비변사",
          "visibility": "supporting",
          "reason": "전쟁 이후 정치 권력의 이동을 보여주는 중요한 기관이다."
        },
        {
          "entity_id": 221,
          "title": "영조",
          "visibility": "core",
          "reason": "탕평책의 본격적 시행자로 방의 핵심 인물이다."
        },
        {
          "entity_id": 212,
          "title": "탕평책",
          "visibility": "core",
          "reason": "붕당 정치를 정리하는 방의 최종 핵심 개념이다."
        },
        {
          "entity_id": 222,
          "title": "정조",
          "visibility": "core",
          "reason": "탕평 개혁을 계승·확장한 핵심 인물이다."
        },
        {
          "entity_id": 214,
          "title": "규장각",
          "visibility": "supporting",
          "reason": "정조 개혁의 상징 기관으로 학습 가치가 높다."
        },
        {
          "entity_id": 232,
          "title": "장용영",
          "visibility": "supporting",
          "reason": "정조의 왕권 강화 수단으로 중요한 보조 개념이다."
        },
        {
          "entity_id": 233,
          "title": "화성",
          "visibility": "supporting",
          "reason": "정조 개혁의 공간적 상징으로 이해를 돕는다."
        },
        {
          "entity_id": 242,
          "title": "수원 화성",
          "visibility": "supporting",
          "reason": "화성과 같은 맥락이지만 구체 명칭으로 클릭 가치가 있다."
        },
        {
          "entity_id": 231,
          "title": "탕평비",
          "visibility": "supporting",
          "reason": "탕평책의 상징물로서 시각적 이해를 돕는다."
        },
        {
          "entity_id": 213,
          "title": "균역법",
          "visibility": "supporting",
          "reason": "영조 개혁의 대표 정책이라 탕평과 함께 보여줄 가치가 있다."
        },
        {
          "entity_id": 244,
          "title": "서얼과 노비 차별 완화",
          "visibility": "search_only",
          "reason": "사회 개혁의 세부 항목으로는 의미 있으나 핵심 축은 아니다."
        },
        {
          "entity_id": 237,
          "title": "대전통편",
          "visibility": "supporting",
          "reason": "정조의 법제 정비를 보여주는 대표 문물이다."
        },
        {
          "entity_id": 234,
          "title": "속대전",
          "visibility": "search_only",
          "reason": "법전 정비의 세부 사례로는 유용하지만 전면 노출은 과하다."
        },
        {
          "entity_id": 235,
          "title": "속오례의",
          "visibility": "search_only",
          "reason": "의례 정비의 세부 항목이라 검색용이 적절하다."
        },
        {
          "entity_id": 236,
          "title": "동국문헌비고",
          "visibility": "search_only",
          "reason": "백과사전적 문헌으로 의미는 있으나 방의 중심과는 거리가 있다."
        },
        {
          "entity_id": 238,
          "title": "동문휘고",
          "visibility": "search_only",
          "reason": "문예 부흥의 세부 문헌이라 보조 이하가 적절하다."
        },
        {
          "entity_id": 239,
          "title": "탁지지",
          "visibility": "search_only",
          "reason": "재정 관련 문헌으로는 의미 있으나 핵심 개념은 아니다."
        },
        {
          "entity_id": 240,
          "title": "규장전운",
          "visibility": "search_only",
          "reason": "문예 부흥의 주변 사례라 UI 전면 노출은 과하다."
        },
        {
          "entity_id": 243,
          "title": "지지대고개",
          "visibility": "search_only",
          "reason": "정조 행차의 일화성 지명으로 학습 핵심성이 낮다."
        },
        {
          "entity_id": 147,
          "title": "광해군",
          "visibility": "supporting",
          "reason": "붕당 정치와 외교 갈등의 연결점으로 중요하다."
        },
        {
          "entity_id": 182,
          "title": "인조반정",
          "visibility": "supporting",
          "reason": "붕당 정치가 권력 교체로 이어진 대표 사건이다."
        },
        {
          "entity_id": 148,
          "title": "중립 외교 정책",
          "visibility": "search_only",
          "reason": "정치 방에서는 외교 세부 개념으로 보조 이하가 적절하다."
        },
        {
          "entity_id": 174,
          "title": "후금",
          "visibility": "search_only",
          "reason": "외교 배경 설명용으로는 필요하지만 붕당 방의 중심은 아니다."
        },
        {
          "entity_id": 175,
          "title": "명나라",
          "visibility": "search_only",
          "reason": "외교 배경의 세부 요소로만 보존하면 충분하다."
        },
        {
          "entity_id": 176,
          "title": "허준",
          "visibility": "search_only",
          "reason": "동의보감은 문화사로는 중요하지만 이 방의 정치 흐름과는 약하다."
        },
        {
          "entity_id": 177,
          "title": "동의보감",
          "visibility": "search_only",
          "reason": "정치 방에서는 주변 사례라 검색용이 적절하다."
        },
        {
          "entity_id": 179,
          "title": "강홍립",
          "visibility": "search_only",
          "reason": "외교 수행 인물로는 의미 있으나 붕당 정치의 핵심은 아니다."
        },
        {
          "entity_id": 186,
          "title": "송시열",
          "visibility": "supporting",
          "reason": "노론과 북벌, 탕평의 연결을 보여주는 핵심 인물이다."
        },
        {
          "entity_id": 193,
          "title": "이이첨",
          "visibility": "search_only",
          "reason": "인조반정 배경 인물로는 의미 있으나 방의 중심성은 낮다."
        },
        {
          "entity_id": 194,
          "title": "정인홍",
          "visibility": "search_only",
          "reason": "정치 갈등의 세부 인물이라 검색용이 적절하다."
        },
        {
          "entity_id": 195,
          "title": "임해군",
          "visibility": "search_only",
          "reason": "정치 희생자 사례로는 의미 있으나 핵심 개념은 아니다."
        },
        {
          "entity_id": 196,
          "title": "영창대군",
          "visibility": "search_only",
          "reason": "희생자 맥락의 세부 항목이라 UI 전면 노출은 과하다."
        },
        {
          "entity_id": 197,
          "title": "김제남",
          "visibility": "search_only",
          "reason": "인조반정 희생자이지만 방의 중심 흐름과는 약하다."
        },
        {
          "entity_id": 198,
          "title": "능창군",
          "visibility": "search_only",
          "reason": "희생자 목록의 세부 사례로 검색용이 적절하다."
        }
      ],
      "risk_flags": [
        "사림-붕당-탕평이 한 방에 들어가므로 정치 용어가 많아질 수 있다.",
        "정조 개혁 문헌이 많아 보일 수 있어, 문헌류는 search_only로 엄격히 조절해야 한다."
      ]
    },
    {
      "room_no": 5,
      "title": "실학과 경제 개혁",
      "learning_flow": "실학의 문제의식에서 출발해 중농·중상·북학으로 갈라지고, 대동법·균역법·상공업·기술 개발로 이어지는 개혁 흐름을 익힌다.",
      "ui_design_reason": "실학은 후기 사회 변화를 설명하는 큰 축이므로 경제·제도 개혁과 함께 묶으면 학습자가 흐름을 쉽게 잡는다. 학파별 차이를 보여주기에도 가장 적합한 방이다.",
      "visible_communities": [11, 13, 15, 35],
      "background_communities": [
        {
          "community_id": 16,
          "reason": "김정호와 지도 제작은 실학의 응용이지만 지리 방으로 분리하는 편이 더 깔끔하다."
        },
        {
          "community_id": 18,
          "reason": "정상기와 동국지도는 지도 제작의 세부 축이라 실학 방에서는 배경으로 둔다."
        },
        {
          "community_id": 20,
          "reason": "동사강목은 역사학 실학의 중요한 사례지만 별도 역사 인식 방으로 보낼 수 있다."
        },
        {
          "community_id": 22,
          "reason": "발해고는 역사 인식의 세부 사례라 실학 방의 중심을 흐릴 수 있다."
        },
        {
          "community_id": 33,
          "reason": "택리지는 지리 실학의 대표작이지만 별도 지리 방으로 분리하는 편이 더 명확하다."
        }
      ],
      "source_communities": [11, 13, 15, 35, 16, 18, 20, 22, 33],
      "subzones": [
        {
          "title": "실학의 문제의식",
          "source_communities": [11],
          "entity_ids": [245, 246, 247, 248, 251, 252, 278, 283, 284, 285]
        },
        {
          "title": "농업과 세제 개혁",
          "source_communities": [15, 35],
          "entity_ids": [253, 254, 255, 257, 258, 259, 286]
        },
        {
          "title": "상공업과 청 문물 수용",
          "source_communities": [13],
          "entity_ids": [256, 260, 261, 262, 263, 264, 265, 266, 267, 287]
        }
      ],
      "entities": [
        {
          "entity_id": 245,
          "title": "실학",
          "visibility": "core",
          "reason": "방 전체를 관통하는 중심 개념이다."
        },
        {
          "entity_id": 246,
          "title": "고증학",
          "visibility": "supporting",
          "reason": "실학의 학문적 방법을 설명하는 핵심 배경이다."
        },
        {
          "entity_id": 278,
          "title": "실사구시",
          "visibility": "supporting",
          "reason": "실학의 태도를 압축해 보여주는 중요한 개념이다."
        },
        {
          "entity_id": 247,
          "title": "노론 장기 집권",
          "visibility": "supporting",
          "reason": "실학이 등장한 사회적 배경을 설명한다."
        },
        {
          "entity_id": 251,
          "title": "실학자",
          "visibility": "supporting",
          "reason": "실학을 대표하는 인물군으로 학습 연결성이 높다."
        },
        {
          "entity_id": 252,
          "title": "이수광",
          "visibility": "supporting",
          "reason": "실학의 선구자로서 흐름의 시작점을 보여준다."
        },
        {
          "entity_id": 283,
          "title": "이제마",
          "visibility": "supporting",
          "reason": "실학의 확장된 응용 사례로 의학 발전을 보여준다."
        },
        {
          "entity_id": 284,
          "title": "중농 학파",
          "visibility": "core",
          "reason": "실학의 핵심 분파 중 하나로 독립 노출 가치가 높다."
        },
        {
          "entity_id": 255,
          "title": "중농학파",
          "visibility": "core",
          "reason": "중농 개혁의 대표 축으로 방의 핵심이다."
        },
        {
          "entity_id": 257,
          "title": "유형원",
          "visibility": "supporting",
          "reason": "중농학파의 대표 인물로 개혁안을 구체화한다."
        },
        {
          "entity_id": 258,
          "title": "이익",
          "visibility": "supporting",
          "reason": "토지 제도 개혁의 중요한 사례를 제공한다."
        },
        {
          "entity_id": 259,
          "title": "정약용",
          "visibility": "supporting",
          "reason": "중농학파의 완성형 인물로 학습 가치가 높다."
        },
        {
          "entity_id": 286,
          "title": "반계수록",
          "visibility": "supporting",
          "reason": "중농 개혁안을 집약한 대표 저술이라 보조로 적절하다."
        },
        {
          "entity_id": 253,
          "title": "김육",
          "visibility": "supporting",
          "reason": "대동법 개혁의 실천 인물로 중요하다."
        },
        {
          "entity_id": 254,
          "title": "대동법",
          "visibility": "core",
          "reason": "세제 개혁의 대표 정책으로 방의 핵심이다."
        },
        {
          "entity_id": 256,
          "title": "중상학파",
          "visibility": "core",
          "reason": "상공업 개혁과 청 문물 수용을 이끄는 핵심 분파다."
        },
        {
          "entity_id": 260,
          "title": "유수원",
          "visibility": "supporting",
          "reason": "중상학파의 대표 인물로 개혁 방향을 구체화한다."
        },
        {
          "entity_id": 261,
          "title": "홍대용",
          "visibility": "supporting",
          "reason": "과학·실용 지식과 청 문물 수용을 연결하는 핵심 인물이다."
        },
        {
          "entity_id": 262,
          "title": "박지원",
          "visibility": "core",
          "reason": "북학파와 실학 문학을 대표하는 핵심 인물이다."
        },
        {
          "entity_id": 263,
          "title": "박제가",
          "visibility": "supporting",
          "reason": "상공업 진흥과 청 문물 수용을 대표하는 중요한 인물이다."
        },
        {
          "entity_id": 264,
          "title": "북학파",
          "visibility": "core",
          "reason": "중상학파 내부의 중요한 흐름으로 독립적으로 보여줄 가치가 있다."
        },
        {
          "entity_id": 265,
          "title": "기술 개발",
          "visibility": "supporting",
          "reason": "상공업 발전의 실천 방향을 설명하는 핵심 보조 개념이다."
        },
        {
          "entity_id": 266,
          "title": "수레와 배",
          "visibility": "search_only",
          "reason": "교통 수단의 예시로는 의미 있으나 핵심 개념은 아니다."
        },
        {
          "entity_id": 267,
          "title": "연암집",
          "visibility": "supporting",
          "reason": "박지원의 실학 사상을 보여주는 대표 저술이다."
        },
        {
          "entity_id": 287,
          "title": "열하일기",
          "visibility": "core",
          "reason": "북학파와 실학 비판 정신을 대표하는 핵심 저술이다."
        },
        {
          "entity_id": 248,
          "title": "대상인",
          "visibility": "search_only",
          "reason": "조선 후기 상업 변화의 결과물로는 의미 있으나 방의 핵심 축은 아니다."
        }
      ],
      "risk_flags": [
        "실학자와 학파, 저술이 많아 보일 수 있으므로 핵심 저술만 전면 노출해야 한다.",
        "중농·중상·북학이 겹치므로 하위구역 제목을 분명히 구분해야 한다."
      ]
    },
    {
      "room_no": 6,
      "title": "조선 후기 사회 변화와 지리·국어학",
      "learning_flow": "서민 문화와 여성 윤리, 농민 봉기, 교통·통신, 지도 제작, 역사 인식, 국어학으로 이어지며 조선 후기 생활 세계의 변화를 입체적으로 본다.",
      "ui_design_reason": "후기 사회문화는 주제가 넓지만 서로 ‘생활 변화’라는 공통축이 있어 하나의 확장형 방으로 묶기 좋다. 다만 핵심과 주변을 엄격히 나눠야 UI가 산만해지지 않는다.",
      "visible_communities": [6, 26, 28, 21, 3, 18, 20, 22, 31, 32, 33, 34, 19],
      "background_communities": [
        {
          "community_id": 7,
          "reason": "고려사·고려사절요는 역사 인식의 비교 배경으로만 보존한다."
        }
      ],
      "source_communities": [6, 26, 28, 21, 3, 18, 20, 22, 31, 32, 33, 34, 19, 7],
      "subzones": [
        {
          "title": "서민 문화와 윤리",
          "source_communities": [6, 26, 34],
          "entity_ids": [142, 143, 217, 218, 219, 220]
        },
        {
          "title": "교통·통신과 물류",
          "source_communities": [21, 3],
          "entity_ids": [62, 74, 75, 81, 82, 83, 84, 85, 86]
        },
        {
          "title": "지도·역사·국어학",
          "source_communities": [18, 20, 22, 31, 32, 33, 19, 7],
          "entity_ids": [91, 92, 104, 105, 268, 269, 270, 271, 272, 273, 274, 275, 276, 277, 279, 280, 281, 282]
        }
      ],
      "entities": [
        {
          "entity_id": 219,
          "title": "김홍도",
          "visibility": "supporting",
          "reason": "서민 문화의 대표 인물로 방의 첫 인상을 만든다."
        },
        {
          "entity_id": 220,
          "title": "계회",
          "visibility": "supporting",
          "reason": "서민·관원 문화의 사회적 관계망을 보여주는 보조 개념이다."
        },
        {
          "entity_id": 142,
          "title": "여성의 재혼 금지",
          "visibility": "supporting",
          "reason": "조선 후기 윤리 규범을 보여주는 핵심 사회 제도다."
        },
        {
          "entity_id": 143,
          "title": "삼종지의",
          "visibility": "supporting",
          "reason": "여성 윤리의 기본 원리로서 함께 보여줄 가치가 있다."
        },
        {
          "entity_id": 217,
          "title": "홍경래의 난",
          "visibility": "supporting",
          "reason": "사회 불만의 폭발을 보여주는 대표 봉기다."
        },
        {
          "entity_id": 218,
          "title": "임술 농민 봉기",
          "visibility": "supporting",
          "reason": "조선 후기 사회 변동의 또 다른 대표 사례다."
        },
        {
          "entity_id": 62,
          "title": "신문고",
          "visibility": "supporting",
          "reason": "민원과 사회 정의의 제도적 장치로 의미가 크다."
        },
        {
          "entity_id": 74,
          "title": "조운",
          "visibility": "supporting",
          "reason": "세곡 운송 체계를 이해시키는 핵심 물류 개념이다."
        },
        {
          "entity_id": 75,
          "title": "역원 제도",
          "visibility": "core",
          "reason": "교통·통신 체계의 중심 개념으로 직접 노출이 적절하다."
        },
        {
          "entity_id": 84,
          "title": "역",
          "visibility": "supporting",
          "reason": "역원 제도의 구성 요소로서 이해를 돕는다."
        },
        {
          "entity_id": 85,
          "title": "마패",
          "visibility": "supporting",
          "reason": "공무 이동의 상징으로 시각적 이해가 좋다."
        },
        {
          "entity_id": 86,
          "title": "원",
          "visibility": "supporting",
          "reason": "숙박 기능을 담당하는 구성 요소로 보조 가치가 있다."
        },
        {
          "entity_id": 81,
          "title": "강창",
          "visibility": "supporting",
          "reason": "조창 체계의 구성 요소로 물류 흐름을 보강한다."
        },
        {
          "entity_id": 82,
          "title": "해창",
          "visibility": "supporting",
          "reason": "조창 체계의 또 다른 구성 요소로 함께 보여줄 가치가 있다."
        },
        {
          "entity_id": 83,
          "title": "조창",
          "visibility": "core",
          "reason": "세곡 저장과 운송의 핵심 제도라 방의 중심 개념이다."
        },
        {
          "entity_id": 91,
          "title": "고려사",
          "visibility": "search_only",
          "reason": "역사 인식 비교용으로는 유용하지만 방의 중심은 아니다."
        },
        {
          "entity_id": 92,
          "title": "고려사절요",
          "visibility": "search_only",
          "reason": "고려사와 함께 묶이는 보조 문헌이라 전면 노출은 과하다."
        },
        {
          "entity_id": 104,
          "title": "한문학",
          "visibility": "supporting",
          "reason": "조선 후기 문학 전통의 배경으로 의미가 있다."
        },
        {
          "entity_id": 105,
          "title": "동문선",
          "visibility": "supporting",
          "reason": "한문학 전통을 보여주는 대표 문헌이라 보조로 적절하다."
        },
        {
          "entity_id": 268,
          "title": "안정복",
          "visibility": "supporting",
          "reason": "역사 인식 변화의 대표 인물로 중요하다."
        },
        {
          "entity_id": 270,
          "title": "동사강목",
          "visibility": "supporting",
          "reason": "민족 사관 형성의 핵심 저술이라 학습 가치가 높다."
        },
        {
          "entity_id": 269,
          "title": "유득공",
          "visibility": "supporting",
          "reason": "북방 민족론과 남북국 시대론을 보여주는 핵심 인물이다."
        },
        {
          "entity_id": 271,
          "title": "발해고",
          "visibility": "supporting",
          "reason": "발해를 한국사에 포함시키는 역사 인식의 핵심 저술이다."
        },
        {
          "entity_id": 272,
          "title": "이중환",
          "visibility": "supporting",
          "reason": "지리 실학의 대표 인물로 방의 지리 축을 이끈다."
        },
        {
          "entity_id": 275,
          "title": "택리지",
          "visibility": "supporting",
          "reason": "지리·풍속·경제를 함께 보여주는 대표 저술이다."
        },
        {
          "entity_id": 273,
          "title": "정상기",
          "visibility": "supporting",
          "reason": "지도 제작 기술 발전의 대표 인물이다."
        },
        {
          "entity_id": 276,
          "title": "동국지도",
          "visibility": "supporting",
          "reason": "조선 후기 지도 제작의 핵심 성과로 의미가 크다."
        },
        {
          "entity_id": 274,
          "title": "김정호",
          "visibility": "core",
          "reason": "대동여지도와 실용 지리학을 대표하는 핵심 인물이다."
        },
        {
          "entity_id": 277,
          "title": "대동여지도",
          "visibility": "core",
          "reason": "조선 후기 지리학의 상징적 성과라 전면 노출이 필요하다."
        },
        {
          "entity_id": 279,
          "title": "신경준",
          "visibility": "supporting",
          "reason": "국어학 발전의 대표 인물로 학습 연결성이 높다."
        },
        {
          "entity_id": 281,
          "title": "훈민정음운해",
          "visibility": "supporting",
          "reason": "훈민정음 연구의 핵심 저술이라 보조로 적절하다."
        },
        {
          "entity_id": 280,
          "title": "유희",
          "visibility": "supporting",
          "reason": "한글 연구의 대표 인물로 의미가 크다."
        },
        {
          "entity_id": 282,
          "title": "언문지",
          "visibility": "supporting",
          "reason": "한글 우수성 인식을 보여주는 핵심 저술이다."
        },
        {
          "entity_id": 20,
          "title": "이성계",
          "visibility": "search_only",
          "reason": "역사 인식 비교 맥락에서는 필요하지만 이 방의 중심은 아니다."
        },
        {
          "entity_id": 21,
          "title": "한양 천도",
          "visibility": "search_only",
          "reason": "도시사 배경으로는 의미 있으나 이 방에서는 주변 정보다."
        },
        {
          "entity_id": 33,
          "title": "국방 강화",
          "visibility": "search_only",
          "reason": "교통·사회 변화와 직접적 관련이 약해 검색용이 적절하다."
        },
        {
          "entity_id": 34,
          "title": "함경도 반란 진압",
          "visibility": "search_only",
          "reason": "조선 초기 사건으로, 후기 사회 변화 방에서는 주변적이다."
        },
        {
          "entity_id": 36,
          "title": "조선-명 친선 관계",
          "visibility": "search_only",
          "reason": "외교사 세부 항목이라 이 방의 중심성과는 거리가 있다."
        },
        {
          "entity_id": 37,
          "title": "압록강·두만강 유역 개발",
          "visibility": "search_only",
          "reason": "북방 개발의 세부 정책으로, 후기 사회문화 방에서는 보조 이하가 적절하다."
        },
        {
          "entity_id": 46,
          "title": "류큐·시암·자와 등 동남아 교역",
          "visibility": "search_only",
          "reason": "대외 교역의 세부 사례로는 의미 있으나 핵심 학습 요소는 아니다."
        },
        {
          "entity_id": 53,
          "title": "의금부",
          "visibility": "search_only",
          "reason": "사법 기관으로는 중요하지만 이 방의 중심 흐름과는 약하다."
        },
        {
          "entity_id": 63,
          "title": "8도",
          "visibility": "search_only",
          "reason": "행정 구역 개념으로는 유용하지만 방의 핵심은 아니다."
        },
        {
          "entity_id": 76,
          "title": "병마절도사",
          "visibility": "search_only",
          "reason": "군사 조직 세부 항목이라 검색용이 적절하다."
        },
        {
          "entity_id": 77,
          "title": "수군절도사",
          "visibility": "search_only",
          "reason": "군사 조직 세부 항목으로는 의미 있으나 핵심 개념은 아니다."
        },
        {
          "entity_id": 78,
          "title": "5위",
          "visibility": "search_only",
          "reason": "수도 방어 조직의 세부 항목이라 전면 노출은 과하다."
        },
        {
          "entity_id": 79,
          "title": "읍성",
          "visibility": "search_only",
          "reason": "성곽 일반 개념으로는 넓어져서 검색용이 적절하다."
        },
        {
          "entity_id": 80,
          "title": "잡색군",
          "visibility": "search_only",
          "reason": "예비군 성격의 세부 조직이라 핵심성이 낮다."
        },
        {
          "entity_id": 87,
          "title": "봉수 제도",
          "visibility": "search_only",
          "reason": "통신 체계의 보조 사례로는 의미 있으나 중심 개념은 아니다."
        },
        {
          "entity_id": 94,
          "title": "팔도지리지",
          "visibility": "search_only",
          "reason": "지리서의 세부 사례로 보존만 하면 충분하다."
        },
        {
          "entity_id": 95,
          "title": "국조오례의",
          "visibility": "search_only",
          "reason": "의례 정비의 세부 문헌이라 핵심성은 낮다."
        },
        {
          "entity_id": 96,
          "title": "삼강행실도",
          "visibility": "search_only",
          "reason": "도덕 교화 문헌으로는 의미 있으나 방의 중심은 아니다."
        },
        {
          "entity_id": 98,
          "title": "농사직설",
          "visibility": "search_only",
          "reason": "농업 기술의 세부 사례로는 유용하지만 핵심 축은 아니다."
        },
        {
          "entity_id": 99,
          "title": "금속활자",
          "visibility": "search_only",
          "reason": "인쇄술 발전의 일반 사례라 이 방에서는 주변 정보다."
        },
        {
          "entity_id": 101,
          "title": "해시계",
          "visibility": "search_only",
          "reason": "세종 과학 방과 중복되므로 여기서는 검색용이 적절하다."
        },
        {
          "entity_id": 103,
          "title": "인지의",
          "visibility": "search_only",
          "reason": "토지 측량 도구로는 의미 있으나 핵심 학습 요소는 아니다."
        },
        {
          "entity_id": 109,
          "title": "과거제",
          "visibility": "search_only",
          "reason": "교육·관료제의 배경 개념으로는 유용하지만 이 방의 중심은 아니다."
        },
        {
          "entity_id": 110,
          "title": "세종 대왕",
          "visibility": "search_only",
          "reason": "세종 방과 중복되므로 여기서는 검색용으로만 보존한다."
        },
        {
          "entity_id": 111,
          "title": "태종",
          "visibility": "search_only",
          "reason": "조선 초기 정치사 배경으로는 의미 있으나 후기 사회문화 방에서는 주변적이다."
        },
        {
          "entity_id": 124,
          "title": "농업 발달",
          "visibility": "search_only",
          "reason": "경제 변화의 일반 개념이라 구체성이 낮다."
        },
        {
          "entity_id": 129,
          "title": "개간 사업",
          "visibility": "search_only",
          "reason": "농업 확대의 세부 정책으로는 의미 있으나 핵심은 아니다."
        },
        {
          "entity_id": 130,
          "title": "모내기법",
          "visibility": "search_only",
          "reason": "농업 기술 사례로는 유용하지만 방의 중심성과는 약하다."
        },
        {
          "entity_id": 133,
          "title": "여씨 향약",
          "visibility": "search_only",
          "reason": "향약의 원형 사례로는 의미 있으나 핵심 개념은 아니다."
        },
        {
          "entity_id": 136,
          "title": "소수 서원",
          "visibility": "search_only",
          "reason": "서원의 대표 사례지만 서원 방에서 이미 충분히 설명된다."
        },
        {
          "entity_id": 137,
          "title": "소수 서원 현판",
          "visibility": "search_only",
          "reason": "상징물로는 의미 있으나 핵심 학습 요소는 아니다."
        },
        {
          "entity_id": 138,
          "title": "명륜당",
          "visibility": "search_only",
          "reason": "서원 내부 공간의 세부 요소라 전면 노출은 과하다."
        },
        {
          "entity_id": 140,
          "title": "오륜행실도",
          "visibility": "search_only",
          "reason": "도덕 교화 문헌으로는 의미 있으나 방의 중심은 아니다."
        },
        {
          "entity_id": 141,
          "title": "가묘",
          "visibility": "search_only",
          "reason": "효 사상의 세부 제도라 보조 이하가 적절하다."
        },
        {
          "entity_id": 169,
          "title": "사고(조선의 사고)",
          "visibility": "search_only",
          "reason": "기록 보관 기관으로는 의미 있으나 핵심 학습 요소는 아니다."
        },
        {
          "entity_id": 178,
          "title": "명",
          "visibility": "search_only",
          "reason": "외교 배경의 세부 요소로만 보존하면 충분하다."
        },
        {
          "entity_id": 180,
          "title": "영창 대군",
          "visibility": "search_only",
          "reason": "정치 희생자 세부 항목이라 핵심성이 낮다."
        },
        {
          "entity_id": 181,
          "title": "인목 대비",
          "visibility": "search_only",
          "reason": "광해군 시기 희생자 맥락의 세부 항목이다."
        },
        {
          "entity_id": 204,
          "title": "김질",
          "visibility": "search_only",
          "reason": "조선 초기 사건의 세부 인물이라 이 방에서는 주변적이다."
        },
        {
          "entity_id": 205,
          "title": "이개",
          "visibility": "search_only",
          "reason": "조선 초기 정치 사건의 세부 인물로 검색용이 적절하다."
        },
        {
          "entity_id": 206,
          "title": "하위지",
          "visibility": "search_only",
          "reason": "조선 초기 정치 사건의 세부 인물로 핵심성은 낮다."
        },
        {
          "entity_id": 207,
          "title": "유응부",
          "visibility": "search_only",
          "reason": "조선 초기 정치 사건의 세부 인물이라 전면 노출은 과하다."
        },
        {
          "entity_id": 211,
          "title": "화성 화서문",
          "visibility": "search_only",
          "reason": "화성의 세부 문으로, 핵심 개념보다 하위 정보다."
        },
        {
          "entity_id": 227,
          "title": "옥산 서원",
          "visibility": "search_only",
          "reason": "서원의 지역 사례로는 의미 있으나 중심성은 낮다."
        },
        {
          "entity_id": 249,
          "title": "부농",
          "visibility": "search_only",
          "reason": "사회 변화의 결과 계층으로는 의미 있으나 핵심 개념은 아니다."
        },
        {
          "entity_id": 250,
          "title": "영세 상인",
          "visibility": "search_only",
          "reason": "사회 모순의 결과 사례로는 유용하지만 중심성은 낮다."
        }
      ],
      "risk_flags": [
        "주제가 매우 넓어 보일 수 있으므로 서민 문화, 교통·물류, 지리·국어학으로 하위구역을 강하게 분리해야 한다.",
        "지도·역사·국어학이 한 방에 모여 있어 문헌류는 search_only를 엄격히 적용해야 한다."
      ]
    }
  ],
  "backend_only_communities": [
    {
      "community_id": 7,
      "assigned_room_no": 6,
      "reason": "고려사·고려사절요는 역사 인식 비교용 근거로만 보존하고, UI에서는 후기 사회·지리·국어학 방의 보조 자료로 처리한다."
    },
    {
      "community_id": 10,
      "assigned_room_no": 1,
      "reason": "세조의 직전법은 왕권 강화의 연장선 근거로만 보존하고, 방 제목을 흐리지 않도록 배경 처리한다."
    },
    {
      "community_id": 16,
      "assigned_room_no": 5,
      "reason": "김정호와 대동여지도는 실학의 응용이지만 지리학 방으로 분리하는 편이 더 명확해 배경으로 둔다."
    },
    {
      "community_id": 17,
      "assigned_room_no": 1,
      "reason": "계유정난과 세조 집권은 조선 초기 권력 재편의 배경 근거로만 보존한다."
    },
    {
      "community_id": 18,
      "assigned_room_no": 5,
      "reason": "정상기와 동국지도는 지도 제작의 세부 축이라 실학 방에서는 배경으로 처리한다."
    },
    {
      "community_id": 20,
      "assigned_room_no": 5,
      "reason": "동사강목은 역사 인식 실학의 중요한 사례지만 별도 역사 인식 방으로 분리하지 않고 배경으로 둔다."
    },
    {
      "community_id": 22,
      "assigned_room_no": 5,
      "reason": "발해고는 역사 인식의 세부 사례라 실학 방의 중심을 흐릴 수 있어 배경으로 보존한다."
    },
    {
      "community_id": 30,
      "assigned_room_no": 2,
      "reason": "세종의 해상 방어는 세종 방의 확장 근거로만 보존하고, 임진왜란·병자호란 방과 중복되지 않게 배경 처리한다."
    },
    {
      "community_id": 33,
      "assigned_room_no": 5,
      "reason": "택리지는 지리 실학의 대표작이지만 별도 지리 방으로 분리하지 않고 실학 방의 배경으로 둔다."
    }
  ],
  "ambiguous_items_for_user_review": [
    {
      "item_type": "community",
      "id": 9,
      "current_room_no": 3,
      "reason": "광해군·인조반정은 전쟁사와 정치사 사이에 걸쳐 있어 전쟁 방과 정치 방 중 어디에 더 강하게 둘지 검토가 필요하다."
    },
    {
      "item_type": "community",
      "id": 10,
      "current_room_no": 1,
      "reason": "세조의 직전법은 왕권 강화와 재정 개혁 사이에 걸쳐 있어 건국 방의 보조로 둘지 별도 중기 정치 방으로 둘지 애매하다."
    },
    {
      "item_type": "entity",
      "id": 224,
      "current_room_no": 4,
      "reason": "북인은 붕당 정치와 인조반정 모두에 걸쳐 있어 정치 방에서는 search_only로 둘지 supporting으로 둘지 경계가 애매하다."
    },
    {
      "item_type": "entity",
      "id": 248,
      "current_room_no": 5,
      "reason": "대상인은 실학의 경제 변화와 후기 사회 변화 모두에 연결되어 있어 어느 방에서 더 강조할지 검토가 필요하다."
    }
  ],
  "self_check": {
    "all_communities_covered": true,
    "duplicate_community_ids": [],
    "missing_community_ids": [],
    "notes": "원본 community_id 0~36을 정확히 한 번씩 배치했다. 핵심 방은 6개로 유지했고, 작은 주제는 background/search_only로 내려 UI 밀도를 조절했다. 방 제목과 visible_communities는 직접 대응하도록 정리했다."
  }
}