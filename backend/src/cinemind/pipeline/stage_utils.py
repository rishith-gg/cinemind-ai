"""Helpers shared by the stages of the ingest chain."""

from fractions import Fraction
from pathlib import Path

from sqlalchemy.orm import Session

from cinemind.core.errors import InvalidInputError, NotFoundError
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
