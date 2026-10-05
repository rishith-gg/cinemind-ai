from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from cinemind.api.app import create_app
from cinemind.core.config import Settings


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(frontend_dist=None, settings=settings)) as c:
        yield c


def test_project_crud(client: TestClient, settings: Settings) -> None:
    created = client.post("/api/projects", json={"name": "  Short film "}).json()
    pid = created["id"]
    assert created["name"] == "Short film"
    assert settings.project_dir(pid).is_dir()

    assert [p["id"] for p in client.get("/api/projects").json()] == [pid]
    patched = client.patch(f"/api/projects/{pid}", json={"description": "d"}).json()
    assert patched["description"] == "d" and patched["name"] == "Short film"

    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert not settings.project_dir(pid).exists()
    missing = client.get(f"/api/projects/{pid}")
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"


def test_validation_and_traversal_ids(client: TestClient) -> None:
    assert client.post("/api/projects", json={"name": ""}).status_code == 422
    res = client.get("/api/projects/..%2F..%2Fetc")
    assert res.status_code in (404, 422)
    res = client.delete("/api/projects/not-a-valid-id")
    assert res.status_code == 422 and res.json()["code"] == "invalid_input"


def test_openapi_operation_ids(settings: Settings) -> None:
    paths = create_app(frontend_dist=None, settings=settings).openapi()["paths"]
    assert paths["/api/projects"]["post"]["operationId"] == "createProject"
    assert paths["/api/jobs/{job_id}/cancel"]["post"]["operationId"] == "cancelJob"


def test_delete_refused_while_jobs_active(client: TestClient, settings: Settings) -> None:
    from cinemind.db.base import make_engine, make_session_factory
    from cinemind.jobs import queue

    pid = client.post("/api/projects", json={"name": "P"}).json()["id"]
    factory = make_session_factory(make_engine(settings.db_path))
    with factory() as s:
        job = queue.enqueue(s, "dummy", project_id=pid)
    res = client.delete(f"/api/projects/{pid}")
    assert res.status_code == 409 and res.json()["code"] == "job_state"
    with factory() as s:
        queue.request_cancel(s, job.id)
    assert client.delete(f"/api/projects/{pid}").status_code == 204
