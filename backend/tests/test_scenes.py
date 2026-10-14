"""Scenes: grouping neighbouring shots, the user's edits, and what survives regrouping."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cinemind.core.config import Settings
from cinemind.db.base import make_engine, make_session_factory
from cinemind.db.people import FeedbackEvent
from embed_helpers import FakeEmbedder, use_fake_embedder
from helpers import drain, import_one


@pytest.fixture
def scene_settings(api_settings: Settings, cut_footage: Path) -> Settings:
    api_settings.media_roots = [*api_settings.media_roots, cut_footage]
    return api_settings


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, scene_settings: Settings) -> FakeEmbedder:
    return use_fake_embedder(monkeypatch, scene_settings)


def _import_all(client: TestClient, pid: str, settings: Settings, *paths: Path) -> list[str]:
    ids = [str(import_one(client, pid, p)["media"]["id"]) for p in paths]  # type: ignore[index]
    drain(settings)
    return ids


def _scenes(client: TestClient, pid: str) -> dict[str, Any]:
    res = client.get(f"/api/projects/{pid}/scenes")
    assert res.status_code == 200, res.text
    return res.json()


def _shots(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [shot for scene in data["scenes"] for shot in scene["shots"]]


def test_shots_are_grouped_after_the_import_with_the_numbers_behind_it(
    client: TestClient,
    pid: str,
    footage: Path,
    cut_footage: Path,
    scene_settings: Settings,
    fake: FakeEmbedder,
) -> None:
    _import_all(client, pid, scene_settings, footage / "a_h264.mp4", cut_footage / "cuts.mp4")
    data = _scenes(client, pid)
    shots = _shots(data)
    assert len(shots) == 5  # one in a_h264, four in cuts.mp4 (file-name order)
    assert [s["filename"] for s in shots] == ["a_h264.mp4"] + ["cuts.mp4"] * 4
    assert shots[0]["decision"] == "first shot" and shots[0]["combined"] is None
    threshold = data["settings"]["join_similarity"]
    for scene in data["scenes"]:
        for i, shot in enumerate(scene["shots"]):
            if shot["combined"] is None:
                continue
            assert (shot["combined"] >= threshold) == (i > 0)  # joined iff similar enough
            assert shot["visual"] is not None and shot["color"] is not None
    assert data["details"]["shots"] == 5 and data["details"]["model"]
    assert [s["index"] for s in data["scenes"]] == list(range(len(data["scenes"])))
    assert all(s["name"] == f"Scene {s['index'] + 1:03d}" for s in data["scenes"])
    # the same testsrc2 picture at the start of both clips is one scene
    assert data["scenes"][0]["shots"][1]["filename"] == "cuts.mp4"


def test_split_join_and_auto_are_kept_through_regrouping(
    client: TestClient, pid: str, cut_footage: Path, scene_settings: Settings, fake: FakeEmbedder
) -> None:
    _import_all(client, pid, scene_settings, cut_footage / "cuts.mp4")
    shots = _shots(_scenes(client, pid))
    second, third = shots[1]["shot_id"], shots[2]["shot_id"]

    def put(shot_id: str, decision: str) -> dict[str, Any]:
        res = client.put(
            f"/api/projects/{pid}/scenes/boundaries",
            json={"shot_id": shot_id, "decision": decision},
        )
        assert res.status_code == 200, res.text
        return res.json()

    data = put(third, "split")
    starts = [scene["shots"][0]["shot_id"] for scene in data["scenes"]]
    assert third in starts
    edited = next(s for s in _shots(data) if s["shot_id"] == third)
    assert edited["decision"] == "split by you" and edited["edit"] == "split"
    data = put(second, "join")
    assert next(s for s in _shots(data) if s["shot_id"] == second)["decision"] == "joined by you"
    data = client.post(f"/api/projects/{pid}/scenes/regroup").json()  # edits outrank similarity
    assert next(s for s in _shots(data) if s["shot_id"] == third)["edit"] == "split"
    data = put(third, "auto")
    assert next(s for s in _shots(data) if s["shot_id"] == third)["edit"] is None
    first = shots[0]["shot_id"]
    res = client.put(
        f"/api/projects/{pid}/scenes/boundaries", json={"shot_id": first, "decision": "join"}
    )
    assert res.status_code == 422 and "first shot" in res.json()["message"]
    factory = make_session_factory(make_engine(scene_settings.db_path))
    with factory() as s:
        kinds = [e.kind for e in s.scalars(select(FeedbackEvent))]
        assert kinds.count("scene_boundary") == 3


def test_a_scene_name_follows_its_shots(
    client: TestClient, pid: str, cut_footage: Path, scene_settings: Settings, fake: FakeEmbedder
) -> None:
    media = _import_all(client, pid, scene_settings, cut_footage / "cuts.mp4")[0]
    scene = _scenes(client, pid)["scenes"][0]
    res = client.patch(f"/api/scenes/{scene['id']}", json={"name": "  Walk   home "})
    assert res.status_code == 200
    renamed = res.json()["scenes"][0]
    assert renamed["name"] == "Walk home" and renamed["named"] is True
    client.post(f"/api/media/{media}/process")
    drain(scene_settings)  # processed again and regrouped: the name stays
    assert _scenes(client, pid)["scenes"][0]["name"] == "Walk home"
    back = client.patch(f"/api/scenes/{scene['id']}", json={"name": ""}).json()
    assert back["scenes"][0]["name"] == "Scene 001" and back["scenes"][0]["named"] is False
    assert client.patch("/api/scenes/nope", json={"name": "x"}).status_code == 404


def test_without_the_picture_model_every_shot_is_its_own_scene(
    client: TestClient, pid: str, cut_footage: Path, scene_settings: Settings
) -> None:
    _import_all(client, pid, scene_settings, cut_footage / "cuts.mp4")
    data = _scenes(client, pid)
    assert data["model_missing"] is True and "models pull" in data["message"]
    shots = _shots(data)
    assert len(data["scenes"]) == len(shots)
    assert all(s["decision"] in ("first shot", "no picture vectors to compare") for s in shots)


def test_removing_a_clip_regroups_the_scenes(
    client: TestClient,
    pid: str,
    footage: Path,
    cut_footage: Path,
    scene_settings: Settings,
    fake: FakeEmbedder,
) -> None:
    first, _ = _import_all(
        client, pid, scene_settings, footage / "a_h264.mp4", cut_footage / "cuts.mp4"
    )
    assert client.delete(f"/api/media/{first}").status_code == 204
    shots = _shots(_scenes(client, pid))
    assert len(shots) == 4 and shots[0]["decision"] == "first shot"
