# _with_images 정본 스키마 + 3D 락 판정 (정찰 산출물)

날짜: 2026-06-15
범위: 3D가 실제로 읽는 `_with_images.palace.json` 의 정본 스키마 문서화 + 향후 백엔드 작업
(작은/빈 방 합치기, 노드-이미지 일반화)이 그 스키마의 "필드"를 바꾸는지 판정.
정찰만. 코드 변경 0, 커밋 0, push 0.

근거는 전부 코드 인용 + 실파일 1부 실측으로 그라운딩. 추측은 명시.

검증 실파일: `palace/handoff/korean_history_with_images.palace.json` (schema_version 1.1,
6 rooms, 86 relationships, 24 attached nodes / 24 figs / 10 unplaced).

기존 정본 문서 `docs/palace_schema_contract.md` 와 대조해 실파일과 일치함을 확인했다.
이 문서는 그 계약서를 3D팀 관점(소비용 with_images)에서 재정리 + 락 판정을 추가한 것.

---

## 0. 먼저: "3D가 읽는 파일"이 둘로 갈린다 (중요)

| 경로 | 3D에 가는 파일 | images[] 있나 |
|---|---|---|
| 핸드오프(현재 3D 작업분) | `palace/handoff/{name}_with_images.palace.json` | 있음 |
| orchestrator 라이브(`GET /palace/{job}`) | `var/jobs/<id>/palace_out/{run_id}.palace.json` (= export 정본) | **없음** |

- `_with_images` 는 독립 스크립트 `palace/match_images.py --write-palace` 가 export 정본을 읽어
  매칭 노드에 `images[]` 를 박아 새로 쓴 파일이다 (`write_palace_copy`, match_images.py:307-392).
- orchestrator 파이프라인(app.py:135-138, stages.py:298-305)은 **현재 이미지 매칭을 안 거친다.**
  `build_palace` 가 낸 images 없는 export 정본을 그대로 서빙한다.
- 즉 "이미지 달린 3D 데이터"는 지금은 핸드오프 산출물뿐이고, 라이브 파이프라인엔 매칭 단계가
  아직 안 배선됐다. 3D 스키마 락은 **with_images 산출물 기준으로** 잡아야 한다(가장 넓은 형태).
- 스키마 관점: `_with_images` = export 정본 + `images[]`(노드) + `image_matching`(최상위) 두 가지만
  더해진 상위집합이다. 나머지 필드는 export와 1:1 동일.

---

## [A] `_with_images` 정본 스키마 (3D팀 들고 갈 것)

### A.1 최상위 (document root)

| 필드 | 타입 | 의미 | 예시 | 출처 |
|---|---|---|---|---|
| `schema_version` | str | 스키마 버전 락 | `"1.1"` | export_palace.py:273 |
| `schema_changelog` | str | 직전 버전 대비 변경 한 줄 | (1.0->1.1 설명) | export_palace.py:274-278 |
| `palace` | object | 궁전 메타. A.2 | | export_palace.py:279-298 |
| `rooms` | array | 방 배열. A.3 | | export_palace.py:299 |
| `relationships` | array | 방 내부 간선(최상위). A.6 | len 86 | export_palace.py:309 |
| `image_matching` | object | 매칭 실행 메타. A.7. **with_images 전용** | | match_images.py:358-372 |

실측 top keys: `['schema_version','schema_changelog','palace','rooms','relationships','image_matching']`.

### A.2 `palace` (궁전 메타)

키: `id`, `title`, `source`, `room_count`, `generated_at`, `pipeline`.

| 필드 | 타입 | 예시 |
|---|---|---|
| `palace.id` | str | run_id |
| `palace.title` | str | `"기억의 궁전: {run_id}"` |
| `palace.source.corpus` | str | 도메인 라벨(자유문) |
| `palace.source.language` | str | `"ko"` (하드코딩) |
| `palace.source.entity_count` | int | 스냅샷 엔티티 수 |
| `palace.room_count` | int | `len(rooms)` |
| `palace.generated_at` | str(ISO) | export 실행 UTC (유일한 비결정 값) |
| `palace.pipeline.snapshot` | str | 스냅샷 경로(repo 상대) |
| `palace.pipeline.k` | int | 목표 방 수 K |
| `palace.pipeline.merge` | str | `"toc"` |
| `palace.pipeline.embedding_model` | str | `"text-embedding-3-small"` |
| `palace.pipeline.llm_model` | str | Azure 배포명 |
| `palace.pipeline.node_budget` | int | 방당 keep 상한 |

