"""Shots and keyframes (read-only; they are produced by the ingest chain)."""

from fastapi import APIRouter
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from cinemind.api.deps import SessionDep, SettingsDep
from cinemind.api.media import ERRORS, get_asset, get_project, serve_derived
from cinemind.api.schemas import ProjectShotOut, ShotOut
from cinemind.core.errors import NotFoundError
from cinemind.db.models import Keyframe, MediaAsset, Shot
from cinemind.rough_cut.assembly import natural_key

router = APIRouter(tags=["shots"])


@router.get(
    "/api/media/{media_id}/shots",
    response_model=list[ShotOut],
    responses=ERRORS,
    operation_id="listMediaShots",
)
def list_media_shots(media_id: str, session: SessionDep) -> list[Shot]:
    get_asset(session, media_id)
    query = (
        select(Shot)
        .where(Shot.media_id == media_id)
        .options(selectinload(Shot.keyframes))
        .order_by(Shot.index)
    )
    return list(session.scalars(query))


@router.get(
    "/api/projects/{project_id}/shots",
    response_model=list[ProjectShotOut],
    responses=ERRORS,
    operation_id="listProjectShots",
)
def list_project_shots(project_id: str, session: SessionDep) -> list[ProjectShotOut]:
    """Every shot in the project, clip by clip in the same file-name order timelines use."""
    get_project(session, project_id)
    query = (
        select(Shot, MediaAsset.filename)
        .join(MediaAsset, MediaAsset.id == Shot.media_id)
        .where(MediaAsset.project_id == project_id)
        .options(selectinload(Shot.keyframes))
    )
    rows = sorted(
        session.execute(query),
        key=lambda row: (natural_key(row[1]), row[0].media_id, row[0].index),
    )
    return [
        ProjectShotOut.model_validate({**ShotOut.model_validate(shot).model_dump(), "filename": n})
        for shot, n in rows
    ]


@router.get("/api/keyframes/{keyframe_id}/image", responses=ERRORS, operation_id="getKeyframe")
def get_keyframe(keyframe_id: str, session: SessionDep, settings: SettingsDep) -> FileResponse:
    keyframe = session.get(Keyframe, keyframe_id)
    if keyframe is None:
        raise NotFoundError("That keyframe does not exist. Reprocess the clip to recreate it.")
    return serve_derived(settings, get_asset(session, keyframe.media_id), keyframe.path, "keyframe")
