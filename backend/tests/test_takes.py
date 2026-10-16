"""Take groups through the API: found after processing, the user's corrections surviving
regrouping, and one take per group in the rough cut. Two clips: `a_h264.mp4` (one shot, the test
pattern) and `cuts.mp4` (four shots, the first the same test pattern); the stand-in transcriber
hears the same line at 0.2-1.8 s in both, so their first shots are two takes of one line."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cinemind.core.config import Settings
from cinemind.core.rough_cut_config import RoughCutConfig
from cinemind.db.base import make_engine, make_session_factory
from cinemind.db.people import FeedbackEvent
from helpers import drain, import_one
from search_helpers import processed_cuts


@pytest.fixture
def project(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    footage: Path,
    cut_footage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    found = processed_cuts(client, pid, api_settings, cut_footage, tmp_path, monkeypatch)
    media: Any = import_one(client, pid, footage / "a_h264.mp4")["media"]
    drain(api_settings)
    found["other"] = client.get(f"/api/media/{media['id']}/shots").json()[0]["id"]
    api_settings.rough_cut = RoughCutConfig(min_quality=0.0)
    # Grouped by the worker once the queue was empty, like scenes and actors.
    assert client.get(f"/api/projects/{pid}/takes").json()["grouped_at"] is not None
    return found


def _takes(client: TestClient, pid: str) -> dict[str, Any]:
    res = client.get(f"/api/projects/{pid}/takes")
    assert res.status_code == 200, res.text
    return res.json()


def _put(client: TestClient, pid: str, what: str, **body: Any) -> dict[str, Any]:
    res = client.put(f"/api/projects/{pid}/takes/{what}", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def test_takes_are_found_after_processing_with_the_numbers_behind_them(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    data = _takes(client, pid)
    assert data["shots"] == 5 and data["message"] is None
    assert data["details"]["groups"] == 1 and data["details"]["shots_with_speech"] == 2
    [g] = data["groups"]
    assert g["kind"] == "speech" and g["best_by"] == "auto"
    assert {m["shot_id"] for m in g["members"]} == {project["shots"][0], project["other"]}
    assert [m["rank"] for m in g["members"]] == [1, 2]
    assert g["members"][0]["best"] and g["best_shot_id"] == g["members"][0]["shot_id"]
    for m in g["members"]:
        assert set(m["signals"]) == {"focus", "exposure", "audio", "complete", "clean"}
        assert m["text"] == "walking into the forest now" and m["keyframe_id"]
    [link] = g["pairs"]
    assert link["rule"] == "speech" and link["text"] == 1.0 and link["score"] >= 0.75


def test_best_take_and_apart_are_kept_through_regrouping(
    client: TestClient, pid: str, project: dict[str, Any], api_settings: Settings
) -> None:
    [g] = _takes(client, pid)["groups"]
    second = g["members"][1]["shot_id"]
    data = _put(client, pid, "best", shot_id=second)
    assert data["groups"][0]["best_shot_id"] == second and data["groups"][0]["best_by"] == "you"
    res = client.post(f"/api/projects/{pid}/takes/regroup")
    assert res.json()["groups"][0]["best_shot_id"] == second
    data = _put(client, pid, "best", shot_id=second, best=False)
    assert data["groups"][0]["best_by"] == "auto"

    data = _put(client, pid, "apart", shot_id=second)
    assert data["groups"] == [] and [s["shot_id"] for s in data["kept_apart"]] == [second]
    assert client.post(f"/api/projects/{pid}/takes/regroup").json()["groups"] == []
    data = _put(client, pid, "apart", shot_id=second, apart=False)
    assert len(data["groups"]) == 1 and data["kept_apart"] == []

    engine = make_engine(api_settings.db_path)
    with make_session_factory(engine)() as session:
        kinds = [e.kind for e in session.scalars(select(FeedbackEvent))]
    engine.dispose()
    assert kinds.count("take_best") == 2 and kinds.count("take_apart") == 2


def test_a_rejected_take_is_never_the_best(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    [g] = _takes(client, pid)["groups"]
    best = g["best_shot_id"]
    res = client.put(f"/api/shots/{best}/mark", json={"mark": "reject"})
    assert res.status_code == 200, res.text
    [g] = _takes(client, pid)["groups"]  # updated by the mark itself
    assert g["best_shot_id"] != best
    assert "rejected by you" in next(m for m in g["members"] if m["shot_id"] == best)["notes"]
    res = client.put(f"/api/projects/{pid}/takes/best", json={"shot_id": best})
    assert (
        res.status_code == 422
        and res.json()["code"] == "invalid_input"
        and "rejected" in res.json()["message"]
    )
    client.put(f"/api/shots/{best}/mark", json={"mark": "none"})
    [g] = _takes(client, pid)["groups"]  # clearing the reject ranks it again
    assert g["best_shot_id"] == best
    assert "rejected by you" not in g["members"][0]["notes"]


def test_errors_are_friendly(client: TestClient, pid: str, project: dict[str, Any]) -> None:
    res = client.put(f"/api/projects/{pid}/takes/best", json={"shot_id": project["shots"][3]})
    assert res.status_code == 404 and "not in a take group" in res.json()["message"]
    assert res.json()["code"] == "not_found"
    res = client.get("/api/projects/0123456789abcdef0123456789abcdef/takes")
    assert res.status_code == 404 and res.json()["code"] == "not_found"


def test_rough_cut_uses_one_take_per_group(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    [g] = _takes(client, pid)["groups"]
    res = client.post(
        f"/api/projects/{pid}/rough-cut", json={"brief": "30 second cut about the forest"}
    )
    assert res.status_code == 201, res.text
    cut = res.json()
    members = {m["shot_id"] for m in g["members"]}
    used = [i for i in cut["items"] if i["shot_id"] in members]
    assert len(used) == 1 and used[0]["shot_id"] == g["best_shot_id"]
    assert used[0]["take_group_id"] == g["id"]
    assert "Best take of take group 1 (2 takes" in used[0]["reason"]["summary"]
    other = next(a for a in cut["alternatives"] if a["shot_id"] in members)
    assert other["take_group_id"] == g["id"] and "Another take of take group 1" in other["summary"]
    assert cut["params"]["other_takes"] == 1
