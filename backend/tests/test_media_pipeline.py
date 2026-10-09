import json
import subprocess
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from cinemind.core.config import Settings
from cinemind.core.errors import UnreadableMediaError, UnsupportedMediaError
from cinemind.db.models import Job, MediaAsset, Project
from cinemind.jobs import queue
from cinemind.jobs.runner import run_job
from cinemind.pipeline import importer
from cinemind.pipeline.ffprobe import parse_probe, probe
from cinemind.pipeline.hashing import content_hash


def test_probe_metadata_and_rational_fps(footage: Path) -> None:
    info = probe(footage / "c_ntsc_noaudio.mkv")
    assert (info.width, info.height) == (640, 360)
    assert info.fps is not None and (info.fps.numerator, info.fps.denominator) == (30000, 1001)
    assert info.has_video and not info.has_audio and not info.is_vfr
    assert info.video_codec == "h264"

    mov = probe(footage / "b_prores.mov")
    assert mov.video_codec == "prores" and mov.has_audio and mov.audio_channels == 1

    wav = probe(footage / "d_audio.wav")
    assert not wav.has_video and wav.audio_sample_rate == 44100


def test_probe_detects_vfr(footage: Path) -> None:
    assert probe(footage / "e_vfr.mp4").is_vfr
    assert not probe(footage / "a_h264.mp4").is_vfr


def test_probe_rejects_corrupt_with_friendly_message(footage: Path) -> None:
    with pytest.raises(UnreadableMediaError) as err:
        probe(footage / "f_corrupt.mp4")
    assert "f_corrupt.mp4" in err.value.message and "corrupt" in err.value.message


def test_parse_probe_rejects_images_and_empty() -> None:
    with pytest.raises(UnsupportedMediaError):
        parse_probe({"streams": [], "format": {}}, "x.bin")
    still = {
        "streams": [{"codec_type": "video", "codec_name": "png", "width": 4, "height": 4}],
        "format": {"format_name": "png_pipe", "duration": "0.04"},
    }
    with pytest.raises(UnsupportedMediaError):
        parse_probe(still, "x.png")


def test_rotation_swaps_display_size() -> None:
    data = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30/1",
                "r_frame_rate": "30/1",
                "side_data_list": [{"rotation": -90}],
            }
        ],
        "format": {"format_name": "mov,mp4", "duration": "3.0"},
    }
    info = parse_probe(data, "phone.mov")
    assert (info.width, info.height) == (1080, 1920)


def test_content_hash_is_stable_and_content_sensitive(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"x" * 3_000_000)
    b.write_bytes(b"x" * 3_000_000)
    assert content_hash(a) == content_hash(b)
    b.write_bytes(b"x" * 2_999_999 + b"y")  # change inside the hashed tail
    assert content_hash(a) != content_hash(b)


# --- the ingest chain end to end -------------------------------------------------------------


def _ingest(
    factory: sessionmaker[Session], settings: Settings, project_id: str, source: Path
) -> tuple[str, str]:
    settings.media_roots = [source.parent]
    with factory() as s:
        result = importer.import_file(s, settings, project_id, source, "reference")
        assert result.asset
        asset_id = result.asset.id
        job_id = importer.enqueue_ingest(s, settings, result.asset).id
    assert queue.claim_next(factory) == job_id
    run_job(factory, settings, job_id)
    return asset_id, job_id


@pytest.fixture
def project(factory: sessionmaker[Session]) -> str:
    with factory() as s:
        p = Project(name="t")
        s.add(p)
        s.commit()
        return p.id


def test_ingest_produces_proxy_thumbs_waveform(
    factory: sessionmaker[Session], settings: Settings, project: str, footage: Path
) -> None:
    before = (footage / "b_prores.mov").read_bytes()
    asset_id, job_id = _ingest(factory, settings, project, footage / "b_prores.mov")
    with factory() as s:
        job = s.get(Job, job_id)
        asset = s.get(MediaAsset, asset_id)
        assert job and asset and job.status == "succeeded"
        assert [st.status for st in job.stages] == ["succeeded"] * 8
        assert asset.probed and asset.video_codec == "prores" and asset.duration_s
        root = settings.project_dir(project)
        assert asset.proxy_path and asset.poster_path and asset.strip_path and asset.waveform_path
        for rel in (asset.proxy_path, asset.poster_path, asset.strip_path, asset.waveform_path):
            assert (root / rel).stat().st_size > 0
        proxy = probe(root / asset.proxy_path)
        assert proxy.video_codec == "h264" and proxy.audio_codec == "aac"
        assert proxy.height is not None and proxy.height <= 720 and not proxy.is_vfr
        raw = (root / asset.proxy_path).read_bytes()
        assert raw.find(b"moov") < raw.find(b"mdat")  # +faststart
        wave = json.loads((root / asset.waveform_path).read_text())
        assert len(wave["peaks"]) == 1000 and max(wave["peaks"]) > 0.05
    assert (footage / "b_prores.mov").read_bytes() == before  # rule 2


