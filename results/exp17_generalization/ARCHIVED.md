# ARCHIVED

이 폴더는 동결. 새 작업은 `palace/` 기반.

palace 정본이 이 폴더에서 복사한 것:
- `toc_gen.py` 중 `SYS_PROMPT`, `build_user_prompt`, `resolve_offsets`, `generate_toc` (모듈 상수 `CORPUS/MODEL/OUT` 제거, `corpus_rel` 인자 추가) → `palace/toc_gen.py`
- `build.py` 중 TOC arm 함수(`char_overlap`, `build_toc_rooms`, `attach_positions`, `apply_keep_demote`, `convert_toc_to_common_schema`, `absorb_empty_rooms`) (모듈 상수 `K/DOMAIN/MODEL/NODE_BUDGET/N_RUNS/RUBRIC_CACHE/SET1_METHOD` 전부 인자로 외화) → `palace/build_rooms.py`

복사 안 한 것: GRAPH arm(`build_graph_rooms`), 블라인드 비교(`build_blind`, `compute_metrics`, `render_markdown`), AI 교안 인덱싱·정제(`snapshot.py`, `clean_corpus.py`, `index_metrics.py`), exp17 산출(`toc_llm.json`, `toc_rooms.json`, `graph_rooms.json`, `blind_*.json`, `metrics.json`, `rooms_ordered.md`, `REPORT.md`, `PHASE_A_CHECKPOINT.md`).
