# 무거운 백엔드(serve + orchestrator) Azure App Service 배포 런북

날짜: 2026-06-15
대상: serve.py(RAG 서빙) + orchestrator(업로드 파이프라인)를 한 App Service에 co-locate 배포.
실행자: 윤재(실제 Azure 생성/스케일/배포 트리거는 수동). 이 문서는 그 수동 단계 + 근거 + warm 절차.
산출물(이 브랜치 feat/heavy-backend-deploy):
- `backend_app.py`: serve + orchestrator를 한 ASGI 앱으로 마운트한 진입점.
- `startup.sh`: gunicorn 단일 워커 startup 커맨드.
- `.github/workflows/main_heavy-backend.yml`: App Service 배포 워크플로(수동 트리거).
- `ops/warmup_poll.py`: 준비 폴 + warm + keep-warm 스크립트.
- `requirements.txt`: gunicorn 추가.
- `serve.py`: 스냅샷 백그라운드 warmup + `/ready` 게이트(아래 검증 참조).

가벼운 showcase_api/ 배포는 이 작업에서 건드리지 않았다(별도 App Service, 이미 라이브).

---

## 프로세스 모델 (왜 이렇게 묶나)

- App Service 한 인스턴스는 외부로 포트 하나만 노출한다. 프론트는 serve(`/query`)와
  orchestrator(`/upload`, `/jobs/{id}/status`)를 둘 다 호출해야 하므로, `backend_app.py`가
  둘을 한 ASGI 앱으로 마운트한다:
  - serve: 루트(`/`). 경로 그대로: `/health`, `/ready`, `/query`, `/jobs/{id}/query`,
    `/snapshots/register`(내부 전용).
  - orchestrator: `/orchestrator` 아래. 즉 `/orchestrator/upload`,
    `/orchestrator/jobs/{id}/status`, `/orchestrator/jobs/{id}/palace`.
  - 두 앱 모두 `/health`와 `/jobs/{id}/...`를 가져 루트를 공유하면 충돌하므로 프리픽스로 분리.
- lifespan: Starlette는 마운트된 서브앱 lifespan을 자동 실행하지 않는다. serve의 백그라운드
  warmup과 orchestrator의 잡 워커 스레드는 둘 다 lifespan에서 시작되므로, 부모 lifespan이
  AsyncExitStack으로 두 lifespan을 직접 연다(`backend_app.py`).
- 단일 gunicorn 워커: serve가 스냅샷을 RAM에 상주시키므로 워커를 늘리면 워커마다 스냅샷이
  복제돼 RAM이 N배가 된다. 그래서 `startup.sh`는 `--workers 1`로 고정한다. 동시 업로드는
  orchestrator 워커의 단일 큐로 직렬 처리되므로(데모 OK) 워커 1개로 충분하다. 다르게 가야
  한다면 그 이유를 여기 명시할 것.
- serve register는 내부 전용이라, 같은 프로세스의 orchestrator rag 스테이지가
  `http://127.0.0.1:<port>`로 호출한다(`config.SERVE_URL` 기본값이 로컬이라 co-locate면 추가
  설정 불필요).

---

## (1) RSS 측정 → 플랜(B2/B3) 선정 근거

로컬에서 국사(korean_history)로 warm된 serve.py를 측정했다(`uvicorn serve:app`, 단일 프로세스,
국사+ai_school 둘 다 로드된 상태). 측정 방법: 포트 8000 리스너 PID의 WorkingSet64 /
PrivateMemorySize64.

측정값(2026-06-15, 로컬 Windows):
- 워밍 후 WorkingSet64(물리 RSS): 약 282 MB.
- 워밍 후 PrivateMemorySize64(커밋): 약 480 MB.
- 콜드 스타트: 포트 바인드까지 약 34s(litellm/graphrag import 지배), 국사 ready까지 약 55s
  (그 중 `load_engine` 자체는 4.1s, 나머지는 첫 graphrag import). 바인드 직후 `/health`는
  즉시 200을 주며 스냅샷은 `warming`으로 보고한다.

