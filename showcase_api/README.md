# 회랑 Showcase API

Stage-1 deploy: a minimal FastAPI backend that serves the pre-baked Korean-history
`_with_images` palace JSON to the 3D frontend. Intentionally has **no** graphrag /
indexing / upload dependencies so the App Service build stays light.

## Endpoints

| Method | Path                     | Returns                                            |
|--------|--------------------------|----------------------------------------------------|
| GET    | `/health`                | `{"status":"ok"}`                                  |
| GET    | `/palace/korean_history` | The frozen `korean_history_with_images` palace JSON |

CORS is open (`allow_origins=["*"]`) for the demo. After deploy, narrow it to the
frontend App Service URL (see the TODO in `main.py`).

## Layout

```
showcase_api/
  main.py            FastAPI app
  requirements.txt   fastapi, uvicorn[standard], gunicorn
  data/
    korean_history_with_images.palace.json   (copy of the frozen palace)
```

The data file is a byte-identical copy of `palace/handoff/korean_history_with_images.palace.json`.
The frozen original is never modified.

## Run locally

```
pip install -r requirements.txt
gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 main:app
```

Then:

```
curl http://localhost:8000/health
curl http://localhost:8000/palace/korean_history
```

## Azure App Service (Linux / Python / Code deploy)

Set the **Startup Command** to:

```
gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 main:app
```

App Service Linux Python expects the app to listen on port 8000 by default, which
matches the `-b 0.0.0.0:8000` bind above.

> If the runtime injects a different port via `$PORT`, use
> `-b 0.0.0.0:$PORT` instead.

### Deploy structure

This folder is **self-contained**: it can be lifted into its own minimal repo whose
root is this app, which is the cleanest fit for Deployment Center (it builds from the
repo root and would otherwise try to install the heavy root `requirements.txt`). See
the parent report for the exact human connection steps and the GitHub Actions
subfolder-deploy alternative.
