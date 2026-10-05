"""ffprobe wrapper: validates a file by content (not extension) and extracts metadata."""

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from cinemind.core.errors import ToolMissingError, UnreadableMediaError, UnsupportedMediaError

log = logging.getLogger(__name__)
# Formats that reference other files/URLs: reading them would escape the approved media roots.
_BLOCKED_FORMATS = {"hls", "applehttp", "concat", "sdp", "rtsp", "rtp", "ffconcat", "tee"}
_IMAGE_CODECS = {"mjpeg", "png", "bmp", "gif", "webp", "tiff", "jpeg2000", "jpegls"}


@dataclass
class MediaInfo:
    container: str
    duration_s: float
    has_video: bool
    has_audio: bool
    width: int | None = None  # display size (rotation applied)
    height: int | None = None
    fps: Fraction | None = None  # nominal rate as a rational, never a float
    is_vfr: bool = False
    video_codec: str | None = None
    audio_codec: str | None = None
    bit_rate: int | None = None
    audio_channels: int | None = None
    audio_sample_rate: int | None = None
    start_timecode: str | None = None
    color: dict[str, str] = field(default_factory=lambda: {})


def require_tool(name: str) -> str:
    exe = shutil.which(name)
    if exe is None:
        raise ToolMissingError(f"{name} was not found. Install FFmpeg, then run `cinemind doctor`.")
    return exe


def _rational(text: str | None) -> Fraction | None:
    if not text or "/" not in text:
        return None
    num, _, den = text.partition("/")
    try:
        value = Fraction(int(num), int(den))
    except (ValueError, ZeroDivisionError):
        return None
    return value if value > 0 else None


def _tag(obj: dict[str, Any], name: str) -> str | None:
    tags: dict[str, Any] = obj.get("tags") or {}
    value = tags.get(name)
    return str(value) if value else None


def _rotation(stream: dict[str, Any]) -> int:
    for side in stream.get("side_data_list", []):
        if "rotation" in side:
            return int(round(float(side["rotation"]))) % 360
    try:
        return int(_tag(stream, "rotate") or 0) % 360
    except ValueError:
        return 0


def run_ffprobe(path: Path) -> dict[str, Any]:
    exe = require_tool("ffprobe")
    cmd = [
        exe,
        "-v",
        "error",
        "-protocol_whitelist",
        "file",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)  # noqa: S603
    except subprocess.TimeoutExpired as exc:
        raise UnreadableMediaError("Reading this file took too long; it may be damaged.") from exc
    if proc.returncode != 0:
        log.warning("ffprobe failed for %s: %s", path.name, proc.stderr.strip()[:300])
        raise UnreadableMediaError(
            f"'{path.name}' could not be read as video or audio. It may be corrupt, "
            "incomplete, or not a media file."
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise UnreadableMediaError(f"'{path.name}' returned unreadable metadata.") from exc


def parse_probe(data: dict[str, Any], filename: str) -> MediaInfo:
    streams: list[dict[str, Any]] = data.get("streams", [])
    fmt: dict[str, Any] = data.get("format", {})
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        ),
        None,
    )
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None and audio is None:
        raise UnsupportedMediaError(f"'{filename}' has no video or audio stream.")
    try:
        duration = float(fmt.get("duration") or (video or audio or {}).get("duration") or 0)
    except ValueError:
        duration = 0.0
    format_name = str(fmt.get("format_name", ""))
    if _BLOCKED_FORMATS & set(format_name.split(",")):
        raise UnsupportedMediaError(
            f"'{filename}' is a playlist or stream description, not a media file."
        )
    if video and (
        "image2" in format_name
        or (video.get("codec_name") in _IMAGE_CODECS and duration < 0.05 and audio is None)
    ):
        raise UnsupportedMediaError(f"'{filename}' is a still image; CineMind imports footage.")
    if duration <= 0:
        raise UnreadableMediaError(f"'{filename}' has no readable duration; it may be incomplete.")

    info = MediaInfo(
        container=format_name.split(",")[0] or "unknown",
        duration_s=duration,
        has_video=video is not None,
        has_audio=audio is not None,
        bit_rate=int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None,
        start_timecode=_tag(fmt, "timecode"),
    )
    if video:
        width, height = int(video.get("width", 0)), int(video.get("height", 0))
        if _rotation(video) in (90, 270):
            width, height = height, width
        avg, nominal = _rational(video.get("avg_frame_rate")), _rational(video.get("r_frame_rate"))
        info.width, info.height = width, height
        info.fps = avg or nominal
        # VFR: average rate differs from the container's base rate by more than 0.5 %.
        info.is_vfr = bool(avg and nominal and abs(avg - nominal) / nominal > Fraction(1, 200))
        info.video_codec = video.get("codec_name")
        info.start_timecode = info.start_timecode or _tag(video, "timecode")
        info.color = {
            k: str(video[k])
            for k in ("pix_fmt", "color_space", "color_transfer", "color_primaries", "color_range")
            if video.get(k)
        }
    if audio:
        info.audio_codec = audio.get("codec_name")
        info.audio_channels = int(audio["channels"]) if audio.get("channels") else None
        rate = audio.get("sample_rate")
        info.audio_sample_rate = int(rate) if rate and str(rate).isdigit() else None
    return info


def probe(path: Path) -> MediaInfo:
    return parse_probe(run_ffprobe(path), path.name)
