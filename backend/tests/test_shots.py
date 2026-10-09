import subprocess
from fractions import Fraction
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from cinemind.core.config import Settings
from cinemind.core.errors import InvalidInputError
from cinemind.db.models import Job, Keyframe, MediaAsset, Project, Shot
from cinemind.jobs import queue
from cinemind.jobs.runner import run_job
from cinemind.pipeline import importer, shots
from conftest import CUTS_DURATION_S, CUTS_S
from helpers import drain, import_one

FPS = Fraction(25)
TRUTH = [0, *(round(c * 25) for c in CUTS_S), round(CUTS_DURATION_S * 25)]


def _quiet(_fraction: float) -> None:
    return None


def _never_cancel() -> None:
    return None


@pytest.mark.parametrize("detector", ["adaptive", "content"])
def test_detected_shots_match_synthetic_ground_truth(cut_footage: Path, detector: str) -> None:
    found = shots.detect_shots(
        cut_footage / "cuts.mp4", FPS, detector, None, 0.5, _quiet, _never_cancel
    )
    assert found.frames == TRUTH[-1]
    assert found.shots == list(zip(TRUTH[:-1], TRUTH[1:], strict=True))  # frame exact
    assert found.threshold == shots.DEFAULT_THRESHOLDS[detector]


def test_clip_without_cuts_is_one_shot_and_unknown_detector_is_rejected(footage: Path) -> None:
    found = shots.detect_shots(
        footage / "a_h264.mp4", FPS, "adaptive", None, 0.5, _quiet, _never_cancel
    )
    assert found.shots == [(0, found.frames)] and found.frames == 50
    with pytest.raises(InvalidInputError):
        shots.detect_shots(footage / "a_h264.mp4", FPS, "magic", None, 0.5, _quiet, _never_cancel)


def test_cut_at_a_detection_chunk_boundary_is_found(tmp_path: Path) -> None:
    # Detection reads 240 frames at a time; a cut exactly there must not be lost or doubled.
    clip = tmp_path / "long.mp4"
    size = "size=320x240:rate=25"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    cmd += ["-f", "lavfi", "-i", f"testsrc2={size}:duration=9.6"]
    cmd += ["-f", "lavfi", "-i", f"smptebars={size}:duration=2"]
    cmd += ["-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-c:v", "libx264"]
    subprocess.run([*cmd, "-pix_fmt", "yuv420p", str(clip)], check=True, timeout=120)  # noqa: S603
    steps: list[float] = []
    found = shots.detect_shots(clip, FPS, "adaptive", None, 0.5, steps.append, _never_cancel)
    assert found.shots == [(0, 240), (240, 290)]
    assert len(steps) == 2 and steps[-1] == 1.0  # progress was reported per chunk


def test_keyframe_plan_stays_inside_each_shot() -> None:
    spans = [(0, 10), (10, 60), (60, 400), (400, 402)]
    plan = shots.keyframe_plan(spans, FPS, per_shot=3)
    assert [sum(1 for shot, _ in plan if shot == i) for i in range(4)] == [1, 2, 3, 1]
    for (shot, _slot), candidates in plan.items():
        start, end = spans[shot]
        assert candidates and all(start <= frame < end for frame in candidates)
    picked = [c for (shot, _), cs in plan.items() if shot == 2 for c in cs]
    assert len(picked) == len(set(picked))  # the three anchors never share a frame
    assert shots.keyframe_plan(spans, FPS, per_shot=1).keys() == {(i, 0) for i in range(4)}


def test_keyframe_is_the_sharpest_candidate(tmp_path: Path) -> None:
    # One 1 s shot that is blurred except for frames 11-13.
    clip = tmp_path / "blur.mp4"
    blur = "boxblur=10:enable='not(between(n,11,13))'"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i"]
    cmd += ["testsrc2=size=320x240:rate=25:duration=1", "-vf", blur, "-c:v", "libx264"]
    subprocess.run([*cmd, "-pix_fmt", "yuv420p", str(clip)], check=True, timeout=60)  # noqa: S603
    found = shots.extract_keyframes(clip, [(0, 25)], FPS, 3, tmp_path / "kf", _quiet, _never_cancel)
    assert len(found) == 1 and 11 <= found[0]["frame"] <= 13
    assert (tmp_path / "kf" / found[0]["file"]).read_bytes()[:2] == b"\xff\xd8"  # a JPEG
    assert not (tmp_path / "kf.partial").exists()


# --- through the ingest chain ----------------------------------------------------------------


def _ingest(factory: sessionmaker[Session], settings: Settings, source: Path) -> tuple[str, str]:
    settings.media_roots = [source.parent]
    with factory() as s:
        project = Project(name="t")
        s.add(project)
        s.commit()
        asset = importer.import_file(s, settings, project.id, source, "reference").asset
        assert asset
        job_id = importer.enqueue_ingest(s, settings, asset).id
    queue.claim_next(factory)
    run_job(factory, settings, job_id)
    return asset.id, job_id


def _rerun(factory: sessionmaker[Session], settings: Settings, asset_id: str) -> list[str]:
    with factory() as s:
        asset = s.get(MediaAsset, asset_id)
        assert asset
        job_id = importer.enqueue_ingest(s, settings, asset).id
    queue.claim_next(factory)
    run_job(factory, settings, job_id)
    with factory() as s:
        job = s.get(Job, job_id)
        assert job
        return [st.status for st in job.stages]