### A.3 `rooms[*]` (방)

키: `id`, `index`, `name`, `summary`, `kept_count`, `meta`, `kept`, `demoted`.

| 필드 | 타입 | 의미 | 출처 |
|---|---|---|---|
| `id` | str | `"room_{NN}"` (absorb 후 0..N 재번호) | export_palace.py:260 |
| `index` | int | 출력 배열 0-기준 위치 | export_palace.py:261 |
| `name` | str | 방 이름(LLM) | export_palace.py:262 |
| `summary` | str\|null | 방 코히런스 설명 또는 null | export_palace.py:263 |
| `kept_count` | int | `len(kept)` | export_palace.py:264 |
| `meta` | object | **`{coherence_flag}` 한 필드뿐** | export_palace.py:265-267 |
| `kept` | array | 채택 노드(A.4), source_offset 오름차순 | export_palace.py:253 |
| `demoted` | array | 강등 노드(A.5) | export_palace.py:254-257 |

실측 ROOM0.meta = `{"coherence_flag": "coherent"}`.

### A.4 `rooms[*].kept[*]` (채택 노드)

실측 키 순서: `id, title, type, sequence, source_offset, offset_confidence, summary,
description, related, images`.

| 필드 | 타입 | 의미 | 출처 |
|---|---|---|---|
| `id` | str | palace pid = `"ent_" + normalize_title` | export_palace.py:95-119 |
| `title` | str | 엔티티 원제 | entities.parquet.title |
| `type` | str | 엔티티 타입(GraphRAG) | entities.parquet.type |
| `sequence` | int | 방 내 등장순 1-기준 순번(중요도 아님) | export_palace.py:239 |
| `source_offset` | int | 코퍼스 문자(char) 오프셋 | compute_position, :71-92 |
| `offset_confidence` | str enum | `"fine"` \| `"fallback"` | compute_position |
| `summary` | str | description 첫 문장 절단(파생) | caption_of, :34-45 |
| `description` | str | 엔티티 설명(GraphRAG) | entities.parquet.description |
| `related` | array<str> | 같은 방 간선 공유 노드 pid 목록 | collect_intra_room_relationships |
| `images` | array | 매칭 도판(A.8). **매칭된 노드만**, match_images 주입 | match_images.py:334-341 |

`kept` 노드는 항상 sequence/source_offset/offset_confidence/related 보유. `images` 는 매칭된 노드만.

### A.5 `rooms[*].demoted[*]` (강등 노드)

실측 키: `id, title, type, summary, description, images`.
**sequence / source_offset / offset_confidence / related 없음** (build_entity_record with_rank=None).
`images` 는 매칭되면 kept/demoted 둘 다 붙을 수 있다(실파일에서 demoted에도 images 부착 확인).

### A.6 `relationships[*]` (방 내부 간선, 최상위)

실측 키: `source, target, weight, description`.

| 필드 | 타입 | 의미 |
|---|---|---|
| `source` | str | 출발 노드 pid |
| `target` | str | 도착 노드 pid |
| `weight` | float\|null | 가중치(NaN이면 null) |
| `description` | str | 간선 설명 |

양 끝점이 같은 방에 kept 된 간선만, parquet 행 순서대로(collect_intra_room_relationships :149-200).

### A.7 `image_matching` (최상위, with_images 전용)

실측 키: `ran_at, source_palace, threshold_local, threshold_cascade, name_match_bonus,
hub_penalty_max, page_window, min_name_len, embed_deployment, caption_rows, attached_nodes,
attached_figures, unplaced_figures` (match_images.py:358-372).
실측 값 예: `attached_nodes=24, attached_figures=24, unplaced_figures=10, caption_rows=34`.
`ran_at` 만 비결정. 임계/보너스는 match_images.py 상단 Tunables 상수.

### A.8 `images[*]` (노드 도판) ★3D 핵심

실측 키: `path, caption, score` (3개 고정). score 내림차순 정렬(match_images.py:329-330).

| 필드 | 타입 | 의미 | 출처 |
|---|---|---|---|
| `path` | str | **PNG repo 상대 경로**. 예 `input/korean_history/img/fig_5_3.png` | png_path.relative_to(REPO).as_posix() |
| `caption` | str | 도판 캡션 전문(임베딩에 쓴 full caption) | detect_joined_caption cap_full |
| `score` | float | `cos + name_bonus - hub_penalty`, 소수 3자리 | round(score, 3) |

