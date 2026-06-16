# ARCHIVED

이 폴더는 동결. 새 작업은 `palace/` 기반.

palace 정본이 이 폴더에서 복사한 것:
- `room_gen.py` 중 Stage A(`derive_rubric`) · Stage B(`_stage_b_prompt`, `_stage_b_cache_key`, `_run_stage_b_once`, `_resolve_keep_membership`, `assign_rooms`, `check_invariants`, `HARD_CAP_K`) · LLM transport(`call_json`, `make_azure_client`) · `load_snapshot` → `palace/room_gen.py`
- `export_palace.py` 전체 (CWD 상대 경로 `ROOMS=Path('archive/rooms')` 제거, `sys.path.insert` 제거, `export()`에 `rooms_dir` 인자 추가) → `palace/export_palace.py`

복사 안 한 것: GRAPH arm(`base_cluster`, `_stack_normalized`, `split_oversized`, `_split_one`, `merge_to_k`, `_cluster_centroid`, `_merge_embedding`, `representatives`, `_merge_llm`, `generate_rooms`, `_summarize`), 4 combo 진입점(`run_repro_run3.py`), 도메인 무관 평가기(`eval_rooms.py` + `anchors_korean_history.json`), 모델 비교(`build_model_compare.py`). 이건 GRAPH arm 참고용으로 폴더에 남김.
