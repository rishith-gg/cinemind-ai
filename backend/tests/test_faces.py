# numpy's norm and load are untyped for these arrays.
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from cinemind.ai import face_cluster
from cinemind.ai import faces as face_engine
from cinemind.ai.faces import Found, turn_of
from cinemind.cli import app as cli_app
from cinemind.core import face_config
from cinemind.core.config import Settings
from cinemind.core.doctor import check_face_models
from cinemind.core.face_config import FaceConfig
from cinemind.pipeline import face_scan
from conftest import CUTS_S
from face_helpers import (
    FakeFaces,
    actors_of,
    engine_factory,
    faces_of,
    import_clip,
    install_models,
    person,
)
from helpers import drain

# --- settings, geometry, grouping -------------------------------------------------------------


def test_settings_reject_values_out_of_range() -> None:
    assert FaceConfig(sample_fps=1, cluster_method="hdbscan").cluster_method == "hdbscan"
    bad: list[dict[str, Any]] = [
        {"sample_fps": 0},
        {"min_score": 1.5},
        {"cluster_distance": 0},
        {"min_size_px": 2},
        {"track_max_gap_s": 0},
    ]
    for values in bad:
        with pytest.raises(ValueError, match="faces"):
            FaceConfig(**values)
    with pytest.raises(ValueError):
        FaceConfig(cluster_method="kmeans")  # pyright: ignore[reportArgumentType]


def test_turn_is_zero_for_a_frontal_face_and_grows_towards_profile() -> None:
    frontal = np.array([40, 50, 80, 50, 60, 70, 45, 90, 75, 90], dtype=np.float32)
    turned = np.array([40, 50, 60, 50, 62, 70, 45, 90, 60, 90], dtype=np.float32)
    tilted = np.array([40, 40, 80, 80, 50, 70, 0, 0, 0, 0], dtype=np.float32)  # head rolled 45°
    assert turn_of(frontal) == pytest.approx(0.0)
    assert turn_of(turned) == pytest.approx(0.6)
    assert turn_of(tilted) == pytest.approx(0.0)  # a rolled head is still frontal
    assert turn_of(np.zeros(10, dtype=np.float32)) > 1  # no eye distance: never usable