소비 노트: `path` 는 repo 상대 경로 문자열만. 바이트는 안 든다. 도판 서빙은 3D측이 정적 루트
(repo 루트)에 이 상대경로를 붙여 직접 서빙. **page 는 의도적으로 노드 images[]에 안 넣음**
(match_images.py:316 spec 주석). 페이지 정보가 필요하면 unplaced 풀에만 있음(아래).

### A.9 곁다리 산출물 `{stem}_unplaced_figures.json` (갤러리 풀, 별 파일)

`_with_images` 와 같이 쓰이나 **palace 파일 안엔 없다.** 미배치 도판 목록.
각 항목: `{row, path, page, caption_title, caption, reason, best_score}` (reason ∈
`{collision, no_fit}`). match_images.py:343-356. 3D 갤러리(방에 안 붙은 그림 모음)용.

---

## [B] export `.palace.json` 정본과의 차이

코드(export_palace.py)가 내는 필드는 시스템 1.1 스키마와 일치한다(validate() :319-349가 강제).
`_with_images` 와의 차이는 **추가 두 가지뿐**:

1. 최상위 `image_matching` 객체 추가 (export엔 없음).
2. 매칭된 노드(kept/demoted)에 `images[]` 추가 (export엔 없음).

그 외 최상위/palace/rooms/kept/demoted/relationships 필드는 export == with_images 로 동일.
즉 `_with_images` 는 export 정본의 **순수 상위집합**이다. export가 안 내는 필드를 with_images가
빼지 않고, 두 필드만 더한다. (확인: 실파일 top keys = export 5종 + image_matching.)

---

## [C] ★작은/빈 방 합치기가 스키마를 바꾸나

### 현재 구현 (빈 방 흡수)
`build_rooms.py::absorb_empty_rooms` (:286-319): kept-empty 방을 비어있지 않은 이웃(다음 섹션
우선, 없으면 이전)으로 합친다. 동작:
- 빈 방의 `demoted` 를 대상 방 `demoted` 로 이동(extend).
- 대상 방 `_meta.absorbed_from` 에 provenance append: `{section_idx, section_name, demoted_count}`.
- 남은 방만 0..N 으로 `room_id` 재번호.

### ★판정: 현재 merge 는 3D(_with_images) 스키마 필드를 바꾸지 않는다 (값만)

근거: `absorbed_from` 는 room_gen 중간 스키마의 `_meta` 에만 쌓인다. export(:258-267)는
`_meta` 에서 `coherence_reason`(→ room.summary) **하나만** 꺼내 쓰고, 출력 `rooms[*].meta` 는
`{coherence_flag}` 만 박는다. **`absorbed_from` 은 export 단계에서 버려진다.** 따라서:
- 바뀌는 것 = **값뿐**: 방 수 감소, `room_id`/`index` 재번호, `demoted[]` 재분배,
  `kept_count`(흡수 방은 kept-empty라 보통 불변), `relationships`(방 경계 재계산).
- 추가/제거/리네임되는 **필드 0개**.

### 단, 결정해야 할 갈림길 (락 전에 정할 것)
1. **"작은 방"까지 확장 시**: 현재는 *빈* 방만 흡수. "작은(kept N개 이하) 방"을 합치면
   kept 가 있는 방을 합치게 되고, 그러면 kept 노드의 `sequence`/`source_offset` 재정렬, kept를
   대상 방으로 이동하는 로직이 필요. 그래도 이는 **값 재계산**이지 새 필드가 아니다 (kept 레코드
   필드는 그대로). 합치는 알고리즘만 바뀜.
2. **provenance 를 3D에 노출할지**: "이 방은 N개 섹션을 합친 것"을 3D가 표시하려면
   `absorbed_from`(또는 `merged_from`, `merged_section_count`)을 **export가 `rooms[*].meta` 로
   끌어올려야** 한다 = **신규 필드**. 데이터는 이미 upstream(`_meta.absorbed_from`)에 있으니
   "export에서 한 줄 노출"이면 됨. 노출 안 하면 필드 변화 0.

