"""The user's approve / reject decisions on tags, and what is shown as a result."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cinemind.ai import tagger
from cinemind.core.errors import InvalidInputError, NotFoundError
from cinemind.db.analysis import Tag, TagReview
from cinemind.db.models import MediaAsset, Shot
from cinemind.db.people import FeedbackEvent

KNOWN = {tag.name for tag in tagger.MODEL_TAGS} | {"faces", "speech"}


def visible(status: str, review: str | None) -> bool:
    """Approved tags are shown, rejected ones never; otherwise the evaluated threshold decides."""
    if review is not None:
        return review == "approved"
    return status == "shown"


def reviews_for(session: Session, shot_ids: list[str]) -> dict[tuple[str, str], str]:
    if not shot_ids:
        return {}
    rows = session.scalars(select(TagReview).where(TagReview.shot_id.in_(shot_ids)))
    return {(r.shot_id, r.name): r.decision for r in rows}


def set_review(session: Session, shot_id: str, name: str, decision: str) -> Shot:
    """Approve, reject, or (`none`) withdraw the decision on one tag of one shot. Every change
    is also written to the feedback log. The caller commits."""
    if name not in KNOWN:
        raise InvalidInputError(f"'{name}' is not a tag the app knows.")
    if decision not in ("approved", "rejected", "none"):
        raise InvalidInputError("The decision must be approved, rejected or none.")
    shot = session.get(Shot, shot_id)
    asset = session.get(MediaAsset, shot.media_id) if shot else None
    if shot is None or asset is None:
        raise NotFoundError("That shot does not exist any more. Reload the page.")
    tag = session.scalar(select(Tag).where(Tag.shot_id == shot_id, Tag.name == name))
    session.execute(delete(TagReview).where(TagReview.shot_id == shot_id, TagReview.name == name))
    if decision != "none":
        session.add(
            TagReview(
                project_id=asset.project_id,
                media_id=asset.id,
                shot_id=shot_id,
                name=name,
                decision=decision,
            )
        )
    session.add(
        FeedbackEvent(
            project_id=asset.project_id,
            kind="tag_review",
            payload={
                "shot_id": shot_id,
                "media_id": asset.id,
                "name": name,
                "decision": decision,
                # What the app had suggested, so reviews can later measure precision on the
                # user's own footage (eval/tag_feedback.py).
                "score": tag.score if tag else None,
                "threshold": tag.threshold if tag else None,
                "status": tag.status if tag else None,
                "model": (tag.details or {}).get("model") if tag else None,
            },
        )
    )
    session.flush()
    return shot
