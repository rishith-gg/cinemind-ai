"""The `ingest` chain: validate -> proxy -> thumbnails -> waveform (SPEC sections 4 and 5).

Stages return plain dicts (cached in `stage_results`); the `persist_*` functions copy them onto
the media asset row. Artifact paths are stored relative to the project directory.
"""

import json
import shutil
from fractions import Fraction
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from cinemind.core.errors import (
    InvalidInputError,
    LowDiskSpaceError,
    NotFoundError,
    PathNotAllowedError,
    SourceMissingError,
)
from cinemind.core.paths import resolve_in_roots
from cinemind.db.models import MediaAsset
from cinemind.jobs.registry import Stage, StageContext, register_chain
from cinemind.pipeline import ffmpeg
from cinemind.pipeline.ffmpeg import make_proxy, make_thumbnails, waveform_peaks
from cinemind.pipeline.ffprobe import MediaInfo, probe

PIPELINE_VERSION = "1"
_PROXY_MBIT = 4  # generous upper bound for proxy bitrate when estimating disk use
_MIN_FREE_BYTES = 500 * 1024 * 1024


def _project_dir(ctx: StageContext) -> Path:
    if ctx.project_id is None:
        raise InvalidInputError("The ingest chain needs a project.")
    return ctx.settings.project_dir(ctx.project_id)


def _media_id(ctx: StageContext) -> str:
    if ctx.media_id is None:
        raise InvalidInputError("The ingest chain needs a media item.")
    return ctx.media_id


def _artifact(ctx: StageContext, kind: str, suffix: str) -> tuple[str, Path]:
    folder = {"proxy": "proxies", "poster": "thumbnails", "strip": "thumbnails", "wave": "audio"}
    rel = f"{folder[kind]}/{_media_id(ctx)}_{kind}{suffix}"
    return rel, _project_dir(ctx) / rel


def _exists(ctx: StageContext, rel: str | None) -> bool:
    return bool(rel) and (_project_dir(ctx) / str(rel)).is_file()


# --- validate ---------------------------------------------------------------------------------


def _checked_source(ctx: StageContext) -> Path:
    """The source must still be inside the approved roots (reference) or our own media dir
    (copy/upload): a symlink swapped in later, or a removed root, must not be read."""
    source = Path(str(ctx.params["source"]))
    if ctx.params.get("import_mode", "reference") == "reference":
        return resolve_in_roots(source, ctx.settings.media_roots) if source.exists() else source
    own = (_project_dir(ctx) / "media").resolve()
    if source.exists() and not source.resolve().is_relative_to(own):
        raise PathNotAllowedError("That file is outside the project's media folder.")
    return source


def verify_validate(ctx: StageContext, _result: dict[str, Any]) -> bool:
    """A cached probe is only reused while the original is still where we expect it."""
    return Path(str(ctx.params["source"])).is_file()


def run_validate(ctx: StageContext) -> dict[str, Any]:
    source = _checked_source(ctx)
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
    asset = _asset(session, ctx)
    fps = result["fps"] or [None, None]
    asset.probed = True
    asset.container, asset.duration_s = result["container"], result["duration_s"]
    asset.width, asset.height = result["width"], result["height"]
    asset.fps_num, asset.fps_den = fps
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


def _asset(session: Session, ctx: StageContext) -> MediaAsset:
    asset = session.get(MediaAsset, _media_id(ctx))
    if asset is None:
        raise NotFoundError("The media item was removed while it was being processed.")
    return asset


def _info(ctx: StageContext) -> MediaInfo:
    meta = ctx.previous["validate"]
    return MediaInfo(
        container=meta["container"],
        duration_s=meta["duration_s"],
        has_video=meta["has_video"],
        has_audio=meta["has_audio"],
        width=meta["width"],
        height=meta["height"],
        fps=Fraction(*meta["fps"]) if meta["fps"] else None,
    )


# --- proxy ------------------------------------------------------------------------------------


def run_proxy(ctx: StageContext) -> dict[str, Any]:
    info = _info(ctx)
    source = _checked_source(ctx)
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
    return _exists(ctx, result.get("proxy"))


def persist_proxy(session: Session, ctx: StageContext, result: dict[str, Any]) -> None:
    asset = _asset(session, ctx)
    asset.proxy_path = result["proxy"]
    asset.artifacts = {**asset.artifacts, "proxy": {k: result[k] for k in ("encoder", "fps")}}


# --- thumbnails -------------------------------------------------------------------------------


def run_thumbnails(ctx: StageContext) -> dict[str, Any]:
    info = _info(ctx)
    if not info.has_video:
        return {"poster": None, "strip": None, "strip_frames": 0}
    proxy = _project_dir(ctx) / ctx.previous["proxy"]["proxy"]
    poster_rel, poster = _artifact(ctx, "poster", ".jpg")
    strip_rel, strip = _artifact(ctx, "strip", ".jpg")
    frames = make_thumbnails(proxy, poster, strip, info.duration_s)
    return {"poster": poster_rel, "strip": strip_rel, "strip_frames": frames}


def verify_thumbnails(ctx: StageContext, result: dict[str, Any]) -> bool:
    return result["poster"] is None or (
        _exists(ctx, result["poster"]) and _exists(ctx, result["strip"])
    )


def persist_thumbnails(session: Session, ctx: StageContext, result: dict[str, Any]) -> None:
    asset = _asset(session, ctx)
    asset.poster_path, asset.strip_path = result["poster"], result["strip"]
    asset.artifacts = {**asset.artifacts, "strip_frames": result["strip_frames"]}


# --- waveform ---------------------------------------------------------------------------------


def run_waveform(ctx: StageContext) -> dict[str, Any]:
    info = _info(ctx)
    if not info.has_audio:
        return {"waveform": None}
    proxy = _project_dir(ctx) / ctx.previous["proxy"]["proxy"]
    rel, dest = _artifact(ctx, "wave", ".json")
    peaks = waveform_peaks(proxy)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".partial")
    tmp.write_text(json.dumps({"duration": info.duration_s, "peaks": peaks}))
    tmp.replace(dest)
    return {"waveform": rel}


def verify_waveform(ctx: StageContext, result: dict[str, Any]) -> bool:
    return result["waveform"] is None or _exists(ctx, result["waveform"])


def persist_waveform(session: Session, ctx: StageContext, result: dict[str, Any]) -> None:
    _asset(session, ctx).waveform_path = result["waveform"]


register_chain(
    "ingest",
    [
        Stage(
            "validate",
            run_validate,
            model_name="ffprobe",
            model_version=PIPELINE_VERSION,
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
    ],
)
