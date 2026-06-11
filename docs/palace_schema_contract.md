# .palace.json 스키마 계약서 (schema_version 1.1)

각 필드의 의미, 타입, 출처(파일/함수), 안정/변동을 코드로 확정한 문서. 추측 없이 코드 인용으로 그라운딩했고,
코드에서 확정 안 되는 항목은 "코드상 불명"으로 표시한다. 경로는 repo 상대.

## 0. 누가 무엇을 쓰는가 (단일 파일이 아님)

최종 산출물은 **두 단계가 이어 붙인다**. 단일 파일에서 한 번에 조립되지 않는다.

1. `palace/export_palace.py::export()` 가 정본 스키마를 쓴다 (LLM 0회, 결정적).
   상위 호출은 `palace/run.py::phase_rooms()` 가 `export_palace.export(run_id, snapshot, rooms_dir)` 로 호출.
   입력은 `{rooms_dir}/{run_id}.json` (room_gen 공통 스키마) + 스냅샷 parquet 4종.
   출력은 `{rooms_dir}/{run_id}.palace.json`. 이 파일에는 `images[]` 가 **없다**.
2. `palace/match_images.py::write_palace_copy()` 가 `--write-palace` 일 때 1단계 산출물을 읽어
   매칭된 노드에 `images[]` 를 붙이고 최상위 `image_matching` 메타를 추가해
   `{stem}_with_images.palace.json` 으로 **새로 쓴다** (원본은 안 건드림).
   `{stem}_unplaced_figures.json` (갤러리 풀)도 같이 쓴다.

즉 `images[]` 와 `image_matching` 은 export 가 아니라 match_images 가 박는다. `schema_version`/`schema_changelog`
는 export 가 박는다(아래 변경). 회의용으로는 두 산출물을 구분해 둘 것: export 산출물 = 정본, with_images 산출물 = 소비용 확장본.

값의 더 위 기원까지 거슬러 올라가면:
- room_gen 공통 스키마(`{run_id}.json`)는 `palace/run.py::phase_rooms()` 가
  `build_rooms.convert_toc_to_common_schema()` 로 만들고 `absorb_empty_rooms()` 로 정리해 쓴다.
- 그 앞단: `build_toc_rooms`(방 배정) -> `attach_positions`(방 내 pos_first_fine 정렬) ->
  `apply_keep_demote`(Stage A 루브릭 + Stage B keep/demote, node_budget 상한).
- 노드의 `type`/`description`/`text_unit_ids` 의 진짜 출처는 스냅샷 `entities.parquet` (GraphRAG 인덱싱 출력).

---

## 1. 최상위 (document root)

| 필드 | 타입 | 의미 | 출처 (파일::함수) | 안정/변동 |
|---|---|---|---|---|
| `schema_version` | str | 스키마 버전 락. 현재 `"1.1"`. | `export_palace.py::export` (리터럴) | 계약값. 변경 시 changelog 갱신 |
| `schema_changelog` | str | 직전 버전 대비 변경 한 줄. | `export_palace.py::export` (리터럴) | 계약값 |
| `palace` | object | 궁전 메타. §2. | `export_palace.py::export` | 안정 |
| `rooms` | array | 방 배열. §3. | `export_palace.py::export` | 안정 |
| `relationships` | array | 방 내부 간선. §6. | `export_palace.py::export` (`collect_intra_room_relationships`) | 안정 |
| `image_matching` | object | 이미지 매칭 실행 메타. §7. **export 아님**, match_images 가 추가. | `match_images.py::write_palace_copy` | with_images 산출물에만 존재 |

주의: 1단계 export 산출물에는 `image_matching` 이 없다. `with_images` 산출물에만 있다.

---

## 2. `palace` (궁전 메타)

전부 `export_palace.py::export()` 의 `palace` dict 리터럴(약 268~290행)에서 조립. 값의 기원은 대부분
room_gen 공통 스키마 `meta`(= `convert_toc_to_common_schema` 가 만든 것).

