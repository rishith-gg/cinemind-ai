import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

import dummy_chain
from cinemind.api.app import create_app
from cinemind.core.config import Settings
from cinemind.db.base import make_engine, make_session_factory
from cinemind.db.migrate import upgrade_head

# Importing registers the test-only chains.
REGISTERED_CHAINS = dummy_chain.__name__


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        media_roots=[],
        worker_poll_seconds=0.05,
        extra_stage_modules=["dummy_chain"],
    )


@pytest.fixture
def factory(settings: Settings) -> Iterator[sessionmaker[Session]]:
    upgrade_head(settings.db_path)
    engine = make_engine(settings.db_path)
    yield make_session_factory(engine)
    engine.dispose()


def _ffmpeg(*args: str) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)  # noqa: S603, S607


@pytest.fixture(scope="session")
def footage(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Tiny synthetic clips in mixed formats (generated with ffmpeg; no real footage)."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    root = tmp_path_factory.mktemp("footage")
    video = ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=2"]
    tone = ["-f", "lavfi", "-i", "sine=frequency=440:duration=2"]
    _ffmpeg(*video, *tone, "-c:v", "libx264", "-c:a", "aac", "-shortest", str(root / "a_h264.mp4"))
    # ProRes in MOV: browsers cannot play it, so it must go through the proxy.
    _ffmpeg(*video, *tone, "-c:v", "prores_ks", "-c:a", "pcm_s16le", str(root / "b_prores.mov"))
    ntsc = ["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30000/1001:duration=2"]
    _ffmpeg(*ntsc, "-c:v", "libx264", str(root / "c_ntsc_noaudio.mkv"))
    _ffmpeg(*tone, str(root / "d_audio.wav"))
    # Variable frame rate: drop every third frame but keep the original timestamps.
    _ffmpeg(
        *video,
        "-vf",
        "select=not(mod(n\\,3))",
        "-fps_mode",
        "vfr",
        "-c:v",
        "libx264",
        str(root / "e_vfr.mp4"),
    )
    (root / "f_corrupt.mp4").write_bytes(os.urandom(4096))
    (root / "notes.txt").write_text("not media")
    return root


@pytest.fixture
def api_settings(settings: Settings, footage: Path) -> Settings:
    settings.media_roots = [footage]
    settings.max_upload_mb = 1
    return settings


@pytest.fixture
def client(api_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(frontend_dist=None, settings=api_settings)) as c:
        yield c


@pytest.fixture
def pid(client: TestClient) -> str:
    return client.post("/api/projects", json={"name": "p"}).json()["id"]


# Cut positions (seconds) of `cuts.mp4`: four visually distinct segments at 25 fps.
CUTS_S = (2.0, 3.52, 6.0)
CUTS_DURATION_S = 8.0


@pytest.fixture(scope="session")
def cut_footage(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Clips with exactly known shot boundaries (ground truth for shot detection)."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    root = tmp_path_factory.mktemp("cuts")
    size = "size=640x360:rate=25"
    graph = "[2:v]trim=duration=2.48,setpts=PTS-STARTPTS[m];[0:v][1:v][m][3:v]concat=n=4:v=1[v]"
    _ffmpeg(
        *("-f", "lavfi", "-i", f"testsrc2={size}:duration=2"),
        *("-f", "lavfi", "-i", f"smptebars={size}:duration=1.52"),
        *("-f", "lavfi", "-i", f"mandelbrot={size}"),
        *("-f", "lavfi", "-i", f"color=c=darkblue:{size}:duration=2"),
        *("-f", "lavfi", "-i", "sine=frequency=330:duration=8"),
        *("-filter_complex", graph, "-map", "[v]", "-map", "4:a", "-ac", "2"),
        *("-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(root / "cuts.mp4")),
    )
    # One continuous shot at 29.97 fps with a drop-frame start timecode, no audio.
    _ffmpeg(
        *("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30000/1001:duration=3"),
        *("-c:v", "libx264", "-pix_fmt", "yuv420p", "-timecode", "01:00:00;00"),
        str(root / "one_shot_ntsc.mov"),
    )
    return root


@pytest.fixture(scope="session")
def qc_footage(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Clips with one known technical property each (ground truth for the quality checks)."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    root = tmp_path_factory.mktemp("qc")
    size = "size=640x360:rate=25"
    picture = ("-f", "lavfi", "-i", f"testsrc2={size}:duration=3")
    tone = ("-f", "lavfi", "-i", "sine=frequency=440:duration=3")
    h264 = ("-c:v", "libx264", "-pix_fmt", "yuv420p")
    _ffmpeg(*picture, *tone, *h264, "-c:a", "aac", str(root / "sharp.mp4"))
    for name, vf in (
        ("blurry.mp4", "gblur=sigma=8"),
        ("over.mp4", "eq=brightness=0.5"),
        ("under.mp4", "lutyuv=y=val/5"),
    ):
        _ffmpeg(*picture, "-vf", vf, *h264, str(root / name))
    # 2 s moving picture, 1.5 s black, 1 s moving picture, then its last frame held for 3 s.
    graph = (
        "[2:v]trim=duration=1,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=3[tail];"
        "[0:v][1:v][tail]concat=n=3:v=1[v]"
    )
    _ffmpeg(
        *("-f", "lavfi", "-i", f"testsrc2={size}:duration=2"),
        *("-f", "lavfi", "-i", f"color=c=black:{size}:duration=1.5"),
        *("-f", "lavfi", "-i", f"testsrc2={size}:duration=2"),
        *("-filter_complex", graph, "-map", "[v]", *h264, str(root / "black_freeze.mp4")),
    )
    # 2 s tone, 3 s digital silence, 2 s tone.
    _ffmpeg(
        *("-f", "lavfi", "-i", "sine=frequency=440:duration=2"),
        *("-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono"),
        *("-f", "lavfi", "-i", "sine=frequency=440:duration=2"),
        *("-filter_complex", "[1:a]atrim=duration=3[s];[0:a][s][2:a]concat=n=3:v=0:a=1[a]"),
        *("-map", "[a]", str(root / "gap.wav")),
    )
    _ffmpeg(*tone, "-af", "volume=30dB", str(root / "clipped.wav"))
    _ffmpeg(*tone, "-af", "volume=-45dB", str(root / "quiet.wav"))
    return root
