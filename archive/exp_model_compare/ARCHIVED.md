# ARCHIVED

이 폴더는 동결. 새 작업은 `palace/` 기반.

측우기·모델 비교 진단 자산. 닫힌 트랙. 정본은 `palace/`.

repro_run3 K=6 TOC arm을 네 가지 모델(gpt41, gpt41mini, gpt54, gpt54mini)로 각 3런 돌려 산출 비교했던 일회성 진단. 진입점은 `build_model_compare.py`, 산출은 `repro_run3_K6_toc.<model>.run{1,2,3}.{json,palace.json}` 24개. palace 정본 검증은 `palace/tests/golden/`과 `palace/tests/compare_golden.py`로 다른 경로.
