## 회랑 GraphRAG 파이프라인

학습 자료(한국사 교과서 등)를 GraphRAG로 돌려 개념을 커뮤니티("방")로 묶고, level 0 커뮤니티를 "건물"로 써서 3D 기억의 궁전을 만드는 암기 도구의 백엔드 파이프라인.

**프로젝트 맥락·진행 상태·다음 할 일은 [STATUS.md](./STATUS.md) 참고.**

리포트는 [results/reports/](./results/reports/)에 모음 (작성 규칙: [REPORT_TEMPLATE.md](./results/reports/REPORT_TEMPLATE.md), 매핑: [INDEX.md](./results/reports/INDEX.md)).

## 환경 준비

1. Python 3.13 + venv:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. `.env.example`을 `.env`로 복사하고 Azure OpenAI 키 채우기:
   ```
   GRAPHRAG_API_KEY=<your-azure-openai-key>
   ```
3. 베이스 스냅샷 `results/snapshots/repro_run3/`이 있어야 실험 5 재현 가능 (357 entities, level 0 = 40).

## 지금 돌아가는 명령어

### GraphRAG 인덱싱 (추출 + 묶기)
```
graphrag index --root .
```
`settings.yaml` 기준. 같은 입력이어도 LLM 비결정성으로 ±10 흔들리므로 매번 새로 추출하지 말고 스냅샷 재사용 권장.

### 실험 5: 방 병합

임베딩 기반 (성공, 결정적):
```
python exp5_embed.py
```
→ `results/exp5/stage2_emb_K{5,8,10}.json` + `embed_silhouette_summary.json` + `embed_reliability.json`

LLM 기반 partition 방식 (현 시점 실패 기록용):
```
python exp5_llm.py
```
→ `results/exp5/llm_reliability.json` (stage2 LLM 파일은 성공 시에만 생성)

### 분석 보조
```
python analyze_baseline.py     # output/ parquet 요약
python extract_results.py      # 결과 추출
```

## 절대 건드리지 말 것

- `results/snapshots/` (특히 `repro_run3/`): 실험 5 베이스. 재추출하면 ±10 흔들려 재현 불가.
- `results/exp5/*.json`: 실험 결과 기록.
- 루트 `exp5_lib.py` / `exp5_embed.py` / `exp5_llm.py`: 경로 하드코딩됨. 옮기면 깨짐.
