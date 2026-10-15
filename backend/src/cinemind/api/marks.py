"""Selects, rejects and stars on shots."""

from fastapi import APIRouter

from cinemind.api.deps import SessionDep
from cinemind.api.media import ERRORS
from cinemind.api.search_schemas import MarkIn, MarkOut
from cinemind.pipeline import shot_marks

router = APIRouter(tags=["search"])


@router.put(
    "/api/shots/{shot_id}/mark",
    response_model=MarkOut,
    responses=ERRORS,
    operation_id="markShot",
)
def mark_shot(shot_id: str, body: MarkIn, session: SessionDep) -> MarkOut:
    """Select, reject or clear a shot, and set its stars. Rejected shots are left out of search
    unless asked for; selected and starred ones get the selection signal in the ranking."""
    row = shot_marks.set_mark(session, shot_id, body.mark, body.stars)
    session.commit()
    return MarkOut(
        shot_id=shot_id,
        mark=row.mark if row else None,  # pyright: ignore[reportArgumentType]
        stars=row.stars if row else 0,
    )
