"""Helpers shared by the stages of the ingest chain."""

from fractions import Fraction
from pathlib import Path

from sqlalchemy.orm import Session

from cinemind.core.errors import InvalidInputError, NotFoundError, PathNotAllowedError
from cinemind.core.paths import resolve_in_roots
from cinemind.db.models import MediaAsset
from cinemind.jobs.registry import StageContext
from cinemind.pipeline.ffprobe import MediaInfo


def project_dir(ctx: StageContext) -> Path:
    if ctx.project_id is None:
        raise InvalidInputError("The ingest chain needs a project.")
    return ctx.settings.project_dir(ctx.project_id)


def media_id(ctx: StageContext) -> str:
    if ctx.media_id is None:
        raise InvalidInputError("The ingest chain needs a media item.")
    return ctx.media_id


def exists(ctx: StageContext, rel: str | None) -> bool:
    return bool(rel) and (project_dir(ctx) / str(rel)).is_file()


def get_asset(session: Session, ctx: StageContext) -> MediaAsset:
    asset = session.get(MediaAsset, media_id(ctx))
    if asset is None:
        raise NotFoundError("The media item was removed while it was being processed.")
    return asset


def source_info(ctx: StageContext) -> MediaInfo:
    """The validate stage's result as a MediaInfo (only the fields later stages need)."""
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


def proxy_file(ctx: StageContext) -> Path:
    return project_dir(ctx) / ctx.previous["proxy"]["proxy"]


def checked_source(ctx: StageContext) -> Path:
    """The source must still be inside the approved roots (reference) or our own media dir
    (copy/upload): a symlink swapped in later, or a removed root, must not be read."""
    source = Path(str(ctx.params["source"]))
    if ctx.params.get("import_mode", "reference") == "reference":
        return resolve_in_roots(source, ctx.settings.media_roots) if source.exists() else source
    own = (project_dir(ctx) / "media").resolve()
    if source.exists() and not source.resolve().is_relative_to(own):
        raise PathNotAllowedError("That file is outside the project's media folder.")
    return source
