"""Ranking after fusion: signals, weights, the duplicate penalty, and selects / rejects / stars.
Uses the processed `cuts.mp4` project of test_search (four shots, stand-in models)."""

from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from cinemind.core.config import Settings
from cinemind.core.ranking_config import DEFAULT_WEIGHTS, RankingConfig
from cinemind.db.base import make_engine, make_session_factory
from cinemind.db.people import FeedbackEvent
from cinemind.search import ranking
from cinemind.search.hybrid import Fused
from cinemind.search.ranking import rank
from cinemind.search.retrievers import Item
from search_helpers import processed_cuts, search


@pytest.fixture
def project(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    cut_footage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    return processed_cuts(client, pid, api_settings, cut_footage, tmp_path, monkeypatch)


ALL_OFF = {"relevance": 0, "quality": 0, "selection": 0, "person": 0, "scene": 0, "duplicate": 0}


def _order(out: dict[str, Any]) -> list[str]:
    return [r["shot_id"] for r in out["results"]]


def test_every_result_explains_its_final_score(
    client: TestClient,
    pid: str,
    project: dict[str, Any],
) -> None:
    out = search(client, pid, q="forest")
    assert out["ranking_weights"]["relevance"] == 1.0 and out["ranking_weights"]["duplicate"] == 0.3
    for result in out["results"]:
        parts = result["breakdown"]
        assert set(parts) == {"relevance", "quality", "selection", "person", "scene", "duplicate"}
        assert result["final"] == pytest.approx(
            sum(p["contribution"] for p in parts.values()), abs=1e-3
        )
        assert parts["duplicate"]["contribution"] <= 0
    first = out["results"][0]
    assert first["breakdown"]["relevance"]["value"] == 1.0 and first["duplicate_of"] is None
    finals = [r["final"] for r in out["results"]]
    assert finals == sorted(finals, reverse=True)  # MMR: a later place never scores higher
    # Only near-identical pictures count as duplicates (cosine above the threshold).
    for result in out["results"]:
        dup = result["breakdown"]["duplicate"]
        assert (dup["value"] > 0) == (result["duplicate_of"] is not None)


def test_changing_weights_changes_the_order_deterministically(
    client: TestClient,
    pid: str,
    project: dict[str, Any],
) -> None:
    by_quality = {**ALL_OFF, "quality": 1.0}
    one = search(client, pid, q="forest", weights=by_quality)
    assert _order(one) == _order(search(client, pid, q="forest", weights=by_quality))
    quality = [r["breakdown"]["quality"]["value"] for r in one["results"]]
    assert quality == sorted(quality, reverse=True)
    by_relevance = search(client, pid, q="forest", weights={**ALL_OFF, "relevance": 1.0})
    fused = [r["score"] for r in by_relevance["results"]]
    assert fused == sorted(fused, reverse=True)  # relevance alone keeps the fused order
    assert by_relevance["ranking_weights"]["quality"] == 0
    bad = client.post(f"/api/projects/{pid}/search", json={"q": "x", "weights": {"magic": 1}})
    assert bad.status_code == 422
    assert (
        client.post(
            f"/api/projects/{pid}/search", json={"q": "x", "weights": {"quality": 9}}
        ).status_code
        == 422
    )


def test_selects_rise_rejects_disappear_and_marks_are_logged(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    project: dict[str, Any],
) -> None:
    first, second, third, fourth = project["shots"]

    def mark(shot: str, **body: Any) -> Any:
        return client.put(f"/api/shots/{shot}/mark", json=body)

    assert mark(fourth, mark="select", stars=4).json() == {
        "shot_id": fourth,
        "mark": "select",
        "stars": 4,
    }
    assert mark(third, stars=3).json() == {"shot_id": third, "mark": None, "stars": 3}
    assert mark(second, mark="reject").json()["mark"] == "reject"
    picks = search(client, pid, q="forest", weights={**ALL_OFF, "selection": 1.0})
    assert _order(picks)[:2] == [fourth, third]  # select = 1, three stars = 0.6
    assert picks["results"][0]["mark"] == "select" and picks["results"][1]["stars"] == 3
    assert second not in _order(picks)  # rejected: left out
    shown = search(client, pid, q="forest", filters={"include_rejected": True})
    assert second in _order(shown)
    assert _order(search(client, pid, q="forest", filters={"selects_only": True})) == [fourth]
    scenes = client.get(f"/api/projects/{pid}/scenes").json()
    marks = {s["shot_id"]: (s["mark"], s["stars"]) for sc in scenes["scenes"] for s in sc["shots"]}
    assert marks[fourth] == ("select", 4) and marks[first] == (None, 0)

    # Each part is kept unless sent; nothing left = no mark at all; a repeat logs nothing.
    assert mark(fourth, stars=5).json() == {"shot_id": fourth, "mark": "select", "stars": 5}
    assert mark(fourth, mark="none").json() == {"shot_id": fourth, "mark": None, "stars": 5}
    assert mark(fourth, stars=0).json() == {"shot_id": fourth, "mark": None, "stars": 0}
    assert mark(fourth, stars=0).json()["stars"] == 0
    assert mark(first, mark="select", stars=6).status_code == 422
    assert mark(first, mark="maybe").status_code == 422
    assert mark("nope", mark="select").status_code == 404
    with make_session_factory(make_engine(api_settings.db_path))() as session:
        events = session.query(FeedbackEvent).filter_by(kind="shot_mark").all()
    assert len(events) == 6 and events[-1].payload["before"] == {"mark": None, "stars": 5}


def test_named_people_and_scenes_in_the_query_count(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    project: dict[str, Any],
) -> None:
    a, b, c, _ = project["shots"]
    fused = [
        Fused(a, 0.03, {"labels": (Item(a, 1, 0.0, matched=["actor: Asha"]), 1, 0.016)}),
        Fused(b, 0.02, {"labels": (Item(b, 1, 0.0, matched=["scene: Picnic"]), 1, 0.016)}),
        Fused(c, 0.01, {}),
    ]
    with make_session_factory(make_engine(api_settings.db_path))() as session:
        out = rank(session, api_settings, pid, fused, {**ALL_OFF, "person": 1.0, "scene": 0.5})
    assert [r.fused.shot_id for r in out] == [a, b, c]
    assert out[0].breakdown["person"] == (1.0, 1.0, 1.0) and out[1].breakdown["scene"][2] == 0.5
    assert out[2].final == 0.0


def test_one_ranking_setting_leaves_the_other_defaults_alone() -> None:
    cfg = RankingConfig.model_validate({"weights": {"quality": 0.5}})
    assert cfg.weights == {**DEFAULT_WEIGHTS, "quality": 0.5}
    for bad in ({"weights": {"speed": 1}}, {"weights": {"quality": 6}}, {"duplicate_threshold": 1}):
        with pytest.raises(ValueError):
            RankingConfig.model_validate(bad)


def _fused(ids: list[str], scores: list[float]) -> list[Fused]:
    return [Fused(i, s, {}) for i, s in zip(ids, scores, strict=True)]


def test_edge_cases_of_the_scaling_and_the_order(
    client: TestClient, pid: str, api_settings: Settings, project: dict[str, Any]
) -> None:
    a, b, c, d = sorted(project["shots"])
    only_relevance = {**ALL_OFF, "relevance": 1.0}
    with make_session_factory(make_engine(api_settings.db_path))() as session:
        (single,) = rank(session, api_settings, pid, _fused([c], [0.01]), only_relevance)
        assert single.breakdown["relevance"][0] == 1.0
        tied = rank(session, api_settings, pid, _fused([d, b, c, a], [0.02] * 4), only_relevance)
        assert [r.fused.shot_id for r in tied] == [a, b, c, d]  # equal scores: smaller id first
        # Near-equal fused scores keep their order (nothing is rounded before comparing).
        near = _fused([d, a], [0.0164 + 1e-7, 0.0164])
        out = rank(session, api_settings, pid, near + _fused([b], [0.0100]), only_relevance)
        assert [r.fused.shot_id for r in out] == [d, a, b]


def test_the_duplicate_weight_and_threshold_change_the_order(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b, c, _ = sorted(project["shots"])
    same, other = np.array([1.0, 0.0]), np.array([0.6, 0.8])  # a and b look identical

    def vectors(*_args: object) -> dict[str, Any]:
        return {a: same, b: same, c: other}

    monkeypatch.setattr(ranking, "_mean_vectors", vectors)
    fused = _fused([a, b, c], [0.030, 0.029, 0.028])
    weights = {**ALL_OFF, "relevance": 1.0}
    with make_session_factory(make_engine(api_settings.db_path))() as session:
        plain = rank(session, api_settings, pid, fused, weights)
        spread = rank(session, api_settings, pid, fused, {**weights, "duplicate": 1.0})
        api_settings.ranking = RankingConfig(duplicate_threshold=0.5)
        lower = rank(session, api_settings, pid, fused, {**weights, "duplicate": 1.0})
    assert [r.fused.shot_id for r in plain] == [a, b, c]
    assert [r.fused.shot_id for r in spread] == [a, c, b]  # the look-alike moves down
    assert spread[2].duplicate_of == a and spread[2].breakdown["duplicate"] == (1.0, 1.0, -1.0)
    assert spread[1].duplicate_of is None  # cosine 0.6 is below the 0.85 threshold
    assert lower[1].fused.shot_id == c and lower[1].duplicate_of == a  # 0.6 counts above 0.5
    assert lower[1].breakdown["duplicate"][0] == pytest.approx(0.2)  # (0.6 - 0.5) / (1 - 0.5)
    # Search by a shot finds look-alikes by design: no duplicate penalty there.
    like = search(client, pid, like_shot_id=project["shots"][0], weights={"duplicate": 5.0})
    assert all(r["breakdown"]["duplicate"]["contribution"] == 0 for r in like["results"])


def test_rejected_shots_leave_picture_searches_too(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    first, second, _, blue = project["shots"]
    client.put(f"/api/shots/{blue}/mark", json={"mark": "reject"})
    client.put(f"/api/shots/{second}/mark", json={"mark": "select"})
    like = search(client, pid, like_shot_id=first)
    assert blue not in [r["shot_id"] for r in like["results"]]
    picture = np.zeros((90, 160, 3), dtype=np.uint8)
    picture[:] = (139, 0, 0)
    _, png = cv2.imencode(".png", picture)
    url = f"/api/projects/{pid}/search/image"
    hidden = client.post(url, content=png.tobytes()).json()
    assert blue not in [r["shot_id"] for r in hidden["results"]]
    params = {"include_rejected": "true", "weights": '{"selection": 0}'}  # the select would win
    shown = client.post(url, params=params, content=png.tobytes()).json()
    assert shown["results"][0]["shot_id"] == blue and shown["results"][0]["mark"] == "reject"
    assert shown["results"][0]["breakdown"]["selection"]["value"] == 0  # a reject earns nothing
    picks = client.post(url, params={"selects_only": "true"}, content=png.tobytes()).json()
    assert [r["shot_id"] for r in picks["results"]] == [second]
    weighted = client.post(url, params={"weights": '{"quality": 2}'}, content=png.tobytes()).json()
    assert (
        weighted["ranking_weights"]["quality"] == 2
        and weighted["ranking_defaults"]["quality"] == 0.2
    )
    assert (
        client.post(url, params={"weights": '{"speed": 1}'}, content=png.tobytes()).status_code
        == 422
    )
    both = search(client, pid, q="forest", filters={"selects_only": True, "include_rejected": True})
    assert [r["shot_id"] for r in both["results"]] == [second]
