"""RetinaScreen API plus the built React app, on one port.

    cd backend && ../.venv/bin/uvicorn app.main:app --port 7860
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.db import init_db
from app.core.errors import error_response, register_error_handlers
from app.modules.auth.router import router as auth_router
from app.modules.demo.router import router as demo_router
from app.modules.model_card.router import router as model_card_router
from app.modules.reviews.router import router as reviews_router
from app.modules.screenings import inference
from app.modules.screenings.router import router as screenings_router
from app.modules.users.router import router as users_router
from app.seed import seed_if_empty

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 1. Upload folder, tables and demo data
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    if settings.SEED_ON_STARTUP:
        seed_if_empty()
    # 2. Load the model ONCE, off the event loop
    await asyncio.to_thread(inference.load_screener)
    if not settings.frontend_dist.joinpath("index.html").is_file():
        logger.warning("No built frontend at %s; run `npm run build` in frontend/", settings.frontend_dist)
    yield


app = FastAPI(title="RetinaScreen API", version="0.4.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
register_error_handlers(app)


@app.get("/health", tags=["health"], summary="Liveness", response_model=dict[str, str])
def health() -> dict[str, str]:
    return {"status": "ok"}


v1 = APIRouter(prefix="/api/v1")
for module_router in (auth_router, users_router, screenings_router, reviews_router, model_card_router, demo_router):
    v1.include_router(module_router)
app.include_router(v1)

# Built frontend: hashed assets, then index.html for every client-side route (the app renders its own 404)
_assets = settings.frontend_dist / "assets"
if _assets.is_dir():
    app.mount("/assets", StaticFiles(directory=_assets), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str, request: Request):
    if path == "api" or path.startswith("api/"):
        return error_response(404, "NOT_FOUND", "Not found")
    index = settings.frontend_dist / "index.html"
    candidate = (settings.frontend_dist / path).resolve()
    if path and candidate.is_file() and settings.frontend_dist.resolve() in candidate.parents:
        return FileResponse(candidate)
    if not index.is_file():
        return JSONResponse({"detail": "Frontend not built. Run `npm run build` in frontend/."}, status_code=503)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
