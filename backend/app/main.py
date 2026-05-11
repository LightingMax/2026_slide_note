from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title="Slide Note API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")

assets_dir = settings.static_dir / "assets"
if assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/{full_path:path}")
def serve_frontend(full_path: str) -> FileResponse:
    index = settings.static_dir / "index.html"
    target = settings.static_dir / full_path
    if full_path and target.exists() and target.is_file():
        return FileResponse(target)
    if index.exists():
        return FileResponse(index)
    return FileResponse(Path(__file__).resolve())
