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

exec gunicorn backend.app:app \
  --workers 1 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind "0.0.0.0:${PORT}" \
  --timeout 600 \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile -
