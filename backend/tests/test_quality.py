# OpenCV images are untyped arrays.
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false

import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from cinemind.core.config import Settings
from cinemind.core.quality_config import QualityConfig
from cinemind.pipeline import qc, quality
from cinemind.pipeline.quality_stages import audio_flags, audio_score
from helpers import drain, import_one

CFG = QualityConfig()
PARAMS = qc.detector_params(CFG)


def _quiet(_fraction: float) -> None:
    return None


def _never_cancel() -> None:
    return None


def _noise(seed: int = 1) -> Any:
    rng = np.random.default_rng(seed)
    return rng.integers(60, 200, size=(360, 640, 3), dtype=np.uint8)


def _flat(value: int) -> Any:
    return np.full((360, 640, 3), value, dtype=np.uint8)


# --- picture metrics on images with a known property -------------------------------------------


def test_blur_metric_rises_with_blur_and_flat_frames_count_as_blurry() -> None:
    import cv2

    sharp = quality.frame_metrics(_noise())
    soft = quality.frame_metrics(cv2.GaussianBlur(_noise(), (0, 0), 2))
    softer = quality.frame_metrics(cv2.GaussianBlur(_noise(), (0, 0), 6))
    assert sharp.blur < soft.blur < softer.blur <= 1.0
    assert sharp.sharpness > soft.sharpness > softer.sharpness
    assert sharp.blur < CFG.out_of_focus_blur_above < softer.blur
    # A flat frame has nothing that could be sharp: focus is not judged, in the flag AND the score.
    flat = quality.aggregate([quality.frame_metrics(_flat(128))])
    assert flat["blur"] == 1.0 and quality.picture_flags(flat, CFG) == []
    scores = quality.sub_scores(flat, CFG)
    assert scores == {"sharpness": None, "exposure": 1.0, "contrast": 0.0}
    assert quality.video_score(scores, CFG) == 0.6  # (0.3 * 1 + 0.2 * 0) / 0.5, focus left out


def test_metrics_do_not_depend_on_resolution() -> None:
    import cv2

    small = _noise()
    large: Any = cv2.resize(small, (2560, 1440), interpolation=cv2.INTER_NEAREST)
    a, b = quality.frame_metrics(small), quality.frame_metrics(large)
    assert a.luma_mean == pytest.approx(b.luma_mean, abs=0.01)
    assert a.blur == pytest.approx(b.blur, abs=0.05)


def test_exposure_extremes_are_measured_and_flagged() -> None:
    white = quality.aggregate([quality.frame_metrics(_flat(255))])
    black = quality.aggregate([quality.frame_metrics(_flat(0))])
    assert white["clipped"] == 1.0 and white["luma_mean"] == 1.0 and white["crushed"] == 0.0
    assert black["crushed"] == 1.0 and black["luma_mean"] == 0.0
    over = {f["kind"]: f for f in quality.picture_flags(white, CFG)}
    under = {f["kind"]: f for f in quality.picture_flags(black, CFG)}
    assert "overexposed" in over and "underexposed" not in over
    assert "underexposed" in under and "overexposed" not in under
    # each flag says what was measured and which threshold it crossed
    assert over["overexposed"] == {
        "kind": "overexposed",
        "metric": "luma_mean",
        "value": 1.0,
        "threshold": CFG.overexposed_mean_above,
        "direction": "above",
    }
    assert quality.sub_scores(white, CFG)["exposure"] == 0.0


def test_score_is_the_documented_weighted_sum() -> None:
    good = {
        "blur": 0.05,
        "sharpness": 400.0,
        "luma_mean": 0.45,
        "clipped": 0.0,
        "crushed": 0.0,
        "spread": 0.7,
    }
    scores = quality.sub_scores(good, CFG)
    assert scores == {"sharpness": 1.0, "exposure": 1.0, "contrast": 1.0}
    assert quality.video_score(scores, CFG) == 1.0 and quality.picture_flags(good, CFG) == []

    halfway = {**good, "blur": (CFG.sharp_blur + CFG.out_of_focus_blur_above) / 2}
    scores = quality.sub_scores(halfway, CFG)
    assert scores["sharpness"] == pytest.approx(0.5, abs=0.001)
    assert quality.video_score(scores, CFG) == pytest.approx(0.75, abs=0.001)  # 0.5*0.5 + 0.3 + 0.2

    only_sharpness = QualityConfig(weight_exposure=0, weight_contrast=0)
    assert quality.video_score(scores, only_sharpness) == pytest.approx(0.5, abs=0.001)
    at_threshold = {**good, "blur": CFG.out_of_focus_blur_above + 0.01}
    assert quality.sub_scores(at_threshold, CFG)["sharpness"] == 0.0
    assert [f["kind"] for f in quality.picture_flags(at_threshold, CFG)] == ["out_of_focus"]
    # compression artefacts can keep the blur ratio down; next to no detail at all still flags
    blocky = {**good, "blur": 0.5, "sharpness": 4.7}
    assert quality.sub_scores(blocky, CFG)["sharpness"] == 0.0  # the score agrees with the flag
    assert quality.picture_flags(blocky, CFG)[0] == {
        "kind": "out_of_focus",
        "metric": "sharpness",
        "value": 4.7,
        "threshold": CFG.out_of_focus_sharpness_below,
        "direction": "below",
    }


def test_frame_sampling_stays_inside_the_shot() -> None:
    assert quality.sample_frames(0, 0, 25) == []
    assert quality.sample_frames(10, 12, 25) == [11]
    long = quality.sample_frames(100, 100 + 25 * 60, 25)
    assert (
        len(long) == quality.MAX_FRAMES_PER_SHOT and long[0] > 100 and long[-1] < 100 + 25 * 60 - 1
    )
    assert len(quality.sample_frames(0, 50, 25)) == 4  # 2 s at one frame per 0.5 s


@pytest.mark.parametrize(
    "bad",
    [
        {"sharp_blur": 0.6},  # above the out-of-focus limit: the focus score would invert
        {"exposure_ok_low": 0.25},  # equal to the underexposed limit
        {"overexposed_clipped_above": 0.0},
        {"weight_sharpness": 0.0, "weight_exposure": 0.0, "weight_contrast": 0.0},
        {"weight_contrast": -1.0},
        {"weight_audio": float("nan")},
        {"good_level_lufs": -40.0},
    ],
)
def test_inconsistent_settings_are_rejected(bad: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="quality settings|weight"):
        QualityConfig(**bad)


def test_ranges_pair_events_and_stay_inside_the_file() -> None:
    pair = qc._ranges  # pyright: ignore[reportPrivateUsage]
    assert pair([("start", "1"), ("end", "2.5")], 10) == [[1.0, 2.5]]
    assert pair([("start", "8")], 10) == [[8.0, 10.0]]  # still running at the end of the file
    assert pair([("end", "3")], 10) == []  # an end without a start is ignored
    assert pair([("start", "-0.02"), ("end", "12")], 10) == [[0.0, 10.0]]
    assert pair([("start", "1"), ("end", "1.5"), ("start", "4"), ("end", "9")], 10, 2.0) == [
        [4.0, 9.0]
    ]
    assert pair([("start", "11"), ("end", "12")], 10, 0.1) == []  # nothing left after clamping


# --- FFmpeg detectors on clips with a known defect ---------------------------------------------


def test_black_and_frozen_ranges(qc_footage: Path) -> None:
    found = qc.detect_black_freeze(
        qc_footage / "black_freeze.mp4", 7.5, PARAMS, _quiet, _never_cancel
    )
    assert len(found["black"]) == 1 and len(found["frozen"]) == 1
    assert found["black"][0] == pytest.approx([2.0, 3.5], abs=0.1)
    assert found["frozen"][0] == pytest.approx([4.5, 7.5], abs=0.15)
    clean = qc.detect_black_freeze(qc_footage / "sharp.mp4", 3.0, PARAMS, _quiet, _never_cancel)
    assert clean == {"black": [], "frozen": []}


