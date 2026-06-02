---
type: spec
id: 05_exp5_data_contract
date: 2026-06-02
---

# 실험 5 데이터 계약서 (팀 공유용)

베이스: `results/snapshots/repro_run3/` (357 entities, level 0 = 40방)

## 0. 데이터 흐름 한눈에

```
[graphrag output]                [exp5 단계 1]              [exp5 단계 2]                [exp5 단계 3]
                                                                                      
entities.parquet         ┐                                                            
  (357 rows)             │                                                            
relationships.parquet    │                                                            
  (379 rows)             │   ┌──────────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐
communities.parquet      ├──▶│  build_room_payloads │──▶│  LLM 병합 (3회 호출) │──▶│   build_slot_json    │
  (73 rows, level 0=40)  │   │                      │   │     (또는)            │   │                      │
community_reports.parquet│   │   = 방 40개 payload   │   │  임베딩 병합 K∈      │   │  = 10 building       │
  (73 rows, level 0=40)  │   │                      │   │  {5,7,10,12,15}      │   │   + 각 안 N loci     │
lancedb/                 │   └──────────────────────┘   └──────────────────────┘   └──────────────────────┘
  community_full_content │           ▲                            ▲                          ▲
  entity_description     │           │                            │                          │
  (1536-dim, normalized) ┘   스키마 1 (입력 페이로드)      스키마 2 (병합 결과)          스키마 3 (3D 슬롯)
```

세 단계 모두 **scribbled in-memory dict → JSON**으로 흘러감. parquet은 단계 1에서만 읽고 그 이후엔 안 봄.

---

## 스키마 1 — LLM 병합 입력 페이로드

각 방 1개 = 1 dict. 40개 모임 = `List[RoomPayload]`.

### `RoomPayload` 필드

| 필드 | 타입 | 출처 (file.column) | 왜 필요한가 |
|---|---|---|---|
| `community` | int | `community_reports.community` (= `communities.community`로 join 키와 동일) | LLM 출력에서 어느 방을 가리키는지 식별 ID. 0~72 사이 정수 |
| `title` | str | `community_reports.title` | LLM이 의미 묶음 판단의 1차 단서 (압축 26자) |
| `summary` | str | `community_reports.summary` | title이 못 담는 뉘앙스. 의미 묶음의 ★ 핵심 (중간 268자) |
| `size` | int | `communities.size` (= `len(entity_ids)`) | 작은 방 흡수 판단의 단서. 슈퍼 방 size 분포 계산에도 사용 |
| `members` | List[str] | `entities.title` (`communities.entity_ids[i]`로 조회) | 도메인 고유명사. title이 추상적일 때 결정타 (예: 광해군·서인·동의보감) |

### `members` 선택 규칙

```python
all_members = entities.loc[communities.entity_ids].sort_values('degree', ascending=False)
top_members = all_members.head(10) if size > 10 else all_members
members = top_members['title'].tolist()
```

- 정렬 키: `entities.degree` (그래프 연결 수 = 중심성)
- size ≤ 10: 모든 멤버
- size > 10: degree 상위 10개

### 실제 예시 (`community=4`, size=12)

```json
{
  "community": 4,
  "title": "광해군 시대 조선 왕조 권력 네트워크",
  "summary": "본 보고서는 임진왜란 이후부터 병자호란에 이르기까지 광해군과 인조를 중심으로 조선 전기부터 후기에 걸친 주요 왕족, 관료, 외교 세력 간의 관계망을 분석한다. 광해군은 전후 국토 복구와 국방력 강화를 주도하며 동의보감 편찬과 후금과의 중립 외교 정책을 실행하였다. 서인 붕당은 광해군 말기에서 인조 즉위에 이르는 정치적 영향력을 보였으며, 인조는 서인의 지지를 바탕으로 후금을 적대시하고 청과의 병자호란을 맞이한다. ...",
  "size": 12,
  "members": ["광해군", "서인", "청", "동의보감", "러시아", "허준", "병자호란", "후금", "인조", "강홍립"]
}
```

(원래 멤버 12개 중 degree 상위 10개. size>10이라 강홍립까지. 남한산성·영창 대군 deg=1은 제외)

