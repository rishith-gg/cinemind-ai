"""QC detectors built on FFmpeg filters (existing tools; ours is the parsing and the flags):
black and frozen picture, loudness (EBU R128), silence, and clipped samples."""

import logging
import re
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from cinemind.core.errors import UnreadableMediaError
from cinemind.core.quality_config import QualityConfig
from cinemind.pipeline.ffmpeg import run_ffmpeg
from cinemind.pipeline.ffprobe import require_tool

log = logging.getLogger(__name__)

Progress = Callable[[float], None]
Check = Callable[[], None]

_NUM = r"(-?\d+(?:\.\d+)?)"
_BLACK = re.compile(rf"black_start:{_NUM} black_end:{_NUM}")
_FREEZE = re.compile(rf"freezedetect\.freeze_(start|end): {_NUM}")
_SILENCE = re.compile(rf"silence_(start|end): {_NUM}")
_LOUDNESS = re.compile(rf"\bI:\s+{_NUM} LUFS")
_RANGE = re.compile(rf"\bLRA:\s+{_NUM} LU")
_PEAK = re.compile(rf"\bPeak:\s+{_NUM} dBFS")
_READ_BYTES = 1 << 20
_DECODE_TIMEOUT_S = 3600
# Loudness needs a few complete 400 ms blocks; under this length "no reading" means "too short".
MIN_LOUDNESS_S = 1.0
ANALYSIS_FAILED = (
    "FFmpeg could not analyse this file. It may be corrupt or use an unsupported format."
)
LUFS_FLOOR = -70.0  # ffmpeg reports this when nothing was loud enough to measure


def detector_params(cfg: QualityConfig) -> dict[str, float]:
    """The settings the detectors run with (part of the stage cache key)."""
    return {
        "black_min_s": cfg.black_min_s,
        "black_pixel_threshold": cfg.black_pixel_threshold,
        "freeze_min_s": cfg.freeze_min_s,
        "freeze_noise_db": cfg.freeze_noise_db,
        "silence_noise_db": cfg.silence_noise_db,
        "long_silence_s": cfg.long_silence_s,
        "clip_sample_level": cfg.clip_sample_level,
    }


def _ranges(
    events: list[tuple[str, str]], duration_s: float, min_s: float = 0.0
) -> list[list[float]]:
    """Pair start/end events; a start without an end runs to the end of the file."""
    found: list[list[float]] = []
    start: float | None = None
    for kind, value in events:
        if kind == "start":
            start = float(value)
        elif start is not None:
            found.append([start, float(value)])
            start = None
    if start is not None:
        found.append([start, duration_s])
    clean = [[round(max(0.0, a), 3), round(min(duration_s, b), 3)] for a, b in found]
    return [r for r in clean if r[1] - r[0] >= min_s]


def _filter_lines(text: str, name: str) -> str:
    """Only the lines a filter itself logged ("[Parsed_<name>_0 @ ...] ..."). File metadata is
    printed to the same stream and must never be parsed as a detection."""
    return "\n".join(
        line for line in text.splitlines() if line.startswith("[") and name in line.split("]")[0]
    )


def detect_black_freeze(
    video: Path, duration_s: float, p: dict[str, float], progress: Progress, check: Check
) -> dict[str, list[list[float]]]:
    """Time ranges where the picture is black, or does not change."""
    filters = (
        f"blackdetect=d={p['black_min_s']}:pix_th={p['black_pixel_threshold']},"
        f"freezedetect=n={p['freeze_noise_db']}dB:d={p['freeze_min_s']}"
    )
    args = ["-protocol_whitelist", "file", "-i", str(video), "-an", "-vf", filters]
    out = run_ffmpeg(
        [*args, "-f", "null", "-"], duration_s, progress, check, "info", ANALYSIS_FAILED
    )
    black = [
        pair
        for a, b in _BLACK.findall(_filter_lines(out, "blackdetect"))
        for pair in (("start", a), ("end", b))
    ]
    return {
        "black": _ranges(black, duration_s),
        "frozen": _ranges(
            _FREEZE.findall(_filter_lines(out, "freezedetect")), duration_s, p["freeze_min_s"]
        ),
    }


