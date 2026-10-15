"""Hybrid search: fusion, label matching, filters, search by picture, judgments, and the
evaluation metrics. Models are the test stand-ins of `embed_helpers` (picture vectors from a
frame's mean colour, text vectors from a hash), so only the plumbing is tested here; how good
the results are is measured by eval/search_eval.py."""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from cinemind.ai import embedder
from cinemind.core.config import Settings
from cinemind.core.search_config import SearchConfig
from cinemind.search import metrics, retrievers
from cinemind.search.hybrid import fuse
from cinemind.search.retrievers import Item
from cinemind.utils.pictures import picture_size
from search_helpers import processed_cuts, search

EVAL = Path(__file__).resolve().parents[2] / "eval"


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


# --- units ------------------------------------------------------------------------------------


def test_rrf_adds_one_over_k_plus_rank_from_every_list() -> None:
    lists = {
        "keyword": [Item("a", -3.0, 1.0), Item("b", -1.0, 2.0)],
        "visual": [Item("b", 0.3, 2.5), Item("c", 0.2, 0.0)],
    }
    out = fuse(lists, {"keyword": 1.0, "visual": 1.0}, k=60, limit=10)
    assert [f.shot_id for f in out] == ["b", "a", "c"]
    assert out[0].score == pytest.approx(1 / 62 + 1 / 61, abs=1e-6)
    assert out[0].parts["keyword"][1] == 2 and out[0].jump_s == 2.0  # a spoken word wins
    assert out[2].jump_s == 0.0
    # A weight of 0 turns a list off; weights scale what a list adds.
    assert [f.shot_id for f in fuse(lists, {"keyword": 0.0, "visual": 1.0}, 60, 10)] == ["b", "c"]
    heavy = fuse(lists, {"keyword": 1.0, "visual": 3.0}, 60, 10)  # c: 3/62 beats a: 1/61
    assert [f.shot_id for f in heavy] == ["b", "c", "a"]


def test_labels_match_whole_words_and_long_prefixes_only() -> None:
    words = ["indoor", "walking", "forest"]
    assert retrievers._matches("forest", words)  # pyright: ignore[reportPrivateUsage]
    assert retrievers._matches("walk", words)  # pyright: ignore[reportPrivateUsage]
    assert not retrievers._matches("in", words)  # pyright: ignore[reportPrivateUsage]
    assert not retrievers._matches("door", words)  # pyright: ignore[reportPrivateUsage]


def test_settings_are_checked() -> None:
    assert SearchConfig().rrf_k == 60
    for bad in ({"rrf_k": 0}, {"weights": {"magic": 1.0}}, {"visual_prompt": "no slot"}):
        with pytest.raises(ValueError):
            SearchConfig.model_validate(bad)


def test_metrics_follow_their_definitions() -> None:
    ranked = ["a", "x", "b", "y"]
    relevant = {"a", "b", "c"}
    assert metrics.precision_at(ranked, relevant, 2) == 0.5
    assert metrics.reciprocal_rank(["x", "a"], relevant) == 0.5
    assert metrics.reciprocal_rank(["x"], relevant) == 0.0
    ideal = 1 + 1 / np.log2(3) + 1 / np.log2(4)
    assert metrics.ndcg_at(ranked, relevant, 10) == pytest.approx((1 + 1 / np.log2(4)) / ideal)
    assert metrics.ndcg_at(ranked, set(), 10) == 0.0


# --- through the API --------------------------------------------------------------------------


