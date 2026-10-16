"""Project-wide steps after its clips were processed: actors, scenes, takes and vector indexes.

Each belongs to a whole project, not to one clip, so none is an ingest stage. They run once the
project's queue is empty (after the last job, after cancelling the last queued job, after a clip
is removed) and each is skipped when a hash of its inputs is unchanged.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cinemind.core.config import Settings
from cinemind.db.analysis import SceneRun
from cinemind.db.models import Job
from cinemind.db.people import ActorRun
from cinemind.db.takes import TakeRun
from cinemind.pipeline import actors, scenes, takes
from cinemind.search import vector_index

log = logging.getLogger(__name__)


def _digest(
    session: Session, model: type[ActorRun] | type[SceneRun] | type[TakeRun], project_id: str
) -> str:
    row = session.get(model, project_id)
    return row.digest if row is not None else ""


def refresh(session: Session, settings: Settings, project_id: str) -> list[str]:
    """Bring actors, scenes, takes and indexes up to date; commits after each. Returns what
    changed ("actors", "scenes", "takes"). A failing step is logged and does not stop the
    others: each can be repeated from its page."""
    changed: list[str] = []
    steps = (
        ("actors", ActorRun, lambda: actors.regroup(session, settings, project_id)),
        ("scenes", SceneRun, lambda: scenes.group(session, settings, project_id)),
        ("takes", TakeRun, lambda: takes.regroup(session, settings, project_id)),
    )
    for name, model, step in steps:
        try:
            before = _digest(session, model, project_id)
            step()
            session.commit()
            if _digest(session, model, project_id) != before:
                changed.append(name)
        except Exception:
            session.rollback()
            log.exception("updating %s failed for project %s", name, project_id)
    try:
        vector_index.rebuild_project(session, settings, project_id)
        session.commit()
    except Exception:
        session.rollback()
        log.exception("rebuilding the vector indexes failed for project %s", project_id)
    return changed


def refresh_if_idle(session: Session, settings: Settings, project_id: str) -> list[str] | None:
    """`refresh` once the project's queue is empty, so a big import is handled once at the end
    and not after every clip. None if jobs are still waiting."""
    waiting = session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.project_id == project_id, Job.status.in_(("queued", "running")))
    )
    if waiting:
        return None
    return refresh(session, settings, project_id)
