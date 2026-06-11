# cold vs warm 단계 분석 (2026-06-11)

GraphRAG 검색 호출의 cold (CLI `graphrag query` 매번 새 프로세스) vs warm (`warm_query.py` 한 번 로드 후 함수 호출) 차이의 단계별 breakdown. audit 표본 1·2의 cold wall time을 오늘 warm 측정으로 분해 검증한 일회성 노트.

## cold 호출에 매번 포함되는 단계

| 단계 | cold | warm |
|---|---:|---:|
| 1. Python 인터프리터 시작 + graphrag/litellm/lancedb import | ~25~35s | 0 |
| 2. settings.yaml + .env load + pydantic validation | ~0.5s | 0 |
| 3. parquet 6종 read (DataReader) | ~2~3s | 0 |
| 4. LanceDB 3 store open | ~1~2s | 0 |
| 5. 검색 엔진 빌드 (LLM client + tokenizer + context builder) | ~1~3s | 0 |
| 6. 첫 LLM 호출 overhead (Azure TLS handshake + LiteLLM warmup) | ~2~5s | 0 |
| 7. 실제 검색 (LLM + retrieval) | (warm 측정값과 동일) | 그 자체 |

1~6 합쳐서 **~30~50s 고정비용**이 cold 호출마다 깔린다. 그 중 import (~25~35s)가 가장 큰 비중. Windows에서 .venv site-packages가 크고 LiteLLM/Azure SDK가 무거운 게 결정적.

`warm_query.py` 워밍업 셀이 43.7s 걸린 게 정확히 1~5단계 합계 (6은 첫 measured 호출에 포함됨). cold도 매번 같은 비용 발생.

## audit 표본 1 cold 분해 검증

| 메서드 | cold default | fixed (1~6) | warm 측정 (warmup 적용) | 합산 추정 |
|---|---:|---:|---:|---:|
| basic | 64s | ~50s | 12.5s | 62.5s ≈ 64s |
| local | 62s | ~47s | 15.3s | 62.3s ≈ 62s |
| global | 77s | ~54s | 23.2s | 77.2s ≈ 77s |
| drift | 289s | ~26s | 263s | 289s |

drift만 fixed가 적게 보이는데, fixed 비용이 줄어든 게 아니라 drift의 67 LLM calls 중 첫 호출 overhead가 다른 호출들 사이에 묻혀 들어가서 그렇게 보인다. 실제로는 ~30~40s 깔린 거 다른 메서드와 동일.

## 실제 RAG 운용 시나리오

- 정의 질문 (basic/local) cold: ~60~65s. import (~30s) + parquet/lancedb (~5s) + 엔진 (~2s) + 검색 (~12~15s).
- 거시 요약 (global) cold: ~75~80s. 위 + community map-reduce 추가.
- 깊이 있는 multi-hop (drift) cold: ~290s (5분). 위 + 67 LLM 호출.

대부분 시간이 import + 첫 LLM overhead라 한 번에 한 질문 cold로 던지면 무겁고, 연속 질문 던질 거면 warm 유지 시 4~6배 이득.

production 권장:
- 한 세션 다회 질문: warm 유지 (FastAPI 등 서버 프로세스). 첫 응답 ~45s, 이후 ~5~25s.
- 일회성 batch: cold 그대로. 같은 프로세스 안에서 여러 질문 던지면 자연스럽게 warm 됨 (LiteLLM import 한 번만 발생).

## 출처

- cold 측정값: `results/audit/2026-06_query_methods.md` 표본 1, 표본 2
- warm 측정값: `results/audit/2026-06-11_method_sweep_warm_default_*.md` 4 모델
- 워밍업 비용 측정: `warm_query.py` 셀 1+2 wall time 43.7s
