from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cinemind.api.app import create_app
from cinemind.core.config import Settings


def test_health_endpoint() -> None:
    client = TestClient(create_app(frontend_dist=None))
    res = client.get("/api/system/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["report"]["recommended"]["tier"] in {"lite", "balanced", "quality"}


def test_openapi_has_health_operation() -> None:
    schema = create_app(frontend_dist=None).openapi()
    assert schema["paths"]["/api/system/health"]["get"]["operationId"] == "getHealth"


def test_refuses_non_local_host() -> None:
    with pytest.raises(ValidationError):
        Settings(host="0.0.0.0")  # noqa: S104


def test_spa_fallback_serves_index_for_deep_links_but_not_api(
    tmp_path: Path, settings: Settings
) -> None:
    (tmp_path / "index.html").write_text("<html>app</html>")
    with TestClient(create_app(frontend_dist=tmp_path, settings=settings)) as client:
        assert "app" in client.get("/projects/abc").text
        assert client.get("/settings").status_code == 200
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get("/%2e%2e/%2e%2e/etc/passwd").status_code in (200, 404)
        assert "root:" not in client.get("/%2e%2e/%2e%2e/etc/passwd").text
        res = client.get("/api/nope")
        assert res.status_code == 404 and "app" not in res.text
