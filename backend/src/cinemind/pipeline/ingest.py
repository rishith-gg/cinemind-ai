"""The `ingest` chain: validate -> proxy -> thumbnails -> waveform -> shots -> keyframes
-> quality -> audio_qc -> transcribe (SPEC sections 4 and 5; the later ones live in
`shot_stages.py`, `quality_stages.py` and `transcribe_stages.py`).

Stages return plain dicts (cached in `stage_results`); the `persist_*` functions copy them onto
the media asset row. Artifact paths are stored relative to the project directory.
"""

import json
import shutil
from fractions import Fraction
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from cinemind.core.errors import LowDiskSpaceError, SourceMissingError
from cinemind.jobs.registry import Stage, StageContext, register_chain
from cinemind.pipeline import ffmpeg
from cinemind.pipeline.ffmpeg import make_proxy, make_thumbnails, waveform_peaks
from cinemind.pipeline.ffprobe import probe
from cinemind.pipeline.quality_stages import QUALITY_STAGES
from cinemind.pipeline.shot_stages import SHOT_STAGES
from cinemind.pipeline.stage_utils import (
    checked_source,
    exists,
    get_asset,
    media_id,
    project_dir,
    proxy_file,
    source_info,
)
from cinemind.pipeline.transcribe_stages import TRANSCRIBE_STAGES

PIPELINE_VERSION = "1"
_PROXY_MBIT = 4  # generous upper bound for proxy bitrate when estimating disk use
_MIN_FREE_BYTES = 500 * 1024 * 1024


def _artifact(ctx: StageContext, kind: str, suffix: str) -> tuple[str, Path]:
    folder = {"proxy": "proxies", "poster": "thumbnails", "strip": "thumbnails", "wave": "audio"}
    rel = f"{folder[kind]}/{media_id(ctx)}_{kind}{suffix}"
    return rel, project_dir(ctx) / rel


# --- validate ---------------------------------------------------------------------------------


def verify_validate(ctx: StageContext, _result: dict[str, Any]) -> bool:
    """A cached probe is only reused while the original is still where we expect it."""
    return Path(str(ctx.params["source"])).is_file()


def _pair(rate: Fraction | None) -> list[int] | None:
    return [rate.numerator, rate.denominator] if rate else None


def run_validate(ctx: StageContext) -> dict[str, Any]:
    source = checked_source(ctx)
    if not source.is_file():
        raise SourceMissingError(
            f"The original file '{source.name}' is missing or was moved. Relink it to continue."
        )
    info = probe(source)
    return {
        "container": info.container,
        "duration_s": info.duration_s,
        "has_video": info.has_video,
        "has_audio": info.has_audio,
        "width": info.width,
        "height": info.height,
        "fps": [info.fps.numerator, info.fps.denominator] if info.fps else None,
        "nominal_fps": _pair(info.nominal_fps),
        "is_vfr": info.is_vfr,
        "video_codec": info.video_codec,
        "audio_codec": info.audio_codec,
        "bit_rate": info.bit_rate,
        "audio_channels": info.audio_channels,
        "audio_sample_rate": info.audio_sample_rate,
        "start_timecode": info.start_timecode,
        "color": info.color,
    }


def persist_validate(session: Session, ctx: StageContext, result: dict[str, Any]) -> None:
    asset = get_asset(session, ctx)
    fps = result["fps"] or [None, None]
    asset.probed = True
    asset.container, asset.duration_s = result["container"], result["duration_s"]
    asset.width, asset.height = result["width"], result["height"]
    asset.fps_num, asset.fps_den = fps
    asset.nominal_fps_num, asset.nominal_fps_den = result.get("nominal_fps") or [None, None]
    for name in (
        "is_vfr",
        "video_codec",
        "audio_codec",
        "bit_rate",
        "audio_channels",
        "audio_sample_rate",
        "start_timecode",
        "color",
    ):
        setattr(asset, name, result[name])


# --- proxy ------------------------------------------------------------------------------------


def run_proxy(ctx: StageContext) -> dict[str, Any]:
    info = source_info(ctx)
    source = checked_source(ctx)
    rel, dest = _artifact(ctx, "proxy", ".mp4" if info.has_video else ".m4a")
    dest.parent.mkdir(parents=True, exist_ok=True)
    needed = int(info.duration_s * _PROXY_MBIT * 125_000) + _MIN_FREE_BYTES
    if shutil.disk_usage(dest.parent).free < needed:
        raise LowDiskSpaceError(
            "There is not enough free disk space to create the proxy. Free up space and retry."
        )
    max_height = int(ctx.params.get("proxy_max_height", ctx.settings.proxy_max_height))
    encoder = make_proxy(
        source,
        dest,
        info,
        max_height,
        ctx.progress,
        ctx.check_cancelled,
    )
    fps = ffmpeg.proxy_fps(info) if info.has_video else None
    return {
        "proxy": rel,
        "encoder": encoder,
        "fps": [fps.numerator, fps.denominator] if fps else None,
        "height": ffmpeg.proxy_height(info, max_height) if info.has_video else None,
    }


def verify_proxy(ctx: StageContext, result: dict[str, Any]) -> bool:
    return exists(ctx, result.get("proxy"))


def persist_proxy(session: Session, ctx: StageContext, result: dict[str, Any]) -> None:
    asset = get_asset(session, ctx)
    asset.proxy_path = result["proxy"]
    asset.artifacts = {**asset.artifacts, "proxy": {k: result[k] for k in ("encoder", "fps")}}


# --- thumbnails -------------------------------------------------------------------------------


def run_thumbnails(ctx: StageContext) -> dict[str, Any]:
    info = source_info(ctx)
    if not info.has_video:
        return {"poster": None, "strip": None, "strip_frames": 0}
    proxy = proxy_file(ctx)
    poster_rel, poster = _artifact(ctx, "poster", ".jpg")
    strip_rel, strip = _artifact(ctx, "strip", ".jpg")
    frames = make_thumbnails(proxy, poster, strip, info.duration_s)
    return {"poster": poster_rel, "strip": strip_rel, "strip_frames": frames}


def verify_thumbnails(ctx: StageContext, result: dict[str, Any]) -> bool:
    return result["poster"] is None or (
        exists(ctx, result["poster"]) and exists(ctx, result["strip"])
    )


def persist_thumbnails(session: Session, ctx: StageContext, result: dict[str, Any]) -> None:
    asset = get_asset(session, ctx)
    asset.poster_path, asset.strip_path = result["poster"], result["strip"]
    asset.artifacts = {**asset.artifacts, "strip_frames": result["strip_frames"]}


# --- waveform ---------------------------------------------------------------------------------


def run_waveform(ctx: StageContext) -> dict[str, Any]:
    info = source_info(ctx)
    if not info.has_audio:
        return {"waveform": None}
    proxy = proxy_file(ctx)
    rel, dest = _artifact(ctx, "wave", ".json")
    peaks = waveform_peaks(proxy)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".partial")
    tmp.write_text(json.dumps({"duration": info.duration_s, "peaks": peaks}))
    tmp.replace(dest)
    return {"waveform": rel}


def verify_waveform(ctx: StageContext, result: dict[str, Any]) -> bool:
    return result["waveform"] is None or exists(ctx, result["waveform"])


def persist_waveform(session: Session, ctx: StageContext, result: dict[str, Any]) -> None:
    get_asset(session, ctx).waveform_path = result["waveform"]


register_chain(
    "ingest",
    [
        Stage(
            "validate",
            run_validate,
            model_name="ffprobe",
            model_version="2",  # 2: also records the nominal frame rate
            param_keys=(),
            verify=verify_validate,
            persist=persist_validate,
        ),
        Stage(
            "proxy",
            run_proxy,
            model_name="ffmpeg",
            model_version=PIPELINE_VERSION,
            params={
                "crf": ffmpeg.PROXY_CRF,
                "preset": ffmpeg.PROXY_PRESET,
                "gop_s": ffmpeg.GOP_SECONDS,
            },
            param_keys=("proxy_max_height",),
            scope_project=True,
            verify=verify_proxy,
            persist=persist_proxy,
        ),
        Stage(
            "thumbnails",
            run_thumbnails,
            model_name="ffmpeg",
            model_version=PIPELINE_VERSION,
            params={
                "strip_frames": ffmpeg.STRIP_FRAMES,
                "tile_height": ffmpeg.STRIP_TILE_HEIGHT,
                "poster_height": ffmpeg.POSTER_HEIGHT,
            },
            param_keys=(),
            scope_project=True,
            verify=verify_thumbnails,
            persist=persist_thumbnails,
        ),
        Stage(
            "waveform",
            run_waveform,
            model_name="ffmpeg",
            model_version=PIPELINE_VERSION,
            params={"bins": ffmpeg.WAVEFORM_BINS, "rate": ffmpeg.WAVEFORM_RATE},
            param_keys=(),
            scope_project=True,
            verify=verify_waveform,
            persist=persist_waveform,
        ),
        *SHOT_STAGES,
        *QUALITY_STAGES,
        *TRANSCRIBE_STAGES,
    ],
)
