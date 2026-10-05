"""Acceptance: a stage chain runs in a real worker process, survives kill -9, streams over SSE."""

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from cinemind.api.app import create_app
from cinemind.core.config import REPO_ROOT, Settings
from cinemind.jobs import queue


def _start_worker(settings: Settings) -> subprocess.Popen[bytes]:
    tests = REPO_ROOT / "backend" / "tests"
    env = {
        **os.environ,
        "CINEMIND_DATA_DIR": str(settings.data_path),
        "CINEMIND_WORKER_POLL_SECONDS": "0.05",
        "CINEMIND_EXTRA_STAGE_MODULES": '["dummy_chain"]',
        "PYTHONPATH": os.pathsep.join([str(tests), str(REPO_ROOT / "backend" / "src")]),
    }
    return subprocess.Popen([sys.executable, "-m", "cinemind.jobs.worker"], env=env)  # noqa: S603


def _wait(cond: Callable[[], bool], timeout: float = 30) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("timed out waiting for condition")


def _status(factory: sessionmaker[Session], job_id: str) -> str:
    with factory() as s:
        return queue.get_job(s, job_id).status


def test_worker_survives_kill_and_resumes(
    factory: sessionmaker[Session], settings: Settings, tmp_path: Path
) -> None:
    marker, gate = tmp_path / "marker", tmp_path / "gate"
    with factory() as s:
        job_id = queue.enqueue(s, "dummy", params={"marker": str(marker), "gate": str(gate)}).id

    worker = _start_worker(settings)
    try:
        # Stage b is blocked on the gate, so the job is mid-flight when we kill the worker.
        _wait(lambda: marker.exists() and "b" in marker.read_text().split())
        time.sleep(0.5)  # let stage b report some progress
        worker.kill()
        worker.wait()
        assert _status(factory, job_id) == "running"
    finally:
        worker.kill()

    gate.write_text("open")
    worker = _start_worker(settings)
    try:
        _wait(lambda: _status(factory, job_id) == "succeeded")
    finally:
        worker.terminate()
        worker.wait(timeout=10)

    # a ran once (cached after restart), b was interrupted and re-run, c ran once.
    assert marker.read_text().split() == ["a", "b", "b", "c"]
    with factory() as s:
        job = queue.get_job(s, job_id)
        assert [st.status for st in job.stages] == ["cached", "succeeded", "succeeded"]
        assert job.attempts == 2

    # SSE replay of the stored events (follow=false closes after the backlog).
    with TestClient(create_app(frontend_dist=None, settings=settings)) as client:
        body = client.get("/api/jobs/events", params={"follow": "false", "job_id": job_id}).text
        frames = [f for f in body.split("\n\n") if f.startswith("id:")]
        types = [f.split("\nevent: ")[1].split("\n")[0] for f in frames]
        assert types[0] == "queued" and types[-1] == "succeeded"
        assert "progress" in types and "started" in types
        payload = json.loads(frames[-1].split("data: ")[1])
        assert payload["job_id"] == job_id

        # Resume from Last-Event-ID returns only newer events.
        first_id = frames[0].split("\n")[0].removeprefix("id: ")
        resumed = client.get(
            "/api/jobs/events",
            params={"follow": "false", "job_id": job_id},
            headers={"Last-Event-ID": first_id},
        ).text
        assert resumed.count("id:") == len(frames) - 1
