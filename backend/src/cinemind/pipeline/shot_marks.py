"""The user's selects, rejects and stars on shots (SPEC section 9). Every change is also written
to the feedback log, with the previous state, for a later learned re-weighting."""

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from cinemind.core.errors import InvalidInputError, NotFoundError
from cinemind.db.analysis import ShotMark
from cinemind.db.base import utcnow
from cinemind.db.models import MediaAsset, Shot
from cinemind.db.people import FeedbackEvent


def marks_for(session: Session, shot_ids: list[str]) -> dict[str, ShotMark]:
    if not shot_ids:
        return {}
    return {
        m.shot_id: m
        for m in session.scalars(select(ShotMark).where(ShotMark.shot_id.in_(shot_ids)))
    }


def rejected(session: Session, project_id: str) -> set[str]:
    query = select(ShotMark.shot_id).where(
        ShotMark.project_id == project_id, ShotMark.mark == "reject"
    )
    return set(session.scalars(query))


def selected(session: Session, project_id: str) -> set[str]:
    query = select(ShotMark.shot_id).where(
        ShotMark.project_id == project_id, ShotMark.mark == "select"
    )
    return set(session.scalars(query))


def set_mark(
    session: Session, shot_id: str, mark: str | None = None, stars: int | None = None
) -> ShotMark | None:
    """Set a shot's mark ("select", "reject", or "none" to clear; None keeps it) and stars (0..5;
    None keeps them). A shot with no mark and no stars has no row. One upsert statement, so two
    quick clicks cannot both insert. The caller commits."""
    if mark not in (None, "select", "reject", "none"):
        raise InvalidInputError("The mark must be select, reject or none.")
    if stars is not None and not 0 <= stars <= 5:
        raise InvalidInputError("Stars go from 0 to 5.")
    shot = session.get(Shot, shot_id)
    asset = session.get(MediaAsset, shot.media_id) if shot else None
    if shot is None or asset is None:
        raise NotFoundError("That shot does not exist any more. Reload the page.")
    row = session.get(ShotMark, shot_id)
    before = {"mark": row.mark if row else None, "stars": row.stars if row else 0}
    after = {
        "mark": before["mark"] if mark is None else (None if mark == "none" else mark),
        "stars": before["stars"] if stars is None else stars,
    }
    if after != before:
        session.add(
            FeedbackEvent(
                project_id=asset.project_id,
                kind="shot_mark",
                payload={"shot_id": shot_id, "media_id": asset.id, "before": before, **after},
            )
        )
    if after["mark"] is None and not after["stars"]:
        session.execute(delete(ShotMark).where(ShotMark.shot_id == shot_id))
        session.flush()
        return None
    values = {"shot_id": shot_id, "project_id": asset.project_id, "media_id": asset.id,
              "mark": after["mark"], "stars": after["stars"], "updated_at": utcnow()}  # fmt: skip
    session.execute(
        sqlite_insert(ShotMark)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["shot_id"],
            set_={k: values[k] for k in ("mark", "stars", "updated_at")},
        )
    )
    session.flush()
    session.expire_all()
    return session.get(ShotMark, shot_id)
