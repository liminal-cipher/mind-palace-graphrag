#!/usr/bin/env bash
# App Service (Linux / Python) startup command for the heavy backend.
# Set the App Service "Startup Command" to:  bash startup.sh
#
# Single gunicorn worker on purpose: serve.py keeps GraphRAG snapshots resident in
# RAM, so every extra worker duplicates that footprint (N x RAM). Co-located with the
# orchestrator indexing subprocess they already compete for memory, so we stay at one
# worker and size the plan (B2/B3) instead. See the deploy runbook for the rationale
# and the measured RSS. If you ever need more than one worker, document why there.
#
# --timeout 600: a single worker serves long global-search and indexing calls; the
# gunicorn default of 30s would kill the worker mid-request. The event loop stays
# responsive because heavy work runs on a thread executor, but we keep a wide margin.
set -euo pipefail

PORT="${PORT:-8000}"

# 스캔 PDF 전처리(STEP4 doclayout-yolo)가 import 하는 opencv(cv2)는 시스템 라이브러리
# (libGL/libxcb 등)를 요구하는데 App Service Oryx 이미지에 기본 미포함이다. 여기서 설치한다.
# 실패해도 startup 은 계속(디지털 PDF/쿼리는 cv2 불필요라 무관). 콜드스타트마다 1회 실행.
apt-get update -y >/dev/null 2>&1 && apt-get install -y --no-install-recommends \
  libgl1 libglib2.0-0 libxcb1 libsm6 libxext6 libxrender1 >/dev/null 2>&1 \
  || echo "[startup] opencv 시스템 라이브러리 설치 실패(스캔 STEP4 영향 가능, 디지털 무관)"

exec gunicorn backend.app:app \
  --workers 1 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind "0.0.0.0:${PORT}" \
  --timeout 600 \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile -
