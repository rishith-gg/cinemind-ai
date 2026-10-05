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
