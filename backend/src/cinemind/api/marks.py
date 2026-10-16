"""Selects, rejects and stars on shots."""

import logging

from fastapi import APIRouter

from cinemind.api.deps import SessionDep, SettingsDep
from cinemind.api.media import ERRORS
from cinemind.api.search_schemas import MarkIn, MarkOut
from cinemind.pipeline import shot_marks, takes

log = logging.getLogger(__name__)
router = APIRouter(tags=["search"])


@router.put(
    "/api/shots/{shot_id}/mark",
    response_model=MarkOut,
    responses=ERRORS,
    operation_id="markShot",
)
def mark_shot(shot_id: str, body: MarkIn, session: SessionDep, settings: SettingsDep) -> MarkOut:
    """Select, reject or clear a shot, and set its stars. Rejected shots are left out of search
    unless asked for; selected and starred ones get the selection signal in the ranking. A
    rejected take is never the best of its take group, so a grouped shot's group is updated."""
    row = shot_marks.set_mark(session, shot_id, body.mark, body.stars)
    session.commit()
    project_id = takes.project_of_grouped_shot(session, shot_id)
    if project_id is not None:
        try:
            takes.regroup(session, settings, project_id)
            session.commit()
        except Exception:  # the mark is saved; the next grouping brings the group up to date
            session.rollback()
            log.exception("updating the take group of shot %s failed", shot_id)
    return MarkOut(
        shot_id=shot_id,
        mark=row.mark if row else None,  # pyright: ignore[reportArgumentType]
        stars=row.stars if row else 0,
    )
