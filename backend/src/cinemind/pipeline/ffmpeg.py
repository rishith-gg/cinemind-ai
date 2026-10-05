"""FFmpeg jobs (argument lists only, never a shell): proxy, thumbnails, waveform peaks."""

import contextlib
import logging
import subprocess
import tempfile
from array import array
from collections.abc import Callable
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from cinemind.core.errors import DomainError, JobCancelled, UnreadableMediaError
from cinemind.pipeline.ffprobe import MediaInfo, require_tool

log = logging.getLogger(__name__)

# Hardware H.264 encoders in order of preference; libx264 is the CPU path (always available).
_HW_ENCODERS = ("h264_nvenc", "h264_videotoolbox", "h264_qsv")
WAVEFORM_BINS = 1000
WAVEFORM_RATE = 8000
STRIP_FRAMES = 20
STRIP_TILE_HEIGHT = 90
POSTER_HEIGHT = 360
PROXY_CRF = 23
PROXY_PRESET = "veryfast"
GOP_SECONDS = 2


@lru_cache
def available_encoders() -> frozenset[str]:
    proc = subprocess.run(  # noqa: S603
        [require_tool("ffmpeg"), "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return frozenset(
        parts[1] for line in proc.stdout.splitlines() if len(parts := line.split()) > 1
    )


def pick_encoders() -> list[str]:
    """Encoders to try in order. A listed hardware encoder may still fail at runtime
    (no GPU), so the caller falls back through the list down to libx264."""
    have = available_encoders()
    return [e for e in _HW_ENCODERS if e in have] + ["libx264"]


def proxy_fps(info: MediaInfo) -> Fraction:
    """Constant frame rate for the proxy: the nominal rate, halved above 60 fps."""
    fps = info.fps or Fraction(30)
    return fps / 2 if fps > 60 else fps


def _even(value: int) -> int:
    return max(2, value - value % 2)


def proxy_height(info: MediaInfo, max_height: int) -> int:
    return _even(min(info.height or max_height, max_height))


def _video_args(encoder: str) -> list[str]:
    if encoder == "libx264":
        return ["-c:v", "libx264", "-preset", PROXY_PRESET, "-crf", str(PROXY_CRF)]
    if encoder == "h264_nvenc":
        return ["-c:v", encoder, "-preset", "p4", "-cq", "26", "-b:v", "0"]
    return ["-c:v", encoder, "-b:v", "3M"]


def run_ffmpeg(
    args: list[str],
    duration_s: float,
    progress: Callable[[float], None],
    check_cancelled: Callable[[], None],
) -> None:
    """Run ffmpeg with `-progress`, reporting 0..1 and honouring cancellation."""
    cmd = [require_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
    cmd += ["-progress", "pipe:1", "-nostats", *args]
    with tempfile.TemporaryFile("w+") as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True)  # noqa: S603
        if proc.stdout is None:  # pragma: no cover - PIPE always provides it
            raise RuntimeError("ffmpeg stdout unavailable")
        try:
            for line in proc.stdout:
                if line.startswith("out_time_us="):
                    with contextlib.suppress(ValueError):
                        progress(int(line.split("=", 1)[1]) / 1e6 / max(duration_s, 0.001))
                check_cancelled()
        except JobCancelled:
            proc.kill()
            proc.wait()
            raise
        finally:
            proc.stdout.close()
        code = proc.wait()
        if code != 0:
            err.seek(0)
            tail = err.read()[-500:].strip()
            log.warning("ffmpeg failed (%d): %s", code, tail)
            raise UnreadableMediaError(
                "FFmpeg could not convert this file. It may be corrupt or use an unsupported "
                "format."
            )


def make_proxy(
    src: Path,
    dest: Path,
    info: MediaInfo,
    max_height: int,
    progress: Callable[[float], None],
    check_cancelled: Callable[[], None],
) -> str:
    """Write the browser-playable proxy to `dest` atomically. Returns the encoder used."""
    tmp = dest.with_name(dest.stem + ".partial" + dest.suffix)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not info.has_video:
        args = [
            "-protocol_whitelist",
            "file",
            "-i",
            str(src),
            "-vn",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ac",
            "2",
        ]
        args += ["-movflags", "+faststart", "-f", "ipod", str(tmp)]
        run_ffmpeg(args, info.duration_s, progress, check_cancelled)
        tmp.replace(dest)
        return "aac"
    fps = proxy_fps(info)
    vf = f"fps={fps.numerator}/{fps.denominator},scale=-2:{proxy_height(info, max_height)}"
    gop = str(max(1, round(float(fps) * GOP_SECONDS)))
    last_error: DomainError | None = None
    for encoder in pick_encoders():
        args = [
            "-protocol_whitelist",
            "file",
            "-i",
            str(src),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            vf,
        ]
        args += [*_video_args(encoder), "-pix_fmt", "yuv420p", "-g", gop]
        args += ["-c:a", "aac", "-b:a", "128k", "-ac", "2"]
        args += ["-movflags", "+faststart", "-f", "mp4", str(tmp)]
        try:
            run_ffmpeg(args, info.duration_s, progress, check_cancelled)
        except UnreadableMediaError as exc:
            last_error = exc
            tmp.unlink(missing_ok=True)
            log.info("encoder %s failed, trying the next one", encoder)
            continue
        tmp.replace(dest)
        return encoder
    raise last_error or UnreadableMediaError("FFmpeg could not convert this file.")


def _extract(args: list[str]) -> None:
    run_ffmpeg(args, 1.0, lambda _f: None, lambda: None)


def make_thumbnails(proxy: Path, poster: Path, strip: Path, duration_s: float) -> int:
    """Poster frame plus a horizontal strip of evenly spaced frames. Returns the strip frames."""
    poster.parent.mkdir(parents=True, exist_ok=True)
    seek = f"{min(1.0, duration_s / 4):.3f}"
    poster_tmp = poster.with_name("partial_" + poster.name)
    _extract(
        [
            "-ss",
            seek,
            "-i",
            str(proxy),
            "-frames:v",
            "1",
            "-vf",
            f"scale=-2:{POSTER_HEIGHT}",
            str(poster_tmp),
        ]
    )
    poster_tmp.replace(poster)
    frames = max(1, min(STRIP_FRAMES, int(duration_s)))
    rate = frames / duration_s
    strip_tmp = strip.with_name("partial_" + strip.name)
    vf = f"fps={rate:.6f},scale=-2:{STRIP_TILE_HEIGHT},tile={frames}x1"
    _extract(["-i", str(proxy), "-vf", vf, "-frames:v", "1", str(strip_tmp)])
    strip_tmp.replace(strip)
    return frames


def waveform_peaks(src: Path, bins: int = WAVEFORM_BINS) -> list[float]:
    """Mono peak envelope in 0..1 (one value per bin) decoded from the first audio stream."""
    cmd = [require_tool("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error"]
    cmd += ["-protocol_whitelist", "file", "-i", str(src)]
    cmd += ["-map", "0:a:0", "-ac", "1", "-ar", str(WAVEFORM_RATE), "-f", "s16le", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=3600, check=False)  # noqa: S603
    except subprocess.TimeoutExpired as exc:
        raise UnreadableMediaError(
            "Decoding the audio took too long; the file may be damaged."
        ) from exc
    if proc.returncode != 0:
        raise UnreadableMediaError("The audio track could not be decoded for the waveform.")
    samples = array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    if not samples:
        return [0.0] * bins
    step = max(1, len(samples) // bins)
    peaks = [
        max(abs(min(chunk)), abs(max(chunk))) / 32768
        for i in range(0, step * bins, step)
        if (chunk := samples[i : i + step])
    ]
    return [round(p, 4) for p in peaks] + [0.0] * (bins - len(peaks))