def test_ingest_stores_shots_and_keyframes_with_provenance(
    factory: sessionmaker[Session], settings: Settings, cut_footage: Path
) -> None:
    asset_id, job_id = _ingest(factory, settings, cut_footage / "cuts.mp4")
    with factory() as s:
        job = s.get(Job, job_id)
        assert job and job.status == "succeeded"
        assert [st.name for st in job.stages][4:6] == ["shots", "keyframes"]
        assert job.stages[4].model_name == "pyscenedetect"
        rows = list(s.query(Shot).filter_by(media_id=asset_id).order_by(Shot.index))
        assert [(r.start_frame, r.end_frame) for r in rows] == list(
            zip(TRUTH[:-1], TRUTH[1:], strict=True)
        )
        assert [r.start_s for r in rows] == [0.0, *CUTS_S]
        assert rows[0].detection["detector"] == "adaptive" and rows[0].detection["threshold"] == 3.0
        asset = s.get(MediaAsset, asset_id)
        assert asset
        root = settings.project_dir(asset.project_id)
        for row in rows:
            assert 1 <= len(row.keyframes) <= 3
            for key in row.keyframes:
                assert row.start_frame <= key.frame < row.end_frame
                assert (root / key.path).stat().st_size > 0
        ids = [r.id for r in rows], [k.id for r in rows for k in r.keyframes]

    assert _rerun(factory, settings, asset_id) == ["cached"] * 8
    with factory() as s:
        rows = list(s.query(Shot).filter_by(media_id=asset_id).order_by(Shot.index))
        assert ([r.id for r in rows], [k.id for r in rows for k in r.keyframes]) == ids


def test_changed_setting_redetects_and_lost_keyframes_are_recreated(
    factory: sessionmaker[Session], settings: Settings, cut_footage: Path
) -> None:
    asset_id, _ = _ingest(factory, settings, cut_footage / "cuts.mp4")
    with factory() as s:
        asset = s.get(MediaAsset, asset_id)
        key = s.query(Keyframe).filter_by(media_id=asset_id).first()
        assert asset and key
        lost = settings.project_dir(asset.project_id) / key.path
    lost.unlink()
    assert _rerun(factory, settings, asset_id)[4:6] == ["cached", "succeeded"]
    assert lost.is_file()

    settings.shot_min_len_s = 3.0  # too long for the 1.52 s segment: fewer shots
    assert _rerun(factory, settings, asset_id)[4:6] == ["succeeded", "succeeded"]
    with factory() as s:
        rows = list(s.query(Shot).filter_by(media_id=asset_id).order_by(Shot.index))
        assert 1 <= len(rows) < 4 and rows[0].detection["min_len_frames"] == 75
        assert rows[-1].end_frame == TRUTH[-1]
        assert s.query(Keyframe).filter(Keyframe.shot_id.notin_([r.id for r in rows])).count() == 0


def test_audio_only_has_no_shots(
    factory: sessionmaker[Session], settings: Settings, footage: Path
) -> None:
    asset_id, job_id = _ingest(factory, settings, footage / "d_audio.wav")
    with factory() as s:
        job = s.get(Job, job_id)
        assert job and job.status == "succeeded"
        assert s.query(Shot).filter_by(media_id=asset_id).count() == 0


# --- API --------------------------------------------------------------------------------------


def test_shot_endpoints_and_cleanup(
    client: TestClient, api_settings: Settings, pid: str, cut_footage: Path
) -> None:
    api_settings.media_roots.append(cut_footage)
    import_one(client, pid, cut_footage / "cuts.mp4")
    import_one(client, pid, cut_footage / "one_shot_ntsc.mov")
    drain(api_settings)
    media = {m["filename"]: m["id"] for m in client.get(f"/api/projects/{pid}/media").json()}

    listed = client.get(f"/api/media/{media['cuts.mp4']}/shots").json()
    assert [s["index"] for s in listed] == [0, 1, 2, 3]
    assert [s["end_s"] for s in listed] == [*CUTS_S, CUTS_DURATION_S]
    assert listed[0]["detection"]["library"] == "PySceneDetect"
    key = listed[2]["keyframes"][0]
    assert listed[2]["start_s"] <= key["time_s"] < listed[2]["end_s"] and key["sharpness"] > 0
    image = client.get(f"/api/keyframes/{key['id']}/image")
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"

    everything = client.get(f"/api/projects/{pid}/shots").json()
    assert [(s["filename"], s["index"]) for s in everything] == [
        *[("cuts.mp4", i) for i in range(4)],
        ("one_shot_ntsc.mov", 0),
    ]
    assert (everything[-1]["fps_num"], everything[-1]["fps_den"]) == (30000, 1001)

    assert client.get("/api/media/nope/shots").status_code == 404
    missing = client.get("/api/keyframes/nope/image")
    assert missing.status_code == 404 and "Reprocess" in missing.json()["message"]

    folder = api_settings.project_dir(pid) / "keyframes" / media["cuts.mp4"]
    assert folder.is_dir()
    assert client.delete(f"/api/media/{media['cuts.mp4']}").status_code == 204
    assert not folder.exists()  # derived data is removed with the clip
    assert len(client.get(f"/api/projects/{pid}/shots").json()) == 1
    assert client.get(f"/api/keyframes/{key['id']}/image").status_code == 404
    assert (cut_footage / "cuts.mp4").is_file()  # the source is never touched