Azure 보정:
- Azure 배포 패키지에는 국사 스냅샷만 들어간다(ai_school은 gitignore, 아래 한계 참조). 따라서
  Azure RSS는 위보다 약간 낮다. 다만 대부분이 라이브러리 베이스라인(graphrag/litellm/lancedb/
  numpy)이라 스냅샷 데이터의 기여는 작다. 워킹셋 약 250~300 MB로 보면 된다.
- ★ 진짜 RAM 피크는 serve 상주가 아니라 라이브 인덱싱 때다. orchestrator가 인덱싱을
  `graphrag index` subprocess로 돌리는데, 그 subprocess가 graphrag 스택을 통째로 다시 올린다
  (약 400~500 MB). 그래서 인덱싱 중 피크 = serve 상주(약 480 MB 커밋) + index subprocess
  (약 400~500 MB) + OS/버퍼 = 대략 1 GB 안팎. 대형 코퍼스면 더 올라간다.

플랜 선정:
- B1(1.75 GB, 1 core): serve 상주만이면 버티지만, 인덱싱 subprocess가 겹치는 순간 약 1 GB
  피크라 OS/버퍼까지 합치면 빠듯하다. 라이브 데모의 크리티컬 패스에는 위험. 비권장.
- B2(3.5 GB, 2 cores): serve 상주 + 인덱싱 subprocess 1개 + 버퍼에 여유. 권장 기본.
- B3(7 GB, 4 cores): 대형 코퍼스/안전 마진/추가 동시성 대비. 업로드가 크거나 여유 예산이면 권장.
- 결론: 데모 안정성 우선이면 B2를 최소로, 여유 있으면 B3. 단일 워커라 serve 480 MB가 N배로
  뻥튀기되지 않는 게 전제(`startup.sh` 유지).

---

## (2) App Service Plan 생성 / 스케일

런타임 스택: Python 3.13(Linux). 쇼케이스와 동일 핀(워크플로 setup-python 3.13,
deploy 액션도 동일 패턴).

1. App Service Plan 생성(Linux, Python 3.13), SKU는 위 근거대로 B2 또는 B3.
2. 그 플랜에 Web App 생성. 앱 이름은 워크플로의 `app-name`과 일치시킨다(현재 플레이스홀더
   `3D-mindpalace-heavy-backend`. 실제 이름으로 바꾸거나 이 이름으로 생성).
3. 쇼케이스 백엔드(`3D-mindpalace-AI-backend`)와 별도 App Service여야 한다. 같은 앱에 올리면
   가벼운 showcase 배포를 덮어쓴다.

---

## (3) Always On 켜기

- App Service > Configuration > General settings > Always On = On.
- 이유: Always On이 꺼져 있으면 유휴 시 워커가 언로드되고, 다음 요청이 콜드 스타트(약 55s
  국사 ready)를 다시 탄다. 데모 중 그 지연은 치명적. Always On으로 상주 유지.
- 헬스 체크 경로(Health check 설정): `/health`로 지정. `/health`는 항상 200을 주고(워밍 중에도)
  스냅샷 상태만 본문에 싣는다. 이게 핵심이다: 콜드 워밍 중에도 App Service가 컨테이너를 죽이지
  않게 `/health`는 200을 유지하고, 진짜 준비 게이트는 `/ready`(미준비 시 503)로 분리했다.
  헬스 체크에 `/ready`를 쓰면 워밍 동안 unhealthy로 보여 컨테이너가 재시작되니 쓰지 말 것.

---

## (4) App settings (환경변수)

App Service > Configuration > Application settings 에 추가:

필수:
- `GRAPHRAG_API_KEY`: Azure OpenAI 키(serve 합성 + 인덱싱 양쪽이 사용. `settings.yaml`의
  `${GRAPHRAG_API_KEY}` 치환, orchestrator 인덱싱 subprocess는 env 상속).
