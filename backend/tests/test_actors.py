# numpy's norm and load are untyped for these arrays.
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from cinemind.core.config import Settings
from cinemind.core.face_config import FaceConfig
from cinemind.db.people import FacePin, FaceTrack, FeedbackEvent
from cinemind.jobs import queue
from cinemind.jobs.runner import run_job
from cinemind.jobs.worker import _after_ingest  # pyright: ignore[reportPrivateUsage]
from cinemind.pipeline import actors
from face_helpers import FakeFaces, actors_of, detail_of, faces_of, import_clip, person, two_clips
from helpers import drain

# --- actors -----------------------------------------------------------------------------------


def test_people_are_grouped_across_clips_and_never_within_a_frame(
    client: TestClient, pid: str, api_settings: Settings, footage: Path, fake: FakeFaces
) -> None:
    first, second = two_clips(client, pid, api_settings, footage)
    overview = actors_of(client, pid)
    assert [(a["name"], a["named"], a["tracks"], a["clips"]) for a in overview["actors"]] == [
        ("Actor 001", False, 2, 2),
        ("Actor 002", False, 2, 2),
    ]
    assert overview["scans"] == {"done": 2} and overview["message"] is None
    run = overview["run"]
    assert (run["method"], run["tracks"], run["actors"]) == ("agglomerative", 4, 2)
    assert run["engine"] == "yunet-sface" and overview["clustered_at"]
    detail = detail_of(client, overview["actors"][0]["id"])
    assert {t["media_id"] for t in detail["track_list"]} == {first, second}
    assert detail["seen_s"] == pytest.approx(4.0, abs=0.1) and detail["crop_url"]

    # Twins: the same vector twice in every frame is still two people.
    fake.people = [(0.1, person(3)), (0.6, person(3))]
    third = import_clip(client, pid, footage / "b_prores.mov")
    drain(api_settings)
    twins = {t["actor_id"] for t in faces_of(client, third)["tracks"]}
    assert len(twins) == 2 and len(actors_of(client, pid)["actors"]) == 4

    # Removing a clip removes its faces; a person with no faces left disappears.
    assert client.delete(f"/api/media/{third}").status_code == 204
    assert len(actors_of(client, pid)["actors"]) == 2
    assert not (api_settings.project_dir(pid) / "faces" / third).exists()


def test_rename_merge_and_split(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    footage: Path,
    fake: FakeFaces,
    factory: sessionmaker[Session],
) -> None:
    two_clips(client, pid, api_settings, footage)
    one, two = actors_of(client, pid)["actors"]
    before = actors_of(client, pid)["run"]
    renamed = client.patch(f"/api/actors/{one['id']}", json={"name": "  Asha \x00 Rao  "})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Asha Rao"
    assert renamed.json()["named"] and {t["state"] for t in renamed.json()["track_list"]} == {
        "pinned"
    }
    # A correction changes what was asked and nothing else: the project is not grouped again.
    after = actors_of(client, pid)
    assert after["run"] == before  # naming someone is not "placing" their faces
    kept = renamed.json()["track_list"][0]["assignment"]
    assert kept["how"] == "kept with this person by your correction"
    assert kept["similarity_to_group"] > 0.9 and kept["method"] == "agglomerative"
    assert [a["tracks"] for a in after["actors"]] == [2, 2]
    assert client.patch(f"/api/actors/{one['id']}", json={"name": " \x00 "}).status_code == 422
    assert client.patch("/api/actors/nope", json={"name": "x"}).status_code == 404

    # Merge the named person INTO the unnamed one: the name the user gave survives.
    merged = client.post(f"/api/actors/{two['id']}/merge", json={"actor_ids": [one["id"]]})
    assert merged.status_code == 200, merged.text
    assert (merged.json()["name"], merged.json()["tracks"]) == ("Asha Rao", 4)
    assert [a["id"] for a in actors_of(client, pid)["actors"]] == [two["id"]]
    assert client.get(f"/api/actors/{one['id']}").status_code == 404
    same = client.post(f"/api/actors/{two['id']}/merge", json={"actor_ids": [two["id"]]})
    assert same.status_code == 422

    # Split two tracks off again; grouping again keeps both corrections.
    tracks = merged.json()["track_list"]
    assert {t["assignment"]["how"] for t in tracks} == {"kept with this person by your correction"}
    chosen = [t["id"] for t in renamed.json()["track_list"]]  # the faces merged in by mistake
    split = client.post(f"/api/actors/{two['id']}/split", json={"track_ids": chosen})
    assert split.status_code == 200, split.text
    created = split.json()
    assert {t["assignment"]["how"] for t in created["track_list"]} == {"placed by you"}
    assert actors_of(client, pid)["run"]["tracks_placed_by_you"] == 2
    assert created["name"] == "Actor 001" and {t["id"] for t in created["track_list"]} == set(
        chosen
    )
    everything = [t["id"] for t in tracks]
    assert client.post(
        f"/api/actors/{two['id']}/split", json={"track_ids": everything}
    ).status_code in (404, 422)
    rest = [t for t in everything if t not in chosen]
    assert (
        client.post(f"/api/actors/{two['id']}/split", json={"track_ids": rest}).status_code == 422
    )
    assert (
        client.post(f"/api/actors/{two['id']}/split", json={"track_ids": ["nope"]}).status_code
        == 404
    )
    again = client.post(f"/api/projects/{pid}/actors/regroup").json()
    assert sorted((a["name"], a["tracks"]) for a in again["actors"]) == [
        ("Actor 001", 2),
        ("Asha Rao", 2),
    ]
    with factory() as session:
        kinds = [e.kind for e in session.query(FeedbackEvent).order_by(FeedbackEvent.id)]
    assert kinds == ["actor_rename", "actor_merge", "actor_split"]