→ **결론**: merge 자체는 스키마 필드 무영향(값만). provenance 표시를 3D 요구사항으로 넣을지가
유일한 신규 필드 결정. 그 한 가지(예: `rooms[*].meta.merged_from` 추가 여부)만 락 전에 합의하면 됨.

---

## [D] ★노드-이미지 일반화가 스키마를 바꾸나

### 대상 변경
1. 그림 매칭 일반화: 국사 전용(페이지 윈도잉, `fig_{p}_{i}.png` 페어링, `_surface_variants`
   한글 prefix 매칭) → 도메인 중립.
2. 캡션 생성: OCR/`extracted_figures.md` → GPT-4o 비전.

### ★판정: 노드-이미지 일반화도 `images[]` 필드를 바꾸지 않는다 (값/커버리지)

근거: `images[]` 의 형태는 `write_palace_copy`(:320-341)가 정하고 `{path, caption, score}` 3개로
**이미 도메인 중립**이다. 매칭 알고리즘(페이지 윈도우, 캐스케이드, name bonus, hub penalty)은
전부 **어떤 노드에 어떤 그림이 붙고 score가 얼마인가**(값)를 정할 뿐, 출력 필드를 안 만든다.
- 캡션 소스를 OCR→비전으로 바꿔도 `caption` 의 **값**이 바뀔 뿐 필드는 그대로.
- 도메인 중립화는 후보 선정/토크나이즈(match_images.py:158-185, "Swap this function per domain")만
  바꾼다. 출력 record 무관.
- page 는 지금도 노드 images[]에 안 들어감(spec). 일반화해도 동일.

국사가 이미 이 필드 모양으로 도는 게 확인됨(실파일 24노드). 다른 도메인 그림/비전 캡션도
같은 `{path, caption, score}` 에 그대로 담긴다 = **커버리지/값 향상**이지 필드 변경 아님.

### 단, 결정해야 할 갈림길 (락 전에 정할 것)
- **비전 캡션 provenance/메타**를 노드에 붙일지: 예 `caption_source`(`"ocr"`|`"vision"`),
  `alt_text`, `bbox`, `confidence` 등을 `images[*]` 에 넣고 싶으면 = **신규 필드**. 현재 스펙은
  안 넣음. 3D가 caption만 쓰면 추가 불필요.
- `image_matching`(최상위 메타)에 비전 모델명/캡션 모드 추가 가능성: 이건 메타 블록이라 3D
  렌더와 무관(값/진단용). 넣어도 노드 스키마엔 영향 없음.

→ **결론**: 노드-이미지 일반화는 노드/`images[]` 필드 무영향(값·커버리지만). 비전 캡션의
부가 메타(`caption_source` 등)를 노드 images[]에 노출할지가 유일한 신규 필드 결정.

---

## 락 권고

**지금 락해도 된다.** 단 아래 2개 "선택 필드"만 3D팀과 먼저 합의:

1. **merge provenance**: `rooms[*].meta` 에 `merged_from`/`merged_section_count` 류를 노출할지.
   (데이터는 이미 `_meta.absorbed_from` 에 있음. export 한 줄로 노출 가능. 안 하면 필드 0변화.)
2. **이미지 부가 메타**: `images[*]` 에 `caption_source`(ocr/vision) 등을 추가할지.
   (현재 `{path, caption, score}` 3필드. 비전 도입해도 caption은 값만 바뀜.)

이 둘 다 **선택적 추가 필드**다. 둘 다 "안 노출"로 합의하면 merge와 노드-이미지는 향후 작업이
스키마 필드를 0개 바꾸므로 **지금 1.1로 완전 락 가능**. 노출을 원하면 그 필드만 1.2 후보로
지금 합의해 스키마에 자리만 잡아두는 걸 권장(나중 추가도 상위집합이라 비파괴적이긴 함).

핵심: merge도 노드-이미지도 **기존 필드는 안 건드린다.** 위험은 "새 필드를 추가하느냐 마느냐"
한 축뿐이고, 그건 3D의 표시 요구(합친 방 표시?/캡션 출처 표시?)로만 결정된다.

---

## 안 건드림 (확인)
- 읽기만 수행. 코드 0, 커밋 0, push 0.
- frozen 미접근: `results/snapshots/repro_run3`, `palace/tests/golden`,
  `palace/configs/*toc_frozen*`, `proj_ai_school` 커밋 파일.
- `palace/handoff/korean_history_with_images.palace.json` 는 읽기만(구조 실측).