def measure_loudness(
    source: Path, duration_s: float, p: dict[str, float], progress: Progress, check: Check
) -> dict[str, Any]:
    """Integrated loudness, loudness range, true peak and silent ranges of the first audio
    stream. `integrated_lufs` is None when there is no reading; `loudness_note` says why:
    "too_short" (not enough audio to gate) or "silent"."""
    filters = (
        "ebur128=peak=true:framelog=verbose,"
        f"silencedetect=noise={p['silence_noise_db']}dB:d={p['long_silence_s']}"
    )
    args = ["-protocol_whitelist", "file", "-i", str(source), "-map", "0:a:0", "-vn"]
    args += ["-af", filters, "-f", "null", "-"]
    out = run_ffmpeg(args, duration_s, progress, check, "info", ANALYSIS_FAILED)
    # The summary is the last thing the loudness filter prints, after its own "[Parsed_ebur128"
    # line; anything before that line (such as file metadata) is ignored.
    marker = out.rfind("[Parsed_ebur128")
    tail = out[marker:] if marker >= 0 else ""
    summary = tail[tail.find("Summary:") :] if "Summary:" in tail else ""

    def last(pattern: re.Pattern[str]) -> float | None:
        values = pattern.findall(summary)
        return float(values[-1]) if values else None

    loudness, peak = last(_LOUDNESS), last(_PEAK)
    measured = loudness is not None and loudness > LUFS_FLOOR
    note = None
    if not measured:
        audible = peak is not None and peak > p["silence_noise_db"]
        note = "too_short" if duration_s < MIN_LOUDNESS_S or audible else "silent"
    return {
        "integrated_lufs": loudness if measured else None,
        "loudness_note": note,
        "loudness_range": last(_RANGE),
        "true_peak_db": peak,
        "silences": _ranges(_SILENCE.findall(_filter_lines(out, "silencedetect")), duration_s),
    }


def count_clipped(source: Path, level: float, check: Check) -> dict[str, Any]:
    """Share of samples at (or within a hair of) full scale, decoded to 16-bit PCM. Samples
    above full scale in a float source count too (they clip when written as integers)."""
    cmd = [require_tool("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error"]
    cmd += ["-protocol_whitelist", "file", "-i", str(source), "-map", "0:a:0", "-vn"]
    cmd += ["-f", "s16le", "-c:a", "pcm_s16le", "-"]
    limit = int(level * 32767)
    total = clipped = peak = 0
    with tempfile.TemporaryFile("w+") as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=False)  # noqa: S603
        if proc.stdout is None:  # pragma: no cover - PIPE always provides it
            raise RuntimeError("ffmpeg stdout unavailable")
        # A stalled decoder (sleeping disk, damaged file) must not hang the worker for ever.
        watchdog = threading.Timer(_DECODE_TIMEOUT_S, proc.kill)
        watchdog.start()
        try:
            carry = b""
            while chunk := proc.stdout.read(_READ_BYTES):
                check()
                data = carry + chunk
                usable = len(data) - len(data) % 2
                carry = data[usable:]
                samples = np.abs(np.frombuffer(data[:usable], dtype="<i2").astype(np.int32))
                if samples.size:
                    total += int(samples.size)
                    clipped += int((samples >= limit).sum())
                    peak = max(peak, int(samples.max()))
        except BaseException:
            proc.kill()
            raise
        finally:
            watchdog.cancel()
            proc.stdout.close()
            code = proc.wait()
        if code != 0 or total == 0:
            err.seek(0)
            log.warning("audio decode failed for %s (%d): %s", source.name, code, err.read()[-300:])
            raise UnreadableMediaError(
                "The audio track could not be decoded for the quality check."
            )
    return {
        "samples": total,
        "clipped_pct": round(100.0 * clipped / total, 5),
        "sample_peak": round(min(1.0, peak / 32767), 5),
    }
