## 회랑 GraphRAG 파이프라인

학습 자료(한국사 교과서 등)를 1인칭 3D 기억의 궁전으로 만들기 위해, 자료의 목차를 LLM이 만들고 그 섹션을 "방"으로 써서 개념을 배정·선별하는 암기 도구의 백엔드 파이프라인.

## 정본은 `palace/`

여기만 보면 된다. 나머지 `archive/exp*`, `archive/pipeline`은 정본이 확정되기까지의 실험 아카이브이고, 각 폴더에 `ARCHIVED.md`로 동결 표시돼 있다. 정본 파이프라인의 레이아웃·동작·실행 명령은 [palace/README.md](./palace/README.md), 재현 절차 한 장은 [results/RUNBOOK.md](./results/RUNBOOK.md), 실험 누적 narrative는 [results/EXPERIMENTS.md](./results/EXPERIMENTS.md) 참조.

## 환경 준비

1. Python 3.13 + venv:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. `.env.example`을 `.env`로 복사하고 Azure OpenAI 키·엔드포인트(`GRAPHRAG_API_KEY`, `GRAPHRAG_API_BASE`)를 채운다.
3. 베이스 스냅샷 `results/snapshots/repro_run3/`이 있어야 후속 실험(exp5~17) 및 palace 골든 검증 재현 가능.

정본 실행 예 (한국사 K=6 골든):

```
python -m palace.run --config palace/configs/korean_history.json --phase toc
python -m palace.run --config palace/configs/korean_history.json --phase rooms
python palace/tests/compare_golden.py --run-id korean_history
```