def test_silence_range_and_loudness(qc_footage: Path) -> None:
    gap = qc.measure_loudness(qc_footage / "gap.wav", 7.0, PARAMS, _quiet, _never_cancel)
    assert len(gap["silences"]) == 1
    assert gap["silences"][0] == pytest.approx([2.0, 5.0], abs=0.05)
    assert gap["integrated_lufs"] is not None and -30 < gap["integrated_lufs"] < -15
    quiet = qc.measure_loudness(qc_footage / "quiet.wav", 3.0, PARAMS, _quiet, _never_cancel)
    assert quiet["silences"] == [[0.0, 3.0]]  # a -63 dBFS tone is under the -50 dB silence level
    assert quiet["integrated_lufs"] is None or quiet["integrated_lufs"] < CFG.low_level_lufs_below


def test_metadata_text_cannot_fake_a_detection(qc_footage: Path, tmp_path: Path) -> None:
    # A title that looks like detector output is printed by ffmpeg on the same stream.
    fake = tmp_path / "fake.wav"
    title = "silence_start: 1 x silence_end: 5 | I: -5.0 LUFS black_start:0 black_end:9"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i"]
    cmd += ["sine=frequency=440:duration=3", "-metadata", f"title={title}", str(fake)]
    subprocess.run(cmd, check=True, timeout=60)  # noqa: S603
    found = qc.measure_loudness(fake, 3.0, PARAMS, _quiet, _never_cancel)
    assert found["silences"] == [] and found["integrated_lufs"] < -10


def test_audio_too_short_to_measure_is_not_called_quiet(tmp_path: Path) -> None:
    short = tmp_path / "short.wav"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i"]
    subprocess.run([*cmd, "sine=frequency=440:duration=0.2", str(short)], check=True, timeout=60)  # noqa: S603
    found = qc.measure_loudness(short, 0.2, PARAMS, _quiet, _never_cancel)
    assert found["integrated_lufs"] is None and found["loudness_note"] == "too_short"
    result = {**found, "clipped_pct": 0.0, "duration_s": 0.2, "measured": True}
    assert audio_score(result, CFG)["score"] == 1.0
    assert audio_flags(result, CFG, PARAMS) == []


def test_clipped_samples_are_counted(qc_footage: Path) -> None:
    clipped = qc.count_clipped(qc_footage / "clipped.wav", CFG.clip_sample_level, _never_cancel)
    clean = qc.count_clipped(qc_footage / "gap.wav", CFG.clip_sample_level, _never_cancel)
    assert clipped["clipped_pct"] > 50 and clipped["sample_peak"] == 1.0
    assert clean["clipped_pct"] == 0.0 and clean["sample_peak"] < 0.2
    assert clipped["samples"] == 3 * 44100


def test_audio_score_and_its_parts() -> None:
    fine = {"integrated_lufs": -20.0, "clipped_pct": 0.0}
    assert audio_score(fine, CFG) == {"level": 1.0, "clipping": 1.0, "score": 1.0}
    assert audio_score({**fine, "integrated_lufs": -31.0}, CFG)["level"] == 0.5
    assert (
        audio_score({**fine, "integrated_lufs": None, "loudness_note": "silent"}, CFG)["score"] == 0
    )
    assert audio_score({**fine, "clipped_pct": 5.0}, CFG)["score"] == 0.0


# --- through the ingest chain and the API ------------------------------------------------------


@pytest.fixture
def qc_project(client: TestClient, api_settings: Settings, pid: str, qc_footage: Path) -> str:
    api_settings.media_roots.append(qc_footage)
    res = client.post(f"/api/projects/{pid}/media", json={"paths": [str(qc_footage)]})
    assert res.status_code == 201
    drain(api_settings)
    return pid


def _media(client: TestClient, pid: str) -> dict[str, dict[str, Any]]:
    return {m["filename"]: m for m in client.get(f"/api/projects/{pid}/media").json()}


