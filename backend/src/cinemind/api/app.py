"""FastAPI application factory. Bound to 127.0.0.1 only (see core/config.py)."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from cinemind import __version__
from cinemind.core.config import REPO_ROOT, get_settings
from cinemind.core.doctor import DoctorReport, run_doctor

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


class HealthResponse(BaseModel):
    status: str
    version: str
    report: DoctorReport


def create_app(frontend_dist: Path | None = FRONTEND_DIST) -> FastAPI:
    app = FastAPI(title="CineMind AI", version=__version__)

    @app.get(
        "/api/system/health",
        response_model=HealthResponse,
        tags=["system"],
        operation_id="getHealth",
    )
    def health() -> HealthResponse:
        report = run_doctor(get_settings())
        return HealthResponse(
            status="ok" if report.ok else "degraded", version=__version__, report=report
        )

    # Built frontend (single-command run). Mounted last so /api routes win.
    if frontend_dist is not None and frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    return app
