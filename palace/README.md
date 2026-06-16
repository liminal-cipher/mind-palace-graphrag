# palace

회랑 프로젝트의 정본 TOC arm 파이프라인. 학습 자료(.txt 한 묶음 + graphrag 스냅샷)를 받아 LLM이 만든 목차를 char-overlap으로 그라운딩, 엔티티를 방에 배정, 방마다 keep/demote 선별, 3D 핸드오프용 `.palace.json`을 emit 한다.

## 레이아웃

- `run.py`: CLI 진입점. `--config <cfg.json> --phase toc|rooms`
- `toc_gen.py`: LLM TOC + start_marker 그라운딩
- `build_rooms.py`: char-overlap 방 배정, 위치 정렬, keep/demote 적용, 공통 스키마 변환, 빈 방 흡수
- `room_gen.py`: snapshot 로더, Azure transport, Stage A(rubric), Stage B(assign_rooms), invariant 체크
- `node_metrics.py`: text_unit/엔티티 위치 계산
- `export_palace.py`: rooms.json -> .palace.json
- `configs/`: 도메인별 설정 JSON (run_id, corpus, snapshot, K, node_budget, model, domain, cache 경로 등)
- `tests/golden/`: 골든 산출(현행 archive/rooms/ 복사본)
- `tests/compare_golden.py`: 현 run vs 골든 비교

## 두 단계

- `--phase toc`: LLM 한 번 호출, `toc_llm.json` 만들고 멈춤. 사람이 섹션을 검토할 시간.
- `--phase rooms`: 위 `toc_llm.json`을 읽어 방 배정 -> Stage A/B -> palace.json까지 한 번에.

Stage A(rubric) 및 Stage B(per-room keep)는 캐시 파일에 해시-키 저장. 캐시 hit 시 LLM 호출 0회, 재실행 byte-identical.

## GRAPH arm

방 생성을 임베딩 기반 클러스터링으로 하는 GRAPH arm(`archive/exp10_room_gen/room_gen.base_cluster + split_oversized + merge_to_k`, `archive/pipeline/run.py`)은 palace 정본에 포함하지 않는다. exp 디렉토리에 grandfather로 남아 있고, 새 실험은 palace 기반.

## 실행

```
python -m palace.run --config palace/configs/korean_history.json --phase toc
python -m palace.run --config palace/configs/korean_history.json --phase rooms
```

골든 검증:

```
python palace/tests/compare_golden.py --run-id korean_history
```