- `GRAPHRAG_API_BASE`: Azure OpenAI 엔드포인트(`settings.yaml`의 `${GRAPHRAG_API_BASE}`).
  api_version은 settings.yaml에 고정(2024-12-01-preview).

빌드/런타임:
- `SCM_DO_BUILD_DURING_DEPLOYMENT` = `true`: Oryx가 배포 시 `pip install -r requirements.txt`를
  플랫폼에서 수행. 무거운 deps(graphrag/spacy/onnxruntime) 때문에 첫 배포 빌드는 수 분 걸린다.
- Startup Command(Configuration > General settings) = `bash startup.sh`. 이게 gunicorn 단일
  워커로 `backend_app:app`을 `0.0.0.0:$PORT`에 바인드한다(`--timeout 600`: 단일 워커가 긴
  global search/인덱싱 호출을 처리하므로 gunicorn 기본 30s 타임아웃에 워커가 안 죽게 넓힌다).
- (선택) `WEBSITES_CONTAINER_START_TIME_LIMIT`: 콜드 import가 약 34s라 기본 230s로 충분하지만,
  대형 deps로 첫 부팅이 늘면 600~1800으로 올린다.

포트/경로(기본값으로 충분, 명시만):
- `PORT`: App Service가 주입. `startup.sh`가 `${PORT:-8000}`로 받는다(추가 설정 불필요).
- 스냅샷 경로: serve는 `results/snapshots/repro_run3`(국사)를 repo 상대 경로로 로드한다. 이
  스냅샷은 git 추적되므로 배포 패키지에 포함된다(아래 한계 참조). 별도 경로 env 불필요.
- `SERVE_URL`: orchestrator rag 스테이지가 serve register를 호출할 주소. co-locate면 기본
  `http://127.0.0.1:8000`이 맞다. App Service가 PORT를 8000이 아닌 값으로 주는 경우에만
  `SERVE_URL`을 `http://127.0.0.1:$PORT`에 맞춰 조정.
- (선택) `ORCH_SEED_PALACE_CACHE`: 기본 1(쇼케이스 도메인이 레퍼런스 방을 결정적으로 재현).
  바꿀 일 없으면 생략.

---

## (5) 배포 트리거

워크플로 `.github/workflows/main_heavy-backend.yml`는 수동 트리거(`workflow_dispatch`)만 켜져
있다. 이유: 무거운 백엔드가 매 push마다 자동 재배포되면 데모 직전에 서버가 재시작/재워밍되어
위험하다. 그래서 윤재가 Actions 탭에서 직접 돌린다.

첫 실행 전 준비:
1. 워크플로의 `app-name`을 실제 App Service 이름으로 맞춘다.
2. GitHub 저장소 secret `AZUREAPPSERVICE_PUBLISHPROFILE_HEAVY_BACKEND`에 그 App Service의
   publish profile을 넣는다(Deployment Center > Manage publish profile, 또는
   `az webapp deployment list-publishing-profiles --xml`).
3. 이 브랜치(feat/heavy-backend-deploy)를 main에 머지(또는 배포 대상 브랜치로). 워크플로는
   기본 브랜치 기준으로 동작한다.

실행: GitHub Actions 탭 > "Build and deploy heavy backend to Azure Web App" > Run workflow.
원하면 나중에 워크플로의 주석 처리된 `push: branches: [main]`을 살려 자동 배포로 전환 가능.

배포 패키지: 워크플로는 repo 전체를 업로드한다(`!antenv/` 제외). 국사 스냅샷(parquet+lancedb,
약 3.7 MB)이 git 추적이라 패키지에 포함되어 serve가 Azure에서 그걸 로드한다.

---

## (6) Warm 절차 (배포 후 / 데모 전)

배포 또는 재시작 직후 serve는 스냅샷을 백그라운드로 warm load한다(앱은 즉시 바인드, `/health`는
바로 200, 워밍 중 `/query`는 503). 준비를 폴하고 검색 경로를 데우려면:

```
# 준비 폴 + 국사 warm 1회(준비될 때까지 폴 후 trivial 질문)
python ops/warmup_poll.py --base-url https://<app>.azurewebsites.net

# 데모 직전 keep-warm(4분마다 trivial 질문으로 콜드아웃 방지)
python ops/warmup_poll.py --base-url https://<app>.azurewebsites.net --keep-warm --interval 240
```

- 기본 대상은 `korean_history`(canonical 데모). `/ready?snapshot=korean_history`가 200이 될
  때까지 폴한 뒤 `/query`를 한 번 친다.
- `/ready`(파라미터 없음)는 모든 스냅샷이 준비됐을 때만 200이다. ai_school이 패키지에 없어
  error로 남으면 `/ready`(전체)는 계속 503이니, 게이팅은 반드시 `--snapshot korean_history`로
  특정 키만 본다(스크립트 기본값이 그렇다).
- 수동 확인:
  ```
  curl https://<app>.azurewebsites.net/health
  curl -i https://<app>.azurewebsites.net/ready?snapshot=korean_history
  ```

---

## (7) ★ 데모 후 스케일다운 / 정지 리마인더

데모가 끝나면 비용/리소스 회수를 위해 반드시:
- App Service > Stop(데모를 또 안 할 거면), 또는
- App Service Plan을 더 작은 SKU로 스케일다운(B3/B2 → B1 또는 Free/Shared), 그리고 Always On
  Off로 유휴 비용 절감.
- keep-warm 스크립트(`--keep-warm`)를 띄워뒀다면 Ctrl-C로 중지.

B2/B3 + Always On은 상주 비용이 계속 나간다. 데모 후 방치 금지.

---

## 검증 결과 (로컬, 2026-06-15)

`uvicorn serve:app`으로 기동해 확인:
- 바인드 직후 `/health` 즉시 200, 본문 `status:"warming"`, 두 스냅샷 모두 `ready:false`로 보고.
  (스냅샷 로드가 끝나기 전에 헬스가 응답함을 확인.)
- 워밍 중 `/query`(국사) → 503, detail `'korean_history' warmup 진행 중. 잠시 후 재시도.`
- 국사 ready 전환 후 `/health` → `status:"ok"`, 국사 `ready:true`, `warmup_seconds≈4.1`,
  `synthesis_model:"gpt-5.4-mini"`. ai_school은 키별로 격리되어 독립 워밍.
- `/ready?snapshot=korean_history` → 준비 후 200, 워밍 중 503.
- 워밍 후 RSS WorkingSet64 약 282 MB / PrivateMemory 약 480 MB(위 (1)).
- orchestrator e2e: `orchestrator/smoke_e2e.py`는 serve의 register/query 계약을 그대로 쓰고,
  이 작업은 그 계약을 바꾸지 않았다(스타트업/lifespan/준비 게이팅만 변경). `/query` 핸들러,
  검색, 라우팅, orchestrator 코드는 불변.

---

## 알려진 한계 / 주의

1. ai_school 스냅샷은 gitignore(`results/snapshots/ai_school/`, throwaway, 재인덱싱 예정)라
   Azure 배포 패키지에 없다. serve는 이를 `error`로 보고하지만 키별로 격리되어 국사 데모에는
   영향이 없다. showcase=ai_school 경로가 데모에 필요하면 윤재가 그 스냅샷을 force-add하거나
   라이브 인덱싱으로 생성해야 한다(이 작업 범위 밖).
2. 인덱싱 입력은 `.txt`(또는 미리 추출된 텍스트)만 지원한다(2026-06-14_live_index_plan.md [E]).
   PDF/슬라이드 직접 업로드는 추출 파이프라인 전까지 깨질 수 있으니 데모는 .txt 안내.
3. 첫 배포 빌드는 무거운 deps로 수 분 걸린다(Oryx pip install). 데모 한참 전에 미리 배포/워밍.
4. 콜드 스타트 국사 ready 약 55s(로컬 기준, graphrag import 지배). Azure에서도 같은 차수.
   Always On + keep-warm으로 데모 중 콜드 스타트를 피한다.
