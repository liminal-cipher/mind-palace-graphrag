## 회랑 GraphRAG 파이프라인

학습 자료(한국사 교과서 등)를 GraphRAG로 돌려 개념을 "방"으로 묶고, level 0 커뮤니티를 "건물"로 써서 1인칭 3D 기억의 궁전을 만드는 암기 도구의 백엔드 파이프라인.

## 환경 준비

1. Python 3.13 + venv:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. `.env.example`을 `.env`로 복사하고 Azure OpenAI 키·엔드포인트(`GRAPHRAG_API_KEY`, `GRAPHRAG_API_BASE`)를 채운다.
3. 베이스 스냅샷 `results/snapshots/repro_run3/`이 있어야 후속 실험(exp5~13) 재현 가능.

실험 로그는 [results/EXPERIMENTS.md](./results/EXPERIMENTS.md), 재현 명령은 [results/RUNBOOK.md](./results/RUNBOOK.md) 참조.