### LLM 호출 시 변환 (JSON → 자연어 텍스트)

```
방 4 (size=12): 광해군 시대 조선 왕조 권력 네트워크
요약: 본 보고서는 임진왜란 이후부터 병자호란에 이르기까지 광해군과 인조를...
멤버: 광해군, 서인, 청, 동의보감, 러시아, 허준, 병자호란, 후금, 인조, 강홍립
---
```

40개 방을 `---`로 구분. 입력 토큰 ~11K.

---

## 스키마 2 — 병합 결과

LLM과 임베딩 두 경로의 출력을 **공통 형태로 통일**해서 단계 3가 어느 쪽이든 받을 수 있게.

### `MergeResult` 통일 스키마

| 필드 | 타입 | 누가 채우나 | 왜 필요한가 |
|---|---|---|---|
| `method` | str | "llm" / "embed_K10" 등 | 어느 경로의 결과인지 (비교용) |
| `run` | int | 1~3 (LLM 재현성용), 임베딩은 항상 1 | 같은 method의 회차 |
| `K` | int | 결과 그룹 수 (LLM=10 강제, 임베딩=K_target) | 검증·비교용 |
| `merged_rooms` | List[MergedRoom] | 핵심 출력 | 각 슈퍼 방 정의 |

### `MergedRoom` 필드

| 필드 | 타입 | LLM 출력 | 임베딩 출력 | 왜 필요한가 |
|---|---|---|---|---|
| `new_id` | int (0~K-1) | LLM이 매김 | scipy fcluster label - 1 | 슈퍼 방 식별자 |
| `new_title` | str \| null | LLM이 생성 (20자 이내) | **null** (임베딩은 의미 추론 못 함) | 단계 3에서 building.name으로 사용 |
| `members` | List[int] | LLM이 매김 (community 번호) | label==new_id+1인 community 번호 list | 단계 3에서 entity_ids 펼침 |
| `silhouette` | float \| null | null | sklearn silhouette_score (전체 K에 대한 1개 값) | 임베딩 품질 metric |

**임베딩 결과의 `new_title` 처리**: null로 두고, 단계 3에서 멤버 방 중 size 최대인 방의 `community_reports.title`을 빌려 옴 (가장 큰 묶음의 이름을 대표로).

### 실제 예시 — LLM 결과 (10그룹 중 1개)

```json
{
  "new_id": 3,
  "new_title": "임진왜란과 광해군 외교",
  "members": [4, 14, 23, 29],
  "silhouette": null
}
```

→ community 4("광해군 권력"), 14("임진왜란"), 23("광해군 후기"), 29("외교") 4방 합쳐 슈퍼 방 1개.

### 실제 예시 — 임베딩 결과 (같은 그룹)

```json
{
  "new_id": 3,
  "new_title": null,
  "members": [4, 14, 23],
  "silhouette": 0.187
}
```

→ 같은 K=10에서 임베딩이 묶는 방. members는 다를 수 있음 (비교 메트릭의 핵심).

### 검증 규약 (둘 다 통과해야 함)

```python
def validate(result):
    assigned = [c for grp in result['merged_rooms'] for c in grp['members']]
    assert set(assigned) == set(input_communities), "방 누락/추가"
    assert len(assigned) == len(set(assigned)), "방 중복 배정"
    assert len(result['merged_rooms']) == result['K'], "K 불일치"
```

---

## 스키마 3 — 최종 3D 슬롯 JSON (3D팀이 받을 것) ⭐

### 전체 구조

```
SlotPackage
├── version: "1.0"
├── source: { snapshot, method, ... }
├── generated_at: ISO timestamp
└── buildings: List[Building]
    └── Building
        ├── id, name, summary, size, source_rooms
        └── loci: List[Locus]
            └── Locus
                ├── order, concept, desc
                └── (메타: entity_id, type, degree)
```

### `SlotPackage` (최상위) 필드