def test_overlap_of_boxes() -> None:
    assert face_scan.overlap((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert face_scan.overlap((0, 0, 10, 10), (5, 0, 10, 10)) == pytest.approx(1 / 3)
    assert face_scan.overlap((0, 0, 10, 10), (20, 20, 5, 5)) == 0.0


@pytest.mark.parametrize("method", ["agglomerative", "hdbscan"])
def test_grouping_respects_apart_and_together(method: face_cluster.Method) -> None:
    rng = np.random.default_rng(7)
    centres = face_cluster.unit(rng.normal(size=(3, 128)))
    rows = [centres[k] + 0.04 * rng.normal(size=128) for k in range(3) for _ in range(5)]
    vectors = face_cluster.unit(np.stack(rows))
    plain = face_cluster.cluster(vectors, 0.5, method)
    assert plain == [0] * 5 + [1] * 5 + [2] * 5
    apart = face_cluster.cluster(vectors, 0.5, method, apart=[(0, 1)])
    assert apart[0] != apart[1] and len(set(apart[5:])) == 2
    together = face_cluster.cluster(vectors, 0.5, method, together=[[0, 5]])
    assert together[0] == together[5]
    # The user wins when both are asked for the same pair.
    both = face_cluster.cluster(vectors, 0.5, method, apart=[(0, 5)], together=[[0, 5]])
    assert both[0] == both[5]
    assert face_cluster.cluster(vectors[:0], 0.5, method) == []
    assert face_cluster.cluster(vectors[:1], 0.5, method) == [0]
    near = face_cluster.centroid_similarity(vectors, plain)
    assert len(near) == 15 and all(0.8 < value <= 1.0 for value in near)


def test_apart_holds_even_for_identical_vectors() -> None:
    vectors = np.stack([person(0), person(0), person(0, 0.05)])
    for method in ("agglomerative", "hdbscan"):
        labels = face_cluster.cluster(vectors, 0.6, method, apart=[(0, 1)])
        assert labels[0] != labels[1]


# --- tracking ---------------------------------------------------------------------------------


def _found(left: float, vector: Any) -> Found:
    return Found((left, 10.0, 50.0, 50.0), 0.9, 50.0, 0.0, 80.0, None, vector)


def test_tracking_rule() -> None:
    cfg = FaceConfig()
    track = face_scan._Track(0, person(0), (100.0, 10.0, 50.0, 50.0), 0)  # pyright: ignore[reportPrivateUsage]
    other = face_scan._Track(0, person(1), (300.0, 10.0, 50.0, 50.0), 0)  # pyright: ignore[reportPrivateUsage]
    match = face_scan.match
    # Similar enough: continues wherever the box is. Two faces never share one track.
    same_twice = [_found(400, person(0, 0.2)), _found(100, person(0))]
    assert match([track, other], same_twice, cfg) == {1: 0}
    assert match([track, other], [_found(300, person(1)), _found(100, person(0))], cfg) == {
        0: 1,
        1: 0,
    }
    # Half as similar (a turned head): only while the box still overlaps the last one.
    mixed: Any = person(0) * 0.25 + person(5)
    weak: Any = mixed / np.linalg.norm(mixed)
    assert cfg.track_similarity / 2 < float(weak @ person(0)) < cfg.track_similarity
    assert match([track], [_found(105, weak)], cfg) == {0: 0}
    assert match([track], [_found(300, weak)], cfg) == {}
    assert match([track], [_found(100, person(7))], cfg) == {}  # someone else in the same place
    assert match([], [_found(100, person(0))], cfg) == {}


def test_matching_takes_the_most_similar_pairs_not_the_most_pairs() -> None:
    cfg = FaceConfig()
    track = face_scan._Track(0, person(0), (100.0, 10.0, 50.0, 50.0), 0)  # pyright: ignore[reportPrivateUsage]
    other = face_scan._Track(0, person(1), (300.0, 10.0, 50.0, 50.0), 0)  # pyright: ignore[reportPrivateUsage]
    # Face 0 is clearly person 0 (0.9) and loosely like person 1 (0.4); face 1 is only loosely
    # like person 0. Linking both would put the clear face on the wrong track.
    clear: Any = 0.9 * person(0) + 0.4 * person(1) + np.sqrt(0.03) * person(2)
    loose: Any = 0.4 * person(0) + np.sqrt(0.84) * person(3)
    assert face_scan.match([track, other], [_found(100, clear), _found(600, loose)], cfg) == {0: 0}


def test_scan_refuses_a_proxy_that_ends_early(cut_footage: Path, tmp_path: Path) -> None:
    from fractions import Fraction

    from cinemind.core.errors import UnreadableMediaError

    engine: Any = FakeFaces([])
    with pytest.raises(UnreadableMediaError, match="up to frame 200 of 400"):
        face_scan.scan(
            cut_footage / "cuts.mp4", Fraction(25), [(0, 400)], FaceConfig(), engine,
            tmp_path / "faces", lambda _f: None, lambda: None,
        )  # fmt: skip


def test_scan_cuts_tracks_at_shot_boundaries(cut_footage: Path, tmp_path: Path) -> None:
    from fractions import Fraction

    engine: Any = FakeFaces([(0.1, person(0)), (0.6, person(1))])
    shots = [(0, 50), (50, 88), (88, 150), (150, 200)]
    assert [round(s * 25) for s in CUTS_S] == [50, 88, 150]
    seen: list[float] = []
    out = tmp_path / "faces"
    result = face_scan.scan(
        cut_footage / "cuts.mp4",
        Fraction(25),
        shots,
        FaceConfig(),
        engine,
        out,
        seen.append,
        lambda: None,
    )
    assert result["step_frames"] == 12 and result["frames_sampled"] == 17 == engine.frames
    assert result["faces_detected"] == 17 * 3 and result["max_in_frame"] == 3
    assert result["rejected"] == {"low_score": 17, "small": 0, "turned": 0, "blurry": 0}
    # Two people in four shots: eight tracks, none crossing a cut.
    assert [t["shot"] for t in result["tracks"]] == [0, 0, 1, 1, 2, 2, 3, 3]
    assert sum(t["faces"] for t in result["tracks"]) == len(result["faces"]) == 34
    vectors: Any = np.load(out / face_scan.TRACKS_FILE)
    assert vectors.shape == (8, 128) and np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    assert float(vectors[0] @ vectors[2]) == pytest.approx(1.0)  # person 0 in shots 0 and 1
    for track in result["tracks"]:
        assert (out / track["crop"]).read_bytes()[:2] == b"\xff\xd8"  # a JPEG
    assert all(0 <= value <= 1 for row in result["faces"] for value in row[1:5])
    assert seen[-1] == 1.0 and not out.with_name("faces.partial").exists()


# --- the stage, through the API ---------------------------------------------------------------


def test_without_models_clips_still_process_and_say_how_to_fix_it(
    client: TestClient, pid: str, api_settings: Settings, footage: Path
) -> None:
    media_id = import_clip(client, pid, footage / "a_h264.mp4")
    drain(api_settings)
    assert client.get(f"/api/media/{media_id}").json()["job"]["status"] == "succeeded"
    faces = faces_of(client, media_id)
    assert faces["status"] == "model_missing" and "cinemind models pull" in faces["message"]
    overview = actors_of(client, pid)
    assert overview["actors"] == [] and overview["scans"] == {"model_missing": 1}
    assert "cinemind models pull" in overview["message"]
    check = check_face_models(api_settings)
    assert (check.status, check.required, check.fix) == (
        "warn",
        False,
        "uv run cinemind models pull",
    )


def test_faces_tracks_and_what_produced_them(
    client: TestClient, pid: str, api_settings: Settings, footage: Path, fake: FakeFaces
) -> None:
    media_id = import_clip(client, pid, footage / "a_h264.mp4")
    audio_id = import_clip(client, pid, footage / "d_audio.wav")
    drain(api_settings)
    assert check_face_models(api_settings).status == "ok"
    faces = faces_of(client, media_id)
    assert (faces["status"], faces["message"]) == ("done", None)
    assert faces["frames_sampled"] == 5 == fake.frames  # 2 s at 25 fps, every 12th frame
    assert (faces["faces_detected"], faces["faces_used"], faces["max_in_frame"]) == (15, 10, 3)
    details = faces["details"]
    assert details["engine"] == "yunet-sface" and details["rejected"]["low_score"] == 5
    assert details["revisions"] == [spec.revision for spec in face_config.FACE_MODELS]
    assert (
        details["settings"]["sample_fps"] == 2.0 and "cluster_distance" not in details["settings"]
    )
    assert [(t["face_count"], t["state"]) for t in faces["tracks"]] == [(5, "auto"), (5, "auto")]
    track = faces["tracks"][0]
    assert track["start_s"] == 0.0 and track["end_s"] == pytest.approx(2.0)
    assert track["actor_name"] in ("Actor 001", "Actor 002")
    assert track["assignment"]["how"] == "similar faces"
    assert track["assignment"]["cluster_distance"] == api_settings.faces.cluster_distance
    image = client.get(track["crop_url"])
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    assert client.get("/api/face-tracks/nope/image").status_code == 404
    no_picture = faces_of(client, audio_id)
    assert (no_picture["status"], no_picture["tracks"]) == ("no_video", [])
    assert "no picture" in no_picture["message"]

    # Processing again reads the cache and keeps the tracks and their actors.
    before = [(t["id"], t["actor_id"]) for t in faces["tracks"]]
    client.post(f"/api/media/{media_id}/process")
    drain(api_settings)
    assert fake.frames == 5
    assert [(t["id"], t["actor_id"]) for t in faces_of(client, media_id)["tracks"]] == before


def test_a_clip_without_faces_and_models_arriving_later(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    footage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_id = import_clip(client, pid, footage / "a_h264.mp4")
    drain(api_settings)
    assert faces_of(client, media_id)["status"] == "model_missing"
    install_models(api_settings)
    monkeypatch.setattr(face_engine, "FaceEngine", engine_factory(FakeFaces([])))
    client.post(f"/api/media/{media_id}/process")
    drain(api_settings)
    faces = faces_of(client, media_id)
    assert faces["status"] == "no_faces" and "No usable face" in faces["message"]
    assert faces["faces_detected"] == 5 and faces["faces_used"] == 0
    assert actors_of(client, pid)["scans"] == {"no_faces": 1}


def _people(settings: Settings, media_id: str) -> list[int]:
    """Which made-up person each stored track vector is."""
    from sqlalchemy import select

    from cinemind.db.base import make_engine, make_session_factory
    from cinemind.db.people import FaceTrack

    with make_session_factory(make_engine(settings.db_path))() as session:
        query = select(FaceTrack).where(FaceTrack.media_id == media_id).order_by(FaceTrack.index)
        vectors = [np.frombuffer(t.embedding, dtype=np.float32) for t in session.scalars(query)]
    return [int(np.argmax(vector)) for vector in vectors]


def test_going_back_to_earlier_settings_never_mixes_two_scans(
    client: TestClient, pid: str, api_settings: Settings, footage: Path, fake: FakeFaces
) -> None:
    media_id = import_clip(client, pid, footage / "a_h264.mp4")
    drain(api_settings)
    assert _people(api_settings, media_id) == [0, 1]
    folder = api_settings.project_dir(pid) / "faces" / media_id
    (first,) = [child.name for child in folder.iterdir()]

    fake.people = [(0.1, person(5)), (0.4, person(6)), (0.7, person(7))]
    api_settings.faces = FaceConfig(sample_fps=5.0)
    client.post(f"/api/media/{media_id}/process")
    drain(api_settings)
    assert _people(api_settings, media_id) == [5, 6, 7]
    assert [child.name for child in folder.iterdir()] != [first]  # the old scan's files are gone

    # Back to the first settings: its files are gone, so the clip is scanned again (the stand-in
    # now shows other people) instead of pairing the cached result with the other scan's vectors.
    api_settings.faces = FaceConfig()
    scanned = fake.frames
    client.post(f"/api/media/{media_id}/process")
    drain(api_settings)
    assert fake.frames > scanned and _people(api_settings, media_id) == [5, 6, 7]
    assert [t["face_count"] for t in faces_of(client, media_id)["tracks"]] == [5, 5, 5]


def test_missing_models_after_a_good_scan_keep_what_was_found(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    footage: Path,
    fake: FakeFaces,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_id = import_clip(client, pid, footage / "a_h264.mp4")
    drain(api_settings)
    before = [(t["id"], t["actor_id"]) for t in faces_of(client, media_id)["tracks"]]
    for spec in face_config.FACE_MODELS:
        spec.path(api_settings.models_path).unlink()
    monkeypatch.undo()  # the real engine, which now finds no model files
    api_settings.faces = FaceConfig(sample_fps=5.0)
    client.post(f"/api/media/{media_id}/process")
    drain(api_settings)
    after = faces_of(client, media_id)
    assert after["status"] == "model_missing" and "cinemind models pull" in after["message"]
    assert [(t["id"], t["actor_id"]) for t in after["tracks"]] == before and len(before) == 2
    assert len(actors_of(client, pid)["actors"]) == 2


# --- models -----------------------------------------------------------------------------------


def test_models_list_names_the_face_models(
    api_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cinemind.cli.get_settings", lambda: api_settings)
    listing = CliRunner().invoke(cli_app, ["models", "list"])
    assert listing.exit_code == 0 and "face_detection_yunet" in listing.output
    assert "not downloaded" in listing.output
    install_models(api_settings)
    pulled = CliRunner().invoke(cli_app, ["models", "pull", "faces"])
    assert pulled.exit_code == 0 and "already downloaded" in pulled.output
    unknown = CliRunner().invoke(cli_app, ["models", "pull", "huge"])
    assert unknown.exit_code == 2 and "faces" in unknown.output


def test_pull_rejects_a_download_with_the_wrong_checksum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def download(_repo: str, filename: str, revision: str, local_dir: str) -> str:
        target = Path(local_dir) / filename
        target.write_bytes(b"not the model")
        return str(target)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    with pytest.raises(face_engine.ModelMissingError, match="checksum"):
        face_engine.pull(tmp_path)
    assert not face_config.models_ready(tmp_path)
    assert list((tmp_path / "faces").iterdir()) == []
    with pytest.raises(face_engine.ModelMissingError, match="not downloaded"):
        face_engine.FaceEngine(tmp_path)