def test_set_aside_move_and_hand_back(
    client: TestClient, pid: str, api_settings: Settings, footage: Path, fake: FakeFaces
) -> None:
    two_clips(client, pid, api_settings, footage)
    one, two = actors_of(client, pid)["actors"]
    mine = [t["id"] for t in detail_of(client, one["id"])["track_list"]]

    def place(track_ids: list[str], state: str, actor_id: str | None = None) -> Any:
        body = {"track_ids": track_ids, "state": state, "actor_id": actor_id}
        return client.post(f"/api/projects/{pid}/face-tracks/place", json=body)

    after = place(mine[:1], "ignored").json()
    assert after["ignored"] == 1 and after["actors"][1]["tracks"] == 1
    assert place(mine[1:], "unknown").json()["unknown"] == 1
    aside = client.get(f"/api/projects/{pid}/face-tracks").json()
    assert sorted(t["state"] for t in aside) == ["ignored", "unknown"]
    assert all(t["actor_id"] is None for t in aside)
    # Someone whose faces are all set aside is no longer listed.
    assert [a["id"] for a in actors_of(client, pid)["actors"]] == [two["id"]]

    # Move one of them to the other person: it stays there although it looks different.
    moved = place(mine[:1], "actor", two["id"])
    assert moved.status_code == 200 and moved.json()["actors"][0]["tracks"] == 3
    assert place(mine[:1], "actor", "nope").status_code == 404
    assert place(mine[:1], "actor").status_code == 422
    assert place(["nope"], "ignored").status_code == 404

    # Handing everything back to automatic grouping restores the two people.
    restored = place(mine, "auto").json()
    assert [a["tracks"] for a in restored["actors"]] == [2, 2]
    assert restored["ignored"] == 0 and restored["unknown"] == 0