| 필드 | 타입 | 출처 | 왜 필요한가 |
|---|---|---|---|
| `version` | str | 고정 "1.0" | 3D팀이 스키마 버전 관리 |
| `source.snapshot` | str | "repro_run3" 등 | 어느 베이스에서 만들어졌는지 |
| `source.method` | str | "llm_run1" / "embed_K10" 등 | 어느 병합 방법 결과인지 |
| `source.entities_total` | int | `len(entities.parquet)` | 검증용 (loci 총합 == 이 값?) |
| `generated_at` | str (ISO) | datetime.now() | 캐시·디버깅 |
| `buildings` | List[Building] | 단계 3에서 빌드 | 본체 |

### `Building` 필드

| 필드 | 타입 | 출처 | 왜 필요한가 |
|---|---|---|---|
| `id` | int (0~9) | MergedRoom.new_id | 3D 씬에서 건물 식별 |
| `name` | str | LLM: MergedRoom.new_title / 임베딩: 멤버 방 중 size 최대인 방의 `community_reports.title` | 건물 라벨. UX에 표시 |
| `summary` | str | ⚠️ **결정 필요** (옵션 ↓) | 건물 안내문. UX에 표시 |
| `size` | int | `sum(len(communities.entity_ids[c]) for c in source_rooms)` | 건물 크기 (loci 수와 같음). UX에서 크기 시각화에 사용 |
| `source_rooms` | List[int] | MergedRoom.members | 추적성 — 원래 어느 level 0 방들이 합쳐졌는지 |
| `loci` | List[Locus] | 아래 규칙으로 빌드 | 건물 안 entity 목록 |

### `Locus` 필드 (entity 1개 = 1 locus)

| 필드 | 타입 | 출처 | 왜 필요한가 |
|---|---|---|---|
| `order` | int (1~N) | ⚠️ **결정 필요** (옵션 ↓) | 동선 순서 |
| `concept` | str | `entities.title` | 3D에서 표시할 개념 이름 ("측우기", "광해군") |
| `desc` | str | `entities.description` | 3D 슬롯의 핵심 텍스트. 16~329자 (중간 49자) → 3D 단서로 적당 |
| `entity_id` | str (UUID) | `entities.id` | 추적성 + 3D팀이 디버깅 시 원본 조회 |
| `type` | str | `entities.type` | UX 색상 분류용 ("인물, 군주" / "사건, 전쟁" 등) |
| `degree` | int | `entities.degree` | UX 크기/강조 (중심성 큰 entity는 강조) |

### 실제 예시 (community=4 베이스의 "광해군 시대" 건물 단독)

```json
{
  "id": 3,
  "name": "광해군 시대 조선 왕조 권력 네트워크",
  "summary": "본 보고서는 임진왜란 이후부터 병자호란에 이르기까지 광해군과 인조를 중심으로...",
  "size": 12,
  "source_rooms": [4],
  "loci": [
    {
      "order": 1,
      "concept": "광해군",
      "desc": "광해군은 임진왜란 이후 조선의 국왕으로 즉위하여 전후 복구를 주도하고 국방력 강화를 위해 노력한 왕이다. 그는 국가 재정 확충과 안보 강화를 위해 토지대장과 호적을 새로 편성하였으며, 성곽과 무기를 보수하는 등 실질...",
      "entity_id": "27eab09b-...",
      "type": "인물, 군주",
      "degree": 8
    },
    {
      "order": 2,
      "concept": "서인",
      "desc": "붕당 중 하나로 기성 관료 중심의 정치 세력이며, 심의겸이 중심 인물 중 하나임",
      "entity_id": "83aff83d-...",
      "type": "사회집단",
      "degree": 5
    },
    {
      "order": 3,
      "concept": "청",
      "desc": "후금이 국호를 바꾼 강성한 국가로, 조선을 압박하며 군대를 동원해 병자호란을 일으켜 조선에 굴욕적인 삼전도 강화 요구함",
      "entity_id": "06fc4483-...",
      "type": "국가, 국제세력",
      "degree": 3
    }
    // ... 나머지 9개 (남한산성·영창 대군 포함, degree=1까지 다 들어감)
  ]
}
```

(실제 슈퍼 건물은 source_rooms이 4~5개 합쳐져 loci 30~50개가 되겠지만, 한 방만 예시)

### 보장 (3D팀과의 계약)