| 필드 | 타입 | 의미 | 값의 기원 | 안정/변동 |
|---|---|---|---|---|
| `id` | str | 런 식별자. | `export()` 인자 `run_id` = config `run_id` | 안정 |
| `title` | str | `"기억의 궁전: {run_id}"` | `export` 리터럴 | 안정(서식) |
| `source.corpus` | str | 도메인 라벨(한국어 자유문). | `meta.domain` <- config `domain` (`convert_toc_to_common_schema`) | 변동(자유문) |
| `source.language` | str | `"ko"` 하드코딩. | `export` 리터럴 | 안정 |
| `source.entity_count` | int | 스냅샷 엔티티 수. | `meta.snapshot_meta.n_entities` (없으면 `len(entities.parquet)`로 폴백) | 안정 |
| `room_count` | int | 방 개수 = `len(rooms_out)`. | `export` 계산 | 안정 |
| `generated_at` | str(ISO) | export 실행 시각(UTC). | `datetime.now(timezone.utc)` | 변동(실행마다) |
| `pipeline.snapshot` | str | 스냅샷 경로(repo 상대). | `meta.snapshot` <- config `snapshot_rel` | 안정 |
| `pipeline.k` | int | 목표 방 수 K. | `meta.K` <- config `K` | 안정 |
| `pipeline.merge` | str | `"toc"` (TOC arm). | `meta.merge_strategy` (`convert_toc...` 리터럴 `'toc'`) | 안정 |
| `pipeline.embedding_model` | str | `"text-embedding-3-small"` 하드코딩. | `export` 리터럴 | 변동(계약: 모델 바뀔 수 있음) |
| `pipeline.llm_model` | str | Stage A/B/TOC 모델명. | `meta.model` <- config `model` (Azure 배포명) | 변동 |
| `pipeline.node_budget` | int | 방당 keep 상한. | `meta.node_budget` <- config `node_budget` | 안정 |

`generated_at` 만 비결정적. 나머지는 입력 고정 시 결정적.

---

## 3. `rooms[*]` (방)

`export_palace.py::export()` 232~266행에서 방마다 조립.

| 필드 | 타입 | 의미 | 값의 기원 | 안정/변동 |
|---|---|---|---|---|
| `id` | str | `"room_{room_id:02d}"`. | `room['room_id']` (absorb 후 0..N 재번호; `absorb_empty_rooms`) | 안정 |
| `index` | int | 출력 배열 내 0-기준 위치. | `enumerate(rooms_json['rooms'])` | 안정 |
| `name` | str | 방 이름(LLM Stage B 생성). | room_gen `room['name']` <- `_llm.room_name` (Stage B `assign_rooms` 출력) | 변동(LLM) |
| `summary` | str\|null | 방 코히런스 설명(LLM) 또는 null. | `room['_meta'].coherence_reason or None` <- `_llm.coherence_reason` | 변동(LLM) |
| `kept_count` | int | `len(kept)`. | `export` 계산 | 안정 |
| `meta.coherence_flag` | str | Stage B 코히런스 플래그(예: `coherent`). | `room['coherence_flag']` <- `_llm.coherence_flag` | 변동(LLM) |
| `kept` | array | 채택 노드. §4. `source_offset` 오름차순 정렬됨. | `export` (`kept_list.sort(key=source_offset)`) | 안정 |
| `demoted` | array | 강등 노드. §5. | `export` | 안정 |

`room_count <= 10` 보장은 K 설정과 absorb 결과에 의존(현재 K=6).

---

## 4. `rooms[*].kept[*]` (채택 노드)

`export_palace.py::build_entity_record()` (with_rank/order 지정) + 사후 `related` 주입.

| 필드 | 타입 | 의미 | 값의 기원 | 안정/변동 |
|---|---|---|---|---|
| `id` | str | palace id = `"ent_" + normalize_title(title)`. | `assign_palace_ids` / `normalize_title` | 안정 |
| `title` | str | 엔티티 원제. | `entities.parquet.title` (방 멤버십은 room_gen kept) | 안정 |
| `type` | str | 엔티티 타입(GraphRAG 추출). | `entities.parquet.type` (`build_ent_lookup`) | 안정 |
| `sequence` | int | **방 내 등장순 1-기준 순번. Stage B 중요도 아님.** (v1.0 `rank`) §8 확정. | `enumerate(room['kept'], start=1)` (정렬 전 입력 순서 = attach_positions의 pos_first_fine 순) | 안정 |
| `source_offset` | int | **등장 위치 = 코퍼스 문자 오프셋(char). 토큰 아님.** (v1.0 `order`) §8. | `compute_position` -> `_first_in_text(corpus_text, variants)` (= `str.find`) | 안정(결정적) |
| `offset_confidence` | str(enum) | `"fine"` 또는 `"fallback"`. (v1.0 `order_confidence`) §8. | `compute_position` 반환 | 안정(enum) |
| `summary` | str | **description 의 첫 문장(절단). 별도 생성 아님.** (v1.0 `caption`) §8. | `caption_of(info['description'])` | 안정(파생) |
| `description` | str | 엔티티 설명(GraphRAG 추출). | `entities.parquet.description` | 안정 |
| `related` | array<str> | 같은 방에서 간선 공유하는 다른 노드 pid 목록. kept 순서로 정렬. | `collect_intra_room_relationships` -> `related_by_pid` | 안정 |
| `images` | array | 매칭 도판. §image. **export엔 없음**, match_images가 주입. | `match_images.py::write_palace_copy` | with_images에만 |

