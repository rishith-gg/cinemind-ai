"""FastAPI application factory. Bound to 127.0.0.1 only (see core/config.py)."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.types import Scope

from cinemind import __version__
from cinemind.api import (
    actor_pairs,
    actors,
    analysis,
    fs,
    jobs,
    media,
    projects,
    quality,
    shots,
    speech,
    timelines,
    transcripts,
)
from cinemind.core.config import REPO_ROOT, Settings, get_settings
from cinemind.core.doctor import DoctorReport, run_doctor
from cinemind.core.errors import DomainError
from cinemind.db.base import make_engine, make_session_factory
from cinemind.db.migrate import upgrade_head
from cinemind.jobs.registry import load_extra_modules

log = logging.getLogger(__name__)

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


class SPAStaticFiles(StaticFiles):
    """Serves the built frontend; unknown non-API paths get index.html so deep links and
    reloads work with client-side routing. Unknown /api paths stay real 404s."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            is_api = path == "api" or path.startswith("api/")
            if exc.status_code != 404 or is_api or "." in path.rsplit("/", 1)[-1]:
                raise  # real 404s for API routes and for missing files such as /assets/x.js
            response = await super().get_response("index.html", scope)
        if response.headers.get("content-type", "").startswith("text/html"):
            # The page names the current (hashed) script. Without this a browser keeps showing
            # an old build after an update; the hashed assets themselves stay cacheable.
            response.headers["Cache-Control"] = "no-cache"
        return response


class HealthResponse(BaseModel):
    status: str
    version: str
    report: DoctorReport


def create_app(
    frontend_dist: Path | None = FRONTEND_DIST, settings: Settings | None = None
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        load_extra_modules(settings)
        upgrade_head(settings.db_path)
        engine = make_engine(settings.db_path)
        app.state.session_factory = make_session_factory(engine)
        yield
        engine.dispose()

    app = FastAPI(title="CineMind AI", version=__version__, lifespan=lifespan)
    app.state.settings = settings

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"code": exc.code, "message": exc.message}
        )

    app.include_router(projects.router)
    app.include_router(jobs.router)
    app.include_router(media.router)
    app.include_router(fs.router)
    app.include_router(shots.router)
    app.include_router(quality.router)
    app.include_router(timelines.router)
    app.include_router(transcripts.router)
    app.include_router(speech.router)
    app.include_router(actors.router)
    app.include_router(actor_pairs.router)
    app.include_router(analysis.router)

    @app.get(
        "/api/system/health",
        response_model=HealthResponse,
        tags=["system"],
        operation_id="getHealth",
    )
    def health() -> HealthResponse:
        report = run_doctor(settings)
        return HealthResponse(
            status="ok" if report.ok else "degraded", version=__version__, report=report
        )

    # Built frontend (single-command run). Mounted last so /api routes win.
    if frontend_dist is not None and frontend_dist.is_dir():
        app.mount("/", SPAStaticFiles(directory=frontend_dist, html=True), name="frontend")
    return app