def test_synthetic_fixtures_score_and_flag_as_expected(client: TestClient, qc_project: str) -> None:
    media = _media(client, qc_project)
    assert all(m["job"]["status"] == "succeeded" for m in media.values())
    assert media["sharp.mp4"]["qc_flags"] == []
    assert media["blurry.mp4"]["qc_flags"] == ["out_of_focus"]
    assert media["over.mp4"]["qc_flags"] == ["overexposed"]
    assert media["under.mp4"]["qc_flags"] == ["underexposed"]
    # its black section is a shot of its own: dark, but not "out of focus" (nothing to focus on)
    assert media["black_freeze.mp4"]["qc_flags"] == [
        "black_frames",
        "frozen_frames",
        "underexposed",
    ]
    assert media["gap.wav"]["qc_flags"] == ["long_silence"]
    assert media["clipped.wav"]["qc_flags"] == ["clipped_audio"]
    assert media["quiet.wav"]["qc_flags"] == ["long_silence", "low_audio_level"]
    score = {name: m["quality_score"] for name, m in media.items()}
    assert score["sharp.mp4"] > 0.9
    for worse in ("blurry.mp4", "over.mp4", "under.mp4"):
        assert score[worse] < score["sharp.mp4"] - 0.2, worse
    assert score["gap.wav"] == 1.0 and score["clipped.wav"] == 0.0 and score["quiet.wav"] == 0.0


def test_quality_endpoint_explains_the_score(client: TestClient, qc_project: str) -> None:
    media = _media(client, qc_project)
    blurry = client.get(f"/api/media/{media['blurry.mp4']['id']}/quality").json()
    assert blurry["measured"] and blurry["score"] == media["blurry.mp4"]["quality_score"]
    assert blurry["audio"] is None and len(blurry["shots"]) == 1
    shot = blurry["shots"][0]
    assert (
        shot["sharpness_score"] == 0.0
        and shot["blur"] > blurry["config"]["out_of_focus_blur_above"]
    )
    assert shot["frames"] >= 4
    flag = blurry["flags"][0]
    assert (flag["kind"], flag["source"], flag["shot_id"]) == (
        "out_of_focus",
        "picture",
        shot["shot_id"],
    )
    assert flag["details"]["metric"] == "blur" and flag["details"]["value"] == round(
        shot["blur"], 4
    )
    assert (flag["start_s"], flag["end_s"]) == (0.0, 3.0)

    sharp = client.get(f"/api/media/{media['sharp.mp4']['id']}/quality").json()
    assert sharp["audio"]["score"] == 1.0 and sharp["audio"]["clipped_pct"] == 0.0
    assert sharp["flags"] == [] and not sharp["low_quality"] and not sharp["settings_changed"]
    assert sharp["shots"][0]["index"] == 0
    # clip score = picture x (1 - audio weight) + audio x audio weight
    picture, weight = sharp["shots"][0]["score"], sharp["config"]["weight_audio"]
    assert sharp["score"] == pytest.approx(picture * (1 - weight) + 1.0 * weight, abs=0.0002)
    assert blurry["score"] == shot["score"]  # no audio: the picture score alone

    ranges = client.get(f"/api/media/{media['black_freeze.mp4']['id']}/quality").json()
    by_kind = {f["kind"]: f for f in ranges["flags"]}
    assert by_kind["black_frames"]["start_s"] == pytest.approx(2.0, abs=0.1)
    assert by_kind["frozen_frames"]["details"]["detector"] == "ffmpeg freezedetect"
    gap = client.get(f"/api/media/{media['gap.wav']['id']}/quality").json()
    assert gap["shots"] == [] and gap["audio"]["silence_s"] == pytest.approx(3.0, abs=0.05)
    assert gap["audio"]["silence_pct"] == pytest.approx(42.86, abs=1)
    assert gap["flags"][0]["details"]["value"] == pytest.approx(3.0, abs=0.05)
    assert client.get("/api/media/nope/quality").status_code == 404


