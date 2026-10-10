"""Helpers shared by the API tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from cinemind.core.config import Settings
from cinemind.db.base import make_engine, make_session_factory
from cinemind.jobs import queue
from cinemind.jobs.runner import run_job
from cinemind.jobs.worker import _group_actors  # pyright: ignore[reportPrivateUsage]


def drain(settings: Settings) -> None:
    """Run every queued job inline (what the worker process does)."""
    factory = make_session_factory(make_engine(settings.db_path))
    while (job_id := queue.claim_next(factory)) is not None:
        run_job(factory, settings, job_id)
        _group_actors(factory, settings, job_id)


def import_one(
    client: TestClient, pid: str, path: Path, mode: str = "reference"
) -> dict[str, object]:
    res = client.post(f"/api/projects/{pid}/media", json={"paths": [str(path)], "mode": mode})
    assert res.status_code == 201
    return res.json()["items"][0]
