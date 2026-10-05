import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

import dummy_chain
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