`kept` 노드는 항상 `sequence`/`source_offset`/`offset_confidence`/`related` 를 가진다. `images` 는 매칭된 노드만.

---

## 5. `rooms[*].demoted[*]` (강등 노드)

`build_entity_record(..., with_rank=None)` 로 생성. **sequence/source_offset/offset_confidence/related 없음.**

| 필드 | 타입 | 의미 | 값의 기원 |
|---|---|---|---|
| `id` | str | pid. | `assign_palace_ids` |
| `title` | str | 원제. | `entities.parquet.title` |
| `type` | str | 타입. | `entities.parquet.type` |
| `summary` | str | description 첫 문장 (v1.0 `caption`). | `caption_of` |
| `description` | str | 설명. | `entities.parquet.description` |
| `images` | array | 매칭 도판(있으면). match_images가 주입. kept/demoted 둘 다 붙을 수 있음. | `write_palace_copy` |

---

## 6. `relationships[*]` (방 내부 간선, 최상위)

`export_palace.py::collect_intra_room_relationships()`. **양 끝점이 같은 방에 kept 된 간선만**, parquet 행 순서대로.

| 필드 | 타입 | 의미 | 값의 기원 | 안정/변동 |
|---|---|---|---|---|
| `source` | str | 출발 노드 pid. | `relationships.parquet.source` -> `title_to_pid` | 안정 |
| `target` | str | 도착 노드 pid. | `relationships.parquet.target` -> `title_to_pid` | 안정 |
| `weight` | float\|null | 간선 가중치(NaN이면 null). | `relationships.parquet.weight` | 안정 |
| `description` | str | 간선 설명. | `relationships.parquet.description` | 안정 |

방 경계를 넘는 간선과 한쪽이 demote/누락인 간선은 제외된다.

---

## 7. `image_matching` (최상위, with_images 산출물 전용)

`match_images.py::write_palace_copy()` 가 추가. 매칭 실행 파라미터·집계.
필드: `ran_at`(UTC ISO), `source_palace`(repo 상대), `threshold_local`(0.45), `threshold_cascade`(0.55),
`name_match_bonus`(0.50), `hub_penalty_max`(0.10), `page_window`(1), `min_name_len`(2),
`embed_deployment`(text-embedding-3-small), `caption_rows`, `attached_nodes`, `attached_figures`, `unplaced_figures`.
임계/보너스 상수는 match_images.py 상단 Tunables. `ran_at` 만 비결정적.

---

## 8. `images[*]` (노드 도판) + 소비 노트

`match_images.py::write_palace_copy()` 280~290행. 매칭 행을 노드 title로 묶어 score 내림차순 정렬해 부착.

| 필드 | 타입 | 의미 | 값의 기원 |
|---|---|---|---|
| `path` | str | **PNG 의 repo 상대 경로** (예: `input/img_국사/fig_5_3.png`). | `png_path.relative_to(REPO).as_posix()` (`main` rows 빌드) |
| `caption` | str | 도판 캡션 전문(임베딩에 쓴 full caption). | `detect_joined_caption` 의 `cap_full` |
| `score` | float | 매칭 점수(`cos + name_bonus - hub_penalty`), 소수 3자리. | `score_pair` -> `round(..., 3)` |

**소비 노트:** `images[].path` 는 repo 상대 경로다. 도판 서빙은 소비자(3D FastAPI)가 정적 루트(repo 루트)를
기준으로 이 상대 경로를 붙여 직접 서빙한다. .palace.json 은 경로 문자열만 들고 바이트는 안 들고 있다.

---

## 9. 물음표 항목 코드 확정 결과

(필드명은 v1.1 기준. 괄호 안은 v1.0 옛 이름.)

