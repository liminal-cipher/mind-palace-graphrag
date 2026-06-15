"""Minimal showcase API: serves the pre-baked Korean-history palace JSON.

Stage-1 deploy target: a lightweight backend on Azure App Service that hands the
3D frontend a frozen, image-matched palace. No graphrag / indexing / upload here.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

DATA_DIR = Path(__file__).parent / "data"
KOREAN_HISTORY_PALACE = DATA_DIR / "korean_history_with_images.palace.json"

app = FastAPI(
    title="회랑 Showcase API",
    description="Serves the pre-baked Korean-history (_with_images) palace for the 3D frontend.",
    version="0.1.0",
)

# Demo-wide CORS so the 3D frontend can fetch during development.
# TODO: after deploy, narrow allow_origins to the frontend App Service URL,
#       e.g. allow_origins=["https://<frontend-app>.azurewebsites.net"].
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/palace/korean_history")
def korean_history_palace():
    """Return the frozen Korean-history _with_images palace JSON verbatim."""
    if not KOREAN_HISTORY_PALACE.is_file():
        raise HTTPException(status_code=404, detail="palace file not found")
    return FileResponse(KOREAN_HISTORY_PALACE, media_type="application/json")
