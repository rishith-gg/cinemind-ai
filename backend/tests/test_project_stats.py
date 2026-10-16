"""Dashboard statistics: counts of a processed project, and an empty project."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cinemind.core.config import Settings
from search_helpers import processed_cuts


def test_stats_of_an_empty_project(client: TestClient, pid: str) -> None:
    res = client.get(f"/api/projects/{pid}/stats")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["clips"] == 0 and data["shots"] == 0 and data["states"] == {}
    assert data["quality_bands"] == [0, 0, 0, 0, 0]


def test_stats_count_what_processing_produced(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    cut_footage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    found: dict[str, Any] = processed_cuts(
        client, pid, api_settings, cut_footage, tmp_path, monkeypatch
    )
    client.put(f"/api/shots/{found['shots'][0]}/mark", json={"mark": "select"})
    data = client.get(f"/api/projects/{pid}/stats").json()
    assert data["clips"] == 1 and data["states"] == {"succeeded": 1}
    assert data["duration_s"] == pytest.approx(8.0, abs=0.1)
    assert data["shots"] == 4 and data["scenes"] >= 1
    assert sum(data["quality_bands"]) == data["quality_measured"] == 4
    assert data["transcripts"] == {"done": 1} and data["languages"] == {"en": 1}
    assert data["segments"] == 2  # one certain and one uncertain line
    assert data["selected"] == 1 and data["rejected"] == 0
    assert data["codecs"] and data["landscape"] == 1 and data["frame_rates"] == ["25"]


def test_stats_of_a_missing_project(client: TestClient) -> None:
    res = client.get("/api/projects/0123456789abcdef0123456789abcdef/stats")
    assert res.status_code == 404 and res.json()["code"] == "not_found"