def test_corrections_survive_scanning_with_other_settings(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    footage: Path,
    fake: FakeFaces,
    factory: sessionmaker[Session],
) -> None:
    first, second = two_clips(client, pid, api_settings, footage)
    one, two = actors_of(client, pid)["actors"]
    client.patch(f"/api/actors/{one['id']}", json={"name": "Asha"})
    aside = [t["id"] for t in detail_of(client, two["id"])["track_list"] if t["media_id"] == first]
    client.post(
        f"/api/projects/{pid}/face-tracks/place", json={"track_ids": aside, "state": "ignored"}
    )

    # Other sampling: every clip is scanned again and its tracks are written anew.
    api_settings.faces = FaceConfig(sample_fps=5.0)
    scanned = fake.frames
    client.post(f"/api/projects/{pid}/process")
    drain(api_settings)
    assert fake.frames > scanned
    tracks = [t for m in (first, second) for t in faces_of(client, m)["tracks"]]
    assert all(t["face_count"] > 5 for t in tracks)
    overview = actors_of(client, pid)
    assert overview["run"]["corrections_not_found"] == 0
    named = next(a for a in overview["actors"] if a["name"] == "Asha")
    assert (named["id"], named["tracks"], named["clips"]) == (one["id"], 2, 2)
    assert overview["ignored"] == 1
    # The untouched person is the same actor as before the rescan, not a new number.
    assert sorted(x["name"] for x in overview["actors"]) == ["Actor 002", "Asha"]
    assert two["id"] in [x["id"] for x in overview["actors"]]
    ignored = [t for t in tracks if t["state"] == "ignored"]
    assert [t["media_id"] for t in ignored] == [first]
    with factory() as session:
        pins = session.query(FacePin).all()
        assert pins and all(pin.track_id is not None for pin in pins)

    # A correction whose face is gone is kept and counted, not applied to someone else.
    fake.people = [(0.6, person(1))]
    api_settings.faces = FaceConfig(sample_fps=4.0)
    client.post(f"/api/projects/{pid}/process")
    drain(api_settings)
    overview = actors_of(client, pid)
    assert overview["run"]["corrections_not_found"] > 0
    assert "Asha" not in [a["name"] for a in overview["actors"]]


def test_grouping_settings_change_regroups_without_scanning(
    client: TestClient, pid: str, api_settings: Settings, footage: Path, fake: FakeFaces
) -> None:
    fake.people = [(0.1, person(0)), (0.6, person(0, 0.9))]  # alike, but in the same frame
    media_id = import_clip(client, pid, footage / "a_h264.mp4")
    drain(api_settings)
    fake.people = [(0.1, person(0, 0.5))]
    import_clip(client, pid, footage / "c_ntsc_noaudio.mkv")
    drain(api_settings)
    scanned = fake.frames
    assert len(actors_of(client, pid)["actors"]) == 2
    api_settings.faces = FaceConfig(cluster_distance=0.01)
    client.post(f"/api/projects/{pid}/process")
    drain(api_settings)
    assert fake.frames == scanned  # stage results came from the cache
    strict = actors_of(client, pid)
    assert len(strict["actors"]) == 3 and strict["run"]["cluster_distance"] == 0.01
    assert len({t["actor_id"] for t in faces_of(client, media_id)["tracks"]}) == 2


def test_ids_from_another_project_are_refused(
    client: TestClient, pid: str, api_settings: Settings, footage: Path, fake: FakeFaces
) -> None:
    two_clips(client, pid, api_settings, footage)
    other = client.post("/api/projects", json={"name": "other"}).json()["id"]
    import_clip(client, other, footage / "a_h264.mp4")
    drain(api_settings)
    mine, theirs = actors_of(client, pid)["actors"][0], actors_of(client, other)["actors"][0]
    their_tracks = [t["id"] for t in detail_of(client, theirs["id"])["track_list"]]
    my_track = detail_of(client, mine["id"])["track_list"][0]["id"]
    merged = client.post(f"/api/actors/{mine['id']}/merge", json={"actor_ids": [theirs["id"]]})
    assert merged.status_code == 404
    split = client.post(f"/api/actors/{mine['id']}/split", json={"track_ids": their_tracks})
    assert split.status_code == 404
    bodies: list[dict[str, Any]] = [
        {"track_ids": their_tracks, "state": "ignored"},
        {"track_ids": their_tracks, "state": "actor", "actor_id": mine["id"]},
        {"track_ids": [my_track], "state": "actor", "actor_id": theirs["id"]},
    ]
    for body in bodies:
        assert client.post(f"/api/projects/{pid}/face-tracks/place", json=body).status_code == 404
    assert actors_of(client, other)["actors"][0]["tracks"] == theirs["tracks"]