- **sequence (v1.0 `rank`)**: 방 내 **등장순 1-기준 순번**(정렬 인덱스 성격)이 맞다. Stage B 중요도 랭크가 **아니다**.
  근거: `export()` 의 `for rank, item in enumerate(room['kept'], start=1)` 로 입력 kept 리스트 순서대로
  번호를 매겨 `rec['sequence']` 에 넣는다. 그 입력 순서는 `build_rooms.attach_positions` 가 `pos_first_fine`
  오름차순(등장 위치)으로 정렬한 것을 `convert_toc_to_common_schema` 가 보존한 것이다. Stage B(`assign_rooms`)는
  keep/demote **멤버십**과 방 이름·코히런스만 내고, `build_rooms` 는 `kept_titles = [k['title'] for k in
  r_out['kept']]` 로 **title만** 취해 Stage B가 매겼을 어떤 순위/점수도 버린다. 이후
  `kept_list.sort(key=source_offset)` 로 정렬하므로 fine 케이스에서 sequence와 source_offset이 함께
  단조증가한다(실측 room_00: 1..12 ↔ 34,63,178,469,...). 데이터상 의심대로 등장순.
  (미세 주의: sequence는 정렬 전 attach_positions 순서로 박히고, source_offset은 export의 `_first_in_text`로 다시
  계산한다. fine 케이스에선 동일 신호라 일치하지만, fallback 분기 로직이 약간 달라 드물게 sequence가 source_offset
  정렬과 어긋날 여지는 코드상 존재한다.)
- **source_offset (v1.0 `order`)**: `pos_first_fine` 계열이 맞다. 단위는 **문자(char) 오프셋**. 토큰 인덱스 아님.
  근거: `compute_position` -> `_first_in_text(corpus_text, variants)` 는 `text.find(v)` 로 코퍼스 원문에서 제목
  표면형의 첫 등장 **문자 위치**를 돌려준다. 폴백 시엔 text_unit 의 `char_start`(역시 문자 오프셋).
- **offset_confidence (v1.0 `order_confidence`)**: enum = `{"fine", "fallback"}` 두 값뿐.
  `fine` = 코퍼스 원문에서 제목 표면형을 직접 찾음(문자 오프셋). `fallback` = 못 찾아서 엔티티의 첫 유효
  text_unit `char_start` 사용. **둘 다 실패하면 source_offset=-1 이면서 confidence 는 여전히 `fallback`** (별도
  `unresolved` enum 값은 없다; `unresolved` 는 stats 카운터일 뿐 필드값 아님).
- **summary(노드, v1.0 `caption`)**: description 따로 생성이 **아니다**. `caption_of(description)` 가 description 의
  첫 문장만 잘라 만든다(`다. `/`. ` 등 구분자 기준, 없으면 200자 절단, 한 문장이면 통째). 실측에서 한 문장
  엔티티는 summary == description. (주의: 노드 `summary` 와 이미지 `images[].caption` 은 다른 필드. 이미지 캡션은
  리네임 대상 아님.)
- **palace.meta / rooms[*].meta 내용**: §2, §3 표 참조. v1.1에서 rooms[*].meta 는 `coherence_flag`(LLM) **하나뿐**
  (v1.0의 `source_cluster_count` 는 TOC 경로에서 항상 0이라 v1.1에서 출력 제거).
- **images[] 채우는 위치/형식/경로**: `match_images.py::write_palace_copy` (export 아님). 형식 `{path, caption,
  score}`, score 내림차순. `path` 는 **repo 상대**(`relative_to(REPO).as_posix()`).

## 10. v1.0 -> v1.1 변경 (스키마 동작 변경)

`palace/export_palace.py::export()` 출력 최상위에 추가:
```
"schema_version": "1.1",
"schema_changelog": "1.0->1.1: images[] 추가 + rank->sequence, order->source_offset,
                     order_confidence->offset_confidence, caption->summary,
                     source_cluster_count 삭제",
```
필드 변경 요약:
- `images[]` 노드에 추가(match_images 주입).
- 노드 키 리네임: `rank` -> `sequence`, `order` -> `source_offset`,
  `order_confidence` -> `offset_confidence`, `caption` -> `summary`.
- `rooms[*].meta.source_cluster_count` 출력 제거(TOC 경로 항상 0).

이 외 export/match 로직 변경·리팩터 없음. v1.0 이전 산출물(옛 키, schema_version 없음)은 stale이므로 현재 코드로
재생성해야 v1.1 키가 채워진다.