def test_ingest_audio_only_and_no_audio(
    factory: sessionmaker[Session], settings: Settings, project: str, footage: Path
) -> None:
    wav_id, _ = _ingest(factory, settings, project, footage / "d_audio.wav")
    mkv_id, _ = _ingest(factory, settings, project, footage / "c_ntsc_noaudio.mkv")
    with factory() as s:
        wav, mkv = s.get(MediaAsset, wav_id), s.get(MediaAsset, mkv_id)
        assert wav and mkv
        assert wav.proxy_path and wav.proxy_path.endswith(".m4a") and wav.waveform_path
        assert wav.poster_path is None
        assert mkv.proxy_path and mkv.poster_path and mkv.waveform_path is None


def test_vfr_source_gets_constant_frame_rate_proxy(
    factory: sessionmaker[Session], settings: Settings, project: str, footage: Path
) -> None:
    asset_id, _ = _ingest(factory, settings, project, footage / "e_vfr.mp4")
    with factory() as s:
        asset = s.get(MediaAsset, asset_id)
        assert asset and asset.is_vfr and asset.proxy_path
        proxy = probe(settings.project_dir(project) / asset.proxy_path)
        assert not proxy.is_vfr


def test_corrupt_file_fails_with_friendly_error(
    factory: sessionmaker[Session], settings: Settings, project: str, footage: Path
) -> None:
    asset_id, job_id = _ingest(factory, settings, project, footage / "f_corrupt.mp4")
    with factory() as s:
        job = s.get(Job, job_id)
        asset = s.get(MediaAsset, asset_id)
        assert job and asset
        assert job.status == "failed" and job.error_code == "unreadable_media"
        assert job.error_message and "corrupt" in job.error_message
        assert not asset.probed and asset.proxy_path is None


def test_rerun_uses_cache_and_recreates_deleted_artifacts(
    factory: sessionmaker[Session], settings: Settings, project: str, footage: Path
) -> None:
    asset_id, _ = _ingest(factory, settings, project, footage / "a_h264.mp4")
    with factory() as s:
        asset = s.get(MediaAsset, asset_id)
        assert asset and asset.proxy_path
        job_id = importer.enqueue_ingest(s, settings, asset).id
    queue.claim_next(factory)
    run_job(factory, settings, job_id)
    with factory() as s:
        job = s.get(Job, job_id)
        assert job and [st.status for st in job.stages] == ["cached"] * 8

    proxy_file = settings.project_dir(project) / asset.proxy_path
    proxy_file.unlink()  # cached result must not be trusted when the file is gone
    with factory() as s:
        asset = s.get(MediaAsset, asset_id)
        assert asset
        job_id = importer.enqueue_ingest(s, settings, asset).id
    queue.claim_next(factory)
    run_job(factory, settings, job_id)
    with factory() as s:
        job = s.get(Job, job_id)
        assert job and [st.status for st in job.stages][:2] == ["cached", "succeeded"]
    assert proxy_file.is_file()


def test_missing_source_is_reported(
    factory: sessionmaker[Session], settings: Settings, project: str, footage: Path, tmp_path: Path
) -> None:
    src = tmp_path / "gone.mp4"
    src.write_bytes((footage / "a_h264.mp4").read_bytes())
    settings.media_roots = [tmp_path]
    with factory() as s:
        asset = importer.import_file(s, settings, project, src, "reference").asset
        assert asset
        src.unlink()
        job_id = importer.enqueue_ingest(s, settings, asset).id
    queue.claim_next(factory)
    run_job(factory, settings, job_id)
    with factory() as s:
        job = s.get(Job, job_id)
        assert job and job.error_code == "source_missing"


def test_encoder_list_always_ends_with_cpu_path() -> None:
    from cinemind.pipeline.ffmpeg import pick_encoders

    assert pick_encoders()[-1] == "libx264"
    proc = subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)  # noqa: S607
    assert proc.returncode == 0


def test_deleted_thumbnails_and_waveform_are_regenerated(
    factory: sessionmaker[Session], settings: Settings, project: str, footage: Path
) -> None:
    asset_id, _ = _ingest(factory, settings, project, footage / "a_h264.mp4")
    with factory() as s:
        asset = s.get(MediaAsset, asset_id)
        assert asset and asset.strip_path and asset.waveform_path
        root = settings.project_dir(project)
        (root / asset.strip_path).unlink()
        (root / asset.waveform_path).unlink()
        job_id = importer.enqueue_ingest(s, settings, asset).id
    queue.claim_next(factory)
    run_job(factory, settings, job_id)
    with factory() as s:
        job = s.get(Job, job_id)
        assert job and [st.status for st in job.stages] == [
            "cached", "cached", "succeeded", "succeeded", "cached", "cached", "cached", "cached"
        ]  # fmt: skip
    assert (root / asset.strip_path).is_file() and (root / asset.waveform_path).is_file()


def test_hardware_encoder_failure_falls_back_to_cpu(
    monkeypatch: pytest.MonkeyPatch, footage: Path, tmp_path: Path
) -> None:
    from cinemind.pipeline import ffmpeg

    monkeypatch.setattr(ffmpeg, "pick_encoders", lambda: ["h264_nvenc", "libx264"])
    used = ffmpeg.make_proxy(
        footage / "a_h264.mp4",
        tmp_path / "p.mp4",
        probe(footage / "a_h264.mp4"),
        720,
        lambda _f: None,
        lambda: None,
    )
    assert used == "libx264" and (tmp_path / "p.mp4").is_file()  # nvenc cannot run on this host