def test_a_correction_does_not_hide_faces_that_still_wait_to_be_grouped(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    footage: Path,
    fake: FakeFaces,
    factory: sessionmaker[Session],
) -> None:
    first = import_clip(client, pid, footage / "a_h264.mp4")
    drain(api_settings)
    one = actors_of(client, pid)["actors"][0]
    second = import_clip(client, pid, footage / "c_ntsc_noaudio.mkv")
    third = import_clip(client, pid, footage / "b_prores.mov")
    job = queue.claim_next(factory)
    assert job is not None
    run_job(factory, api_settings, job)
    _after_ingest(factory, api_settings, job)  # the third clip still waits: not grouped yet
    assert [t["actor_id"] for t in faces_of(client, second)["tracks"]] == [None, None]

    # A correction made meanwhile must not make the project look up to date ...
    assert client.patch(f"/api/actors/{one['id']}", json={"name": "Asha"}).status_code == 200
    # ... and cancelling the last waiting job groups what the finished ones found.
    pending = client.get(f"/api/media/{third}").json()["job"]["id"]
    assert client.post(f"/api/jobs/{pending}/cancel").status_code == 200
    assert all(t["actor_id"] for t in faces_of(client, second)["tracks"])
    people = actors_of(client, pid)["actors"]
    assert sorted((a["name"], a["tracks"], a["clips"]) for a in people) == [
        ("Actor 002", 2, 2),
        ("Asha", 2, 2),
    ]
    assert faces_of(client, first)["tracks"][0]["state"] == "pinned"


def test_one_stray_pin_does_not_decide_a_long_track(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    footage: Path,
    fake: FakeFaces,
    factory: sessionmaker[Session],
) -> None:
    media = import_clip(client, pid, footage / "a_h264.mp4")
    drain(api_settings)

    def pin(session: Session, track: str, time_s: float) -> None:
        session.add(
            FacePin(project_id=pid, media_id=media, time_s=time_s, x=0, y=0, w=0.1, h=0.1,
                    state="ignored", actor_id=None, track_id=track)
        )  # fmt: skip

    def track(name: str, end_s: float) -> FaceTrack:
        return FaceTrack(id=name, media_id=media, index=0, start_s=0.0, end_s=end_s, face_count=9)

    votes = actors._votes  # pyright: ignore[reportPrivateUsage]
    with factory() as session:
        pin(session, "long", 3.0)
        pin(session, "short", 0.0)
        for time_s in (0.0, 4.0, 9.5):
            pin(session, "covered", time_s)
        session.flush()
        tracks = [track("long", 20.0), track("short", 0.5), track("covered", 20.0)]
        assert votes(session, pid, tracks) == {
            "short": ("ignored", None),
            "covered": ("ignored", None),
        }


def test_hdbscan_grouping_keeps_corrections_and_does_not_claim_a_distance(
    client: TestClient, pid: str, api_settings: Settings, footage: Path, fake: FakeFaces
) -> None:
    two_clips(client, pid, api_settings, footage)
    one, _ = actors_of(client, pid)["actors"]
    client.patch(f"/api/actors/{one['id']}", json={"name": "Asha"})
    api_settings.faces = FaceConfig(cluster_method="hdbscan")
    again = client.post(f"/api/projects/{pid}/actors/regroup").json()
    assert again["run"]["method"] == "hdbscan" and "cluster_distance" not in again["run"]
    assert sorted((a["name"], a["tracks"]) for a in again["actors"]) == [
        ("Actor 002", 2),
        ("Asha", 2),
    ]
    listed = [t for a in again["actors"] for t in detail_of(client, a["id"])["track_list"]]
    auto = [t for t in listed if t["state"] == "auto"]
    assert auto and all("cluster_distance" not in t["assignment"] for t in auto)