def test_changed_threshold_rescores_from_the_cache(
    client: TestClient, api_settings: Settings, pid: str, qc_footage: Path
) -> None:
    api_settings.media_roots.append(qc_footage)
    import_one(client, pid, qc_footage / "sharp.mp4")
    media_id = str(_media(client, pid)["sharp.mp4"]["id"])
    drain(api_settings)
    before = client.get(f"/api/media/{media_id}/quality").json()
    assert before["flags"] == [] and before["score"] > 0.9

    # Declare every frame out of focus: no video is decoded again, only the scoring changes.
    api_settings.quality = QualityConfig(out_of_focus_blur_above=0.01, sharp_blur=0.0)
    stale = client.get(f"/api/media/{media_id}/quality").json()
    assert stale["settings_changed"] and stale["config"] == before["config"]  # not re-scored yet
    job = client.post(f"/api/media/{media_id}/process").json()
    drain(api_settings)
    stages = client.get(f"/api/jobs/{job['id']}").json()["stages"]
    assert [s["status"] for s in stages] == ["cached"] * 8
    after = client.get(f"/api/media/{media_id}/quality").json()
    assert [f["kind"] for f in after["flags"]] == ["out_of_focus"]
    assert not after["settings_changed"] and after["config"]["out_of_focus_blur_above"] == 0.01
    assert after["shots"][0]["sharpness_score"] == 0.0 and after["score"] < before["score"]
    assert after["shots"][0]["blur"] == before["shots"][0]["blur"]  # same measurement
    assert client.get(f"/api/media/{media_id}").json()["qc_flags"] == ["out_of_focus"]


def test_clip_score_follows_the_picture_even_when_audio_qc_fails(
    client: TestClient,
    api_settings: Settings,
    pid: str,
    qc_footage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api_settings.media_roots.append(qc_footage)
    import_one(client, pid, qc_footage / "sharp.mp4")
    drain(api_settings)
    media_id = str(_media(client, pid)["sharp.mp4"]["id"])
    assert client.get(f"/api/media/{media_id}").json()["quality_score"] > 0.9

    def crash(*_args: object) -> dict[str, Any]:
        raise RuntimeError("decoder died")

    # New thresholds, and a changed detector setting so both stages really run again.
    monkeypatch.setattr(qc, "count_clipped", crash)
    api_settings.quality = QualityConfig(
        out_of_focus_blur_above=0.01, sharp_blur=0.0, clip_sample_level=0.99
    )
    job = client.post(f"/api/media/{media_id}/process").json()
    drain(api_settings)
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "failed"
    media = client.get(f"/api/media/{media_id}").json()
    detail = client.get(f"/api/media/{media_id}/quality").json()
    assert detail["shots"][0]["sharpness_score"] == 0.0 and media["qc_flags"] == ["out_of_focus"]
    # the clip score was recomputed with the new picture score (and the audio row still there)
    assert media["quality_score"] == pytest.approx(
        detail["shots"][0]["score"] * 0.75 + 0.25, abs=0.001
    )


def test_undecodable_audio_is_reported_without_failing_the_clip(
    client: TestClient,
    api_settings: Settings,
    pid: str,
    qc_footage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cinemind.core.errors import UnreadableMediaError

    def unreadable(*_args: object) -> dict[str, Any]:
        raise UnreadableMediaError("The audio track could not be decoded for the quality check.")

    monkeypatch.setattr(qc, "count_clipped", unreadable)
    api_settings.media_roots.append(qc_footage)
    import_one(client, pid, qc_footage / "sharp.mp4")
    drain(api_settings)
    media = _media(client, pid)["sharp.mp4"]
    assert media["job"]["status"] == "succeeded" and media["qc_flags"] == ["audio_unreadable"]
    detail = client.get(f"/api/media/{media['id']}/quality").json()
    assert detail["audio"] is None and detail["score"] == detail["shots"][0]["score"]
    assert "could not be decoded" in detail["flags"][0]["details"]["reason"]