- **모든 entity가 정확히 한 building.loci에 등장** (개념 보존). `sum(len(b.loci) for b in buildings) == entities_total`로 검증.
- **loci는 entity 1개 = 1 row** (멤버 중복 없음).
- 모든 필드 non-null. desc가 빈 경우는 graphrag 단계에서 이미 발생 안 하지만 안전망으로 `desc or ""` 처리.

---

## ⚠️ 결정 필요한 부분 (3D팀과 합의)

### A) `Building.summary` 어떻게 채울까

| 옵션 | 결과 | 비용 | 추천 |
|---|---|---|---|
| **A1**: 멤버 방의 summary 이어붙이기 (`\n\n`으로) | 매우 정보 풍부, 1000~2000자 | 0 | UX가 긴 텍스트 OK라면 |
| **A2**: 멤버 방의 title을 list로 ("이 건물에는: 임진왜란 의병, 광해군 외교, ...") | 짧고 깔끔 (~100자) | 0 | ★ 추천 — 빠르고 충분 |
| **A3**: 합쳐진 멤버 방들을 LLM으로 한 줄 재요약 | 자연스러운 안내문 (~200자) | +$0.05 추가 호출 | 시연 품질 우선이면 |
| **A4**: 비워둠 ("") | UX에 안내문 없음 | 0 | 비추천 |

### B) `Locus.order` (동선) 어떻게 정할까

| 옵션 | 결과 | 비고 |
|---|---|---|
| **B1**: `degree` 내림차순 | 중심 인물·개념 먼저, 주변 entity 뒤 | ★ 추천 — 도메인 무관, 깔끔 |
| **B2**: 같은 building 내 entity끼리 그래프 거리 traversal (DFS) | 의미적 인접 entity가 연달아 | relationships.parquet 추가 처리 필요. 복잡 |
| **B3**: `frequency` 내림차순 | 자주 등장한 entity 먼저 | 텍스트 노출 빈도 기준 |
| **B4**: 임베딩 유사도로 가까운 것 연달아 (TSP-style) | 의미 흐름이 부드러움 | 추가 계산. 효과 검증 안 됨 |
| **B5**: 임의 (`entity_ids` 원래 순서) | 의미 없음 (확인: 광해군 방에서 강홍립·광해군·동의보감 섞여 있음) | 비추천 |

### C) `Locus`에 relationship 노출할까

- 현재 안: entity만 노출 (concept/desc). 그래프 관계는 안 보여줌.
- 옵션: 각 locus에 "관련된 다른 locus"를 추가 필드 (예: `connected_to: [order=3, order=5]`)로. 3D에서 선으로 시각화 가능.
- ⚠️ 결정 필요. 안 넣으면 3D는 점만, 넣으면 점+선 가능.

### D) 슈퍼 건물 size 폭증 처리

K=10이면 평균 building.size=36, 큰 건물은 50+ 가능. 3D 슬롯이 50개 이상 들어가면 시연 UX가 무너질 수 있음.

| 옵션 | 결과 |
|---|---|
| **D1**: 그대로 (모든 entity 노출) | 보존 100%, UX 부담 |
| **D2**: 큰 building 안에서 degree 상위 N개만 노출, 나머지는 별도 필드 `dim_loci`로 | UX 깔끔, 정보 일부 숨김 |
| **D3**: K를 자동 조절 (silhouette/자연 cut 기준) → building 평균 size를 20 안쪽으로 | "정확히 10개" 포기 |

---

## 결정 받을 게 4가지

| 항목 | 옵션 | 내 추천 |
|---|---|---|
| A) Building.summary | A1/A2/A3/A4 | **A2** (멤버 방 title list, 빠르고 충분) |
| B) Locus.order | B1/B2/B3/B4/B5 | **B1** (degree 내림차순, 도메인 무관) |
| C) relationship 노출 | yes/no | **no** (1.0에서는 점만, 추후 1.1에서 점+선) |
| D) size 폭증 처리 | D1/D2/D3 | **D1** (그대로 노출, UX는 3D팀이 판단) |

이 4개 결정해주면 단계 3 코드까지 완성된 계약서로 실험 5 들어갈게.
