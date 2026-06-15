"""Minimal showcase API: serves the pre-baked Korean-history palace JSON.

Stage-1 deploy target: a lightweight backend on Azure App Service that hands the
3D frontend a frozen, image-matched palace. No graphrag / indexing / upload here.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = BASE_DIR / "images"
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


# Serve the palace's referenced PNGs as static files. The mount mirrors each
# node's images[].path verbatim, so a path "input/korean_history/img/fig_5_3.png"
# is fetched at GET /images/input/korean_history/img/fig_5_3.png. The frontend
# resolves an image URL as <base>/images/<images[].path>.
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/palace/korean_history")
def korean_history_palace():
    """Return the frozen Korean-history _with_images palace JSON verbatim."""
    if not KOREAN_HISTORY_PALACE.is_file():
        raise HTTPException(status_code=404, detail="palace file not found")
    return FileResponse(KOREAN_HISTORY_PALACE, media_type="application/json")