def test_a_typed_query_fuses_all_four_lists_and_says_why(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    first = project["shots"][0]
    out = search(client, pid, q="forest")
    assert out["rrf_k"] == 60 and out["unavailable"] == {}
    assert out["lists"]["keyword"] == 1 and out["lists"]["labels"] == 4
    assert out["lists"]["visual"] == 4 and out["lists"]["text"] >= 1
    top = out["results"][0]
    assert top["shot_id"] == first and set(top["why"]) == {"keyword", "labels", "text", "visual"}
    keyword = top["why"]["keyword"]
    assert {"text": "forest", "match": True} in keyword["parts"] and keyword["rank"] == 1
    assert top["jump_s"] == pytest.approx(keyword["time_s"]) and 0.2 <= top["jump_s"] < 1.8
    assert top["why"]["labels"]["matched"] == ["tag: Forest"]
    assert top["keyframe_url"].startswith("/api/keyframes/") and top["relevant"] is None
    assert all(
        r["final"] >= s["final"] for r, s in zip(out["results"], out["results"][1:], strict=False)
    )

    # One list at a time (as the evaluation compares them); uncertain lines never match.
    only = search(client, pid, q="forest", use=["keyword"])
    assert [r["shot_id"] for r in only["results"]] == [first]
    assert search(client, pid, q="night", use=["keyword"])["results"] == []


def test_unrelated_transcript_lines_are_left_out_of_the_text_list(
    client: TestClient, pid: str, api_settings: Settings, project: dict[str, Any]
) -> None:
    api_settings.search = SearchConfig()  # the default floor of 0.25
    out = search(client, pid, q="forest")
    assert out["lists"]["text"] == 0 and "text" not in out["results"][0]["why"]


def test_filters_remove_shots_from_every_list(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    assert search(client, pid, q="forest", filters={"media_id": "0" * 32})["results"] == []
    talking = search(client, pid, q="forest", filters={"has_dialogue": True})["results"]
    assert [r["shot_id"] for r in talking] == [project["shots"][0]]
    good = search(client, pid, q="forest", filters={"min_quality": 0.0})["results"]
    assert len(good) == 4
    assert search(client, pid, q="forest", filters={"actor_id": "nobody"})["results"] == []
    bad = client.post(f"/api/projects/{pid}/search", json={"q": "x", "filters": {"min_quality": 2}})
    assert bad.status_code == 422


def test_more_like_this_and_search_by_picture(
    client: TestClient, pid: str, project: dict[str, Any], tmp_path: Path
) -> None:
    blue = project["shots"][3]
    like = search(client, pid, like_shot_id=blue)
    assert blue not in [r["shot_id"] for r in like["results"]]
    assert set(like["lists"]) == {"visual"} and like["query"] is None

    picture = np.zeros((90, 160, 3), dtype=np.uint8)
    picture[:] = (139, 0, 0)  # dark blue in BGR, like the last shot
    ok, png = cv2.imencode(".png", picture)
    assert ok
    res = client.post(f"/api/projects/{pid}/search/image", content=png.tobytes())
    assert res.status_code == 200, res.text
    assert res.json()["results"][0]["shot_id"] == blue
    assert (
        client.post(f"/api/projects/{pid}/search/image", content=b"not a picture").status_code
        == 422
    )
    assert (
        client.post(f"/api/projects/{pid}/search", json={"like_shot_id": "nope"}).status_code == 404
    )
    assert client.post(f"/api/projects/{pid}/search", json={"q": "  "}).status_code == 422


def test_judgments_are_kept_per_query_and_can_be_taken_back(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    first = project["shots"][0]
    url = f"/api/projects/{pid}/search/judgments"
    res = client.put(url, json={"query": "  Forest ", "shot_id": first, "relevant": True})
    assert res.status_code == 200 and res.json() == {
        "query": "forest", "shot_id": first, "relevant": True, "judged": 1
    }  # fmt: skip
    marks = {r["shot_id"]: r["relevant"] for r in search(client, pid, q="FOREST")["results"]}
    assert marks[first] is True and list(marks.values()).count(None) == 3
    assert (
        client.put(url, json={"query": "forest", "shot_id": first, "relevant": None}).json()[
            "judged"
        ]
        == 0
    )
    assert (
        client.put(url, json={"query": "forest", "shot_id": "nope", "relevant": True}).status_code
        == 404
    )


def test_a_missing_model_turns_its_list_off_and_says_so(
    client: TestClient, pid: str, api_settings: Settings, project: dict[str, Any]
) -> None:
    shutil.rmtree(embedder.choose_text(api_settings).path(api_settings.models_path))
    out = search(client, pid, q="forest")
    assert "text" not in out["lists"] and "models pull" in out["unavailable"]["text"]
    assert out["results"][0]["shot_id"] == project["shots"][0]


def test_the_evaluation_script_runs_on_judgments(
    client: TestClient, pid: str, api_settings: Settings, project: dict[str, Any]
) -> None:
    for shot, relevant in zip(project["shots"], (True, False, False, False), strict=True):
        body = {"query": "forest", "shot_id": shot, "relevant": relevant}
        client.put(f"/api/projects/{pid}/search/judgments", json=body)
    out = subprocess.run(  # noqa: S603 (the test's own interpreter and script)
        [sys.executable, str(EVAL / "search_eval.py"), "run", str(api_settings.data_dir),
         "--project", pid, "--judge", "user",
         "--lists", "keyword,labels"],  # the stand-in models are not in that process
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert out.returncode == 0, out.stderr
    assert "1 queries" in out.stdout
    rows = {line.split()[0]: line.split()[1:] for line in out.stdout.splitlines()[5:] if line}
    assert rows["keyword"][:2] == ["0.200", "0.100"]  # the one relevant shot is first: P@5 = 1/5
    assert rows["keyword"][3] == "1.000" and "hybrid" in rows


# --- after review -----------------------------------------------------------------------------


def test_equal_scores_share_a_rank() -> None:
    lists = {"labels": [Item("a", 1.0, 0), Item("b", 1.0, 0), Item("c", 0.5, 0)]}
    out = {f.shot_id: f for f in fuse(lists, {"labels": 1.0}, 60, 10)}
    assert out["a"].score == out["b"].score == pytest.approx(1 / 61, abs=1e-6)
    assert out["c"].parts["labels"][1] == 3  # competition ranking: 1, 1, 3


def test_picture_sizes_are_read_from_the_header_only() -> None:
    picture = np.zeros((30, 50, 3), dtype=np.uint8)
    for ext, kind in ((".png", "png"), (".jpg", "jpeg"), (".webp", "webp")):
        ok, data = cv2.imencode(ext, picture)
        assert ok and picture_size(data.tobytes()) == (kind, 50, 30)
    ok, tiff = cv2.imencode(".tiff", picture)
    assert ok and picture_size(tiff.tobytes()) is None
    assert picture_size(b"\xff\xd8\xff") is None


def test_a_time_maps_to_the_shot_it_falls_in(
    client: TestClient, pid: str, project: dict[str, Any], api_settings: Settings
) -> None:
    from cinemind.db.base import make_engine, make_session_factory

    with make_session_factory(make_engine(api_settings.db_path))() as session:
        shots = retrievers.Shots(session, pid)
        first, second, *_, last = project["shots"]
        assert shots.at(project["media"], -1.0) == first
        assert shots.at(project["media"], 2.0) == second  # a cut belongs to the shot it starts
        assert shots.at(project["media"], 99.0) == last
        assert shots.at("unknown", 1.0) is None


def test_a_search_takes_no_lock_and_a_stale_index_is_rebuilt_once(
    client: TestClient, pid: str, api_settings: Settings, project: dict[str, Any]
) -> None:
    import sqlite3

    from cinemind.db.analysis import VectorIndexRow
    from cinemind.db.base import make_engine, make_session_factory

    factory = make_session_factory(make_engine(api_settings.db_path))
    with factory() as session:  # make the picture index stale, as a worker adding rows would
        record = session.query(VectorIndexRow).filter_by(kind="keyframe").one()
        record.fingerprint = "stale"
        session.commit()
    search(client, pid, q="forest")
    with factory() as session:
        record = session.query(VectorIndexRow).filter_by(kind="keyframe").one()
        built, path = record.built_at, record.path
        assert record.fingerprint != "stale"  # the rebuild was committed, not rolled back
        assert (api_settings.project_dir(pid) / path).is_file()
    search(client, pid, q="night")
    with factory() as session:
        assert session.query(VectorIndexRow).filter_by(kind="keyframe").one().built_at == built
    # Nothing holds the write lock after a search: another writer gets it at once.
    other = sqlite3.connect(api_settings.db_path, timeout=0.1)
    other.execute("BEGIN IMMEDIATE")
    other.rollback()
    other.close()


def test_filters_find_shots_beyond_the_depth_of_each_list(
    client: TestClient, pid: str, api_settings: Settings, project: dict[str, Any]
) -> None:
    from cinemind.db.base import make_engine, make_session_factory
    from cinemind.db.models import Shot

    api_settings.search = SearchConfig(text_min_similarity=-1.0, depth=1)
    (top,) = search(client, pid, q="forest", use=["visual"])["results"]
    with make_session_factory(make_engine(api_settings.db_path))() as session:
        scenes = {
            s.id: s.scene_id for s in session.query(Shot).filter(Shot.id.in_(project["shots"]))
        }
    other_scene = next(scene for scene in scenes.values() if scene != scenes[top["shot_id"]])
    wanted = {shot for shot, scene in scenes.items() if scene == other_scene}
    kept = search(client, pid, q="forest", use=["visual"], filters={"scene_id": other_scene})
    # The project-wide top 1 is in another scene; the filter still finds this scene's best shot.
    assert len(kept["results"]) == 1 and kept["results"][0]["shot_id"] in wanted


def test_the_speech_filter_follows_the_users_review(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    first = project["shots"][0]
    review = {"shot_id": first, "name": "speech", "decision": "rejected"}
    assert client.put("/api/tags/review", json=review).status_code == 200
    assert search(client, pid, q="forest", filters={"has_dialogue": True})["results"] == []


def test_labels_skip_small_words_and_unnamed_people(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    assert search(client, pid, q="of a the", use=["labels"])["results"] == []
    assert search(client, pid, q="cuts", use=["labels"])["lists"]["labels"] == 4  # file name


def test_other_projects_and_bad_uploads_are_refused(
    client: TestClient, pid: str, project: dict[str, Any], api_settings: Settings
) -> None:
    other = client.post("/api/projects", json={"name": "other"}).json()["id"]
    shot = project["shots"][0]
    assert (
        client.post(f"/api/projects/{other}/search", json={"like_shot_id": shot}).status_code == 404
    )
    body = {"query": "forest", "shot_id": shot, "relevant": True}
    assert client.put(f"/api/projects/{other}/search/judgments", json=body).status_code == 404
    url = f"/api/projects/{pid}/search/image"
    assert client.post(f"/api/projects/{'0' * 32}/search/image", content=b"x").status_code == 404
    huge = client.post(url, content=b"x", headers={"content-length": str(16 * 1024 * 1024)})
    assert huge.status_code == 413
    # A small PNG that claims 10000 x 10000 pixels is refused before it is decoded.
    header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (10000).to_bytes(4, "big") * 2
    big = client.post(url, content=header + b"\x08\x02\x00\x00\x00")
    assert big.status_code == 413 and "megapixels" in big.json()["message"]
    _, tiff = cv2.imencode(".tiff", np.zeros((8, 8, 3), np.uint8))
    assert client.post(url, content=tiff.tobytes()).status_code == 422
    # Two marks in a row for the same result: the second replaces the first.
    url = f"/api/projects/{pid}/search/judgments"
    client.put(url, json=body)
    again = client.put(url, json={**body, "relevant": False}).json()
    assert again["judged"] == 1 and again["relevant"] is False


def test_vectors_of_another_model_are_reported_not_hidden(
    client: TestClient, pid: str, api_settings: Settings, project: dict[str, Any]
) -> None:
    api_settings.embed = api_settings.embed.model_copy(update={"visual_model": "siglip-base"})
    out = search(client, pid, q="forest")
    assert "visual" not in out["lists"] and "siglip-base" in out["unavailable"]["visual"]
    like = client.post(f"/api/projects/{pid}/search", json={"like_shot_id": project["shots"][0]})
    assert like.status_code == 200 and like.json()["results"] == []
    assert "Process all" in like.json()["unavailable"]["visual"]