def test_faces_seen_too_briefly_are_set_aside_until_the_user_places_them(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    footage: Path,
    fake: FakeFaces,
    factory: sessionmaker[Session],
) -> None:
    two_clips(client, pid, api_settings, footage)
    one, two = actors_of(client, pid)["actors"]
    flash = detail_of(client, one["id"])["track_list"][0]["id"]
    with factory() as session:  # as if the face had been found in one sampled frame only
        track = session.get(FaceTrack, flash)
        assert track is not None
        track.face_count = 1
        session.commit()
    after = client.post(f"/api/projects/{pid}/actors/regroup").json()
    assert after["brief"] == 1 and after["run"]["tracks_seen_briefly"] == 1
    assert after["run"]["min_track_faces"] == 2
    aside = client.get(f"/api/projects/{pid}/face-tracks").json()
    assert [(t["id"], t["state"], t["actor_id"]) for t in aside] == [(flash, "brief", None)]
    assert "seen in only 1 sampled frame" in aside[0]["assignment"]["how"]

    # The user knows better: placed with a person, it stays there however brief it was.
    body = {"track_ids": [flash], "state": "actor", "actor_id": two["id"]}
    placed = client.post(f"/api/projects/{pid}/face-tracks/place", json=body).json()
    assert placed["brief"] == 0
    again = client.post(f"/api/projects/{pid}/actors/regroup").json()
    assert again["brief"] == 0 and flash in {
        t["id"] for t in detail_of(client, two["id"])["track_list"]
    }

    # A setting of 1 keeps every face.
    api_settings.faces = FaceConfig(min_track_faces=1)
    assert (
        client.post(f"/api/projects/{pid}/actors/regroup").json()["run"]["tracks_seen_briefly"] == 0
    )


def test_same_person_questions_merge_on_yes_and_keep_apart_on_no(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    footage: Path,
    fake: FakeFaces,
    factory: sessionmaker[Session],
) -> None:
    # Person 2 shows up in a third clip looking a little different from person 0: grouped as a
    # person of its own (a stand-in for one actor split in two).
    two_clips(client, pid, api_settings, footage)
    fake.people = [(0.1, person(0, wobble=3.0))]  # cosine 1/sqrt(10) to person 0
    import_clip(client, pid, footage / "b_prores.mov")
    drain(api_settings)
    people = actors_of(client, pid)["actors"]
    assert len(people) == 3
    pairs = client.get(f"/api/projects/{pid}/actors/pairs").json()
    assert pairs["answered"] == 0 and pairs["cluster_distance"] == 0.6
    # Persons 0 and 1 share every frame: never asked. The closest pair comes first.
    asked = [{p["first"]["id"], p["second"]["id"]} for p in pairs["pairs"]]
    zero, one = (a["id"] for a in people[:2])
    assert {zero, one} not in asked
    first = pairs["pairs"][0]
    assert first["distance"] == pytest.approx(1 - 10**-0.5, abs=0.01)
    assert [p["distance"] for p in pairs["pairs"]] == sorted(p["distance"] for p in pairs["pairs"])

    def answer(a: str, b: str, same: bool) -> Any:
        body = {"first_id": a, "second_id": b, "same": same}
        return client.post(f"/api/projects/{pid}/actors/pairs/answer", json=body)

    # "No": not asked again, and kept apart by a regrouping whose limit would join them.
    a, b = first["first"]["id"], first["second"]["id"]
    after = answer(a, b, False).json()
    assert after["answered"] == 1 and after["answered_same"] == 0
    assert {a, b} not in [{p["first"]["id"], p["second"]["id"]} for p in after["pairs"]]
    api_settings.faces = FaceConfig(cluster_distance=0.9)
    regrouped = client.post(f"/api/projects/{pid}/actors/regroup").json()
    owners = {t["actor_id"] for x in (a, b) for t in faces_of_actor(client, x)}
    assert len(owners) == 2 and len(regrouped["actors"]) == 3

    # "Yes" on the remaining pair merges it; the bigger person stays.
    api_settings.faces = FaceConfig()
    rest = client.get(f"/api/projects/{pid}/actors/pairs").json()["pairs"]
    c, d = rest[0]["first"]["id"], rest[0]["second"]["id"]
    merged = answer(c, d, True).json()
    assert merged["answered"] == 2 and merged["answered_same"] == 1
    assert len(actors_of(client, pid)["actors"]) == 2
    assert answer(c, c, True).status_code in (404, 422)
    assert answer(a, "nope", False).status_code == 404
    with factory() as session:
        kinds = [e.kind for e in session.query(FeedbackEvent).order_by(FeedbackEvent.id)]
    assert kinds.count("actor_pair") == 2 and "actor_merge" in kinds


def faces_of_actor(client: TestClient, actor_id: str) -> list[dict[str, Any]]:
    res = client.get(f"/api/actors/{actor_id}")
    return res.json()["track_list"] if res.status_code == 200 else []
