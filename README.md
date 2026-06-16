## 회랑 GraphRAG 파이프라인

학습 자료(한국사 교과서, 통계 교안 등)를 1인칭 3D 기억의 궁전으로 만드는 백엔드.
자료의 목차를 LLM이 만들고 그 섹션을 "방"으로 써서 개념을 배정·선별한 뒤,
GraphRAG 인덱스 위에서 질의(RAG)와 쇼케이스 팰리스를 서빙한다.

## 레포 구조

| 폴더 | 역할 |
|---|---|
| `backend/` | 서빙(통합 FastAPI). `app`(진입점) + `serve`(RAG 질의) + `showcase`(팰리스·이미지) + `query`(엔진) |
| `orchestrator/` | 업로드 → 인덱싱 → palace → 등록 자동 파이프라인(라이브 인제스트) |
| `palace/` | 방 빌드 정본. TOC → 방 배정/선별 → `palace.json` (`run.py`, `build_rooms.py`, `configs/`, `tests/`) |
| `indexing/` | 도메인별 GraphRAG 인덱싱 config (`<domain>/settings.yaml` + 튜닝 프롬프트, `_template.settings.yaml`) |
| `preprocessing/` | 원본 PDF → 정제 코퍼스 (`pipeline_v2.py`, `normalize.py`, `source/`, `result/`) |
| `snapshots/` | 빌드된 GraphRAG 인덱스 (`repro_run3`=국사 골든, `statistics`) |
| `deliverables/` | 프론트가 읽는 도메인별 산출물 (`<domain>/palace.json`, `palace_with_images.json`, `images/`) |
| `docs/` | 분석 문서 (`RUNBOOK.md`, `EXPERIMENTS.md`, `CONVENTIONS.md`, `audit/`) |
| `input/` | 도메인별 정제 코퍼스 (저작물, gitignored) |
| `archive/` | 동결된 실험·분석 (`ARCHIVED.md` 표시, 새 작업 금지) |
| `prompts/` | 공유 프롬프트(검색 + 기본 인덱싱). 루트 `settings.yaml`은 쿼리 config |

## 환경 준비

1. Python 3.13 + venv:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. `.env.example`을 `.env`로 복사하고 키를 채운다(.env는 gitignored):
   - `GRAPHRAG_API_KEY`, `GRAPHRAG_API_BASE`: 쿼리·인덱싱(Azure OpenAI)
   - `CONTENT_UNDERSTANDING_*`, `OPEN_AI_*`: 전처리(`preprocessing/pipeline_v2.py`)에서만 필요
3. 기본 스냅샷 `snapshots/repro_run3/`(국사, 357 엔티티)가 있어야 골든 검증 재현 가능.

## 백엔드 실행 + API

```
gunicorn backend.app:app --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
# 개발:  uvicorn backend.app:app --reload
# App Service: "Startup Command" = bash startup.sh
```

서빙 도메인: `korean_history`, `statistics`.

| 메서드 · 경로 | 용도 |
|---|---|
| `GET /palace/{name}` | 쇼케이스 팰리스 JSON(이미지 포함) |
| `GET /images/{name}/{file}` | 팰리스가 참조하는 그림 |
| `POST /query` | RAG 질의. body `{"question": "...", "snapshot": "korean_history"}` → `{"answer", "snapshot"}` |
| `GET /health` · `/ready` | 헬스 / 스냅샷 준비 여부 |
| `POST /orchestrator/upload?filename=&domain=` | 파일(raw body) 업로드 → 자동 체인 → `job_id` |
| `GET /orchestrator/jobs/{id}/status` · `/palace` | 잡 진행 / 산출 팰리스 |
| `POST /jobs/{id}/query` | 라이브 잡 RAG 질의 |

```bash
# 쇼케이스 팰리스 (프론트)
curl http://127.0.0.1:8000/palace/korean_history

# RAG 질의
curl -X POST http://127.0.0.1:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"조선 전기의 통치 제도를 설명해줘.","snapshot":"korean_history"}'

# 라이브 업로드 → 자동 인덱싱·palace (이후 /orchestrator/jobs/<id>/status 폴링)
curl -X POST "http://127.0.0.1:8000/orchestrator/upload?filename=corpus.txt&domain=statistics" \
  --data-binary @input/statistics/corpus.txt
```

## 도메인 추가 (큐레이션 쇼케이스)

```
preprocessing/source/<domain>.pdf                              # 원본(gitignored)
python -m preprocessing.pipeline_v2 --pdf preprocessing/source/<domain>.pdf   # 정제 -> result/<domain>_vN
python preprocessing/normalize.py --result preprocessing/result/<domain>_vN --domain <domain>
                                                               # -> input/<domain>/{corpus.txt, captions.md, pagesplit.txt, images/}
graphrag index --root indexing/<domain>                        # -> output/<domain>, snapshots/<domain> 로 복사(캡처)
python -m palace.run --config palace/configs/<domain>.json --phase toc   # LLM TOC 검토용
python -m palace.run --config palace/configs/<domain>.json --phase rooms # -> palace.json
python -m palace.match_images --palace deliverables/<domain>/palace.json \
  --snapshot snapshots/<domain> --figures-dir input/<domain>/images \
  --captions input/<domain>/captions.md --pagesplit input/<domain>/pagesplit.txt --write-palace
# 마지막: backend/showcase.py SHOWCASE_PALACES 와 backend/serve.py SNAPSHOTS 에 도메인 등록
```

신규 인덱싱 config는 `indexing/_template.settings.yaml`을 복사해 `<domain>` 경로만 수정.
라이브 사용자 업로드는 이 수동 경로가 아니라 orchestrator(`/upload`, `var/jobs/`)가 자동 처리.

## 정본 검증 (국사 골든)

```
python -m palace.run --config palace/configs/korean_history.json --phase rooms
python palace/tests/compare_golden.py --run-id korean_history   # 캐시 히트 시 byte-identical
```
국사는 `assignment: chunk_overlap`으로 핀(골든 동작 보존), 신규 도메인은 `fine_pos` 기본.

## 더 보기

- 정본 방 빌드 상세: [palace/README.md](./palace/README.md)
- 재현 절차: [docs/RUNBOOK.md](./docs/RUNBOOK.md)
- 실험 누적 narrative: [docs/EXPERIMENTS.md](./docs/EXPERIMENTS.md)
- 규약: [docs/CONVENTIONS.md](./docs/CONVENTIONS.md)
