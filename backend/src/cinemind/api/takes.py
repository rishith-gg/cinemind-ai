"""Take groups: shots that repeat the same material, the suggested best take of each with the
numbers behind it, and the user's corrections (SPEC P1-B)."""

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from cinemind.ai import embedder
from cinemind.ai.embedder import PULL_HINT
from cinemind.api.deps import SessionDep, SettingsDep
from cinemind.api.media import ERRORS, get_project
from cinemind.api.takes_schemas import (
    TakeApartIn,
    TakeBestIn,
    TakeGroupOut,
    TakeGroupsOut,
    TakeMemberOut,
    TakePairOut,
    TakeShotOut,
)
from cinemind.core.config import Settings
from cinemind.db.models import Keyframe, MediaAsset, Shot
from cinemind.db.takes import TakeGroup, TakeRun
from cinemind.pipeline import shot_marks
from cinemind.pipeline import takes as take_service

router = APIRouter(tags=["takes"])


def _shots(session: Session, shot_ids: list[str]) -> dict[str, TakeShotOut]:
    if not shot_ids:
        return {}
    rows = session.execute(
        select(Shot, MediaAsset.filename)
        .join(MediaAsset, MediaAsset.id == Shot.media_id)
        .where(Shot.id.in_(shot_ids))
    ).all()
    keyframes: dict[str, str] = {}
    query = select(Keyframe.shot_id, Keyframe.id).where(Keyframe.shot_id.in_(shot_ids))
    for shot_id, keyframe_id in session.execute(query.order_by(Keyframe.slot.desc())):
        keyframes[shot_id] = keyframe_id  # last write wins: the lowest slot
    marks = shot_marks.marks_for(session, shot_ids)
    return {
        shot.id: TakeShotOut(
            shot_id=shot.id,
            media_id=shot.media_id,
            filename=filename,
            index=shot.index,
            start_s=shot.start_s,
            end_s=shot.end_s,
            keyframe_id=keyframes.get(shot.id),
            mark=marks[shot.id].mark if shot.id in marks else None,  # pyright: ignore[reportArgumentType]
            stars=marks[shot.id].stars if shot.id in marks else 0,
        )
        for shot, filename in rows
    }


def _out(session: Session, settings: Settings, project_id: str) -> TakeGroupsOut:
    groups = list(
        session.scalars(
            select(TakeGroup)
            .where(TakeGroup.project_id == project_id)
            .order_by(TakeGroup.index)
            .options(selectinload(TakeGroup.members))
        )
    )
    apart = take_service.kept_apart(session, project_id)
    shots = _shots(session, [m.shot_id for g in groups for m in g.members] + apart)
    out: list[TakeGroupOut] = []
    for g in groups:
        members = [
            TakeMemberOut(
                **shots[m.shot_id].model_dump(),
                rank=m.rank,
                best=m.shot_id == g.best_shot_id,
                score=m.score,
                signals=m.signals,
                notes=m.notes,
                text=m.text,
            )
            for m in g.members
            if m.shot_id in shots
        ]
        out.append(
            TakeGroupOut(
                id=g.id,
                index=g.index,
                kind=g.kind,  # pyright: ignore[reportArgumentType]
                best_shot_id=g.best_shot_id,
                best_by=g.best_by,  # pyright: ignore[reportArgumentType]
                members=members,
                pairs=[TakePairOut(**p) for p in g.details.get("pairs", [])],
            )
        )
    run = session.get(TakeRun, project_id)
    count = session.scalar(
        select(func.count())
        .select_from(Shot)
        .join(MediaAsset, MediaAsset.id == Shot.media_id)
        .where(MediaAsset.project_id == project_id)
    )
    spec = embedder.choose_visual(settings)
    message = None
    if not spec.ready(settings.models_path):
        message = (
            f"The picture model '{spec.key}' is not downloaded, so only shots with matching "
            f"words can be found as takes. {PULL_HINT}"
        )
    elif run is None and count:
        message = "Takes have not been looked for in this project yet. Press Find takes."
    return TakeGroupsOut(
        groups=out,
        kept_apart=[shots[s] for s in apart if s in shots],
        grouped_at=run.grouped_at if run else None,
        details=run.details if run else {},
        settings=settings.takes.model_dump(),
        shots=count or 0,
        message=message,
    )


@router.get(
    "/api/projects/{project_id}/takes",
    response_model=TakeGroupsOut,
    responses=ERRORS,
    operation_id="listTakeGroups",
)
def list_take_groups(project_id: str, session: SessionDep, settings: SettingsDep) -> TakeGroupsOut:
    get_project(session, project_id)
    return _out(session, settings, project_id)


@router.post(
    "/api/projects/{project_id}/takes/regroup",
    response_model=TakeGroupsOut,
    responses=ERRORS,
    operation_id="regroupTakes",
)
def regroup_takes(project_id: str, session: SessionDep, settings: SettingsDep) -> TakeGroupsOut:
    get_project(session, project_id)
    take_service.regroup(session, settings, project_id)
    session.commit()
    return _out(session, settings, project_id)


@router.put(
    "/api/projects/{project_id}/takes/best",
    response_model=TakeGroupsOut,
    responses=ERRORS,
    operation_id="setBestTake",
)
def set_best_take(
    project_id: str, body: TakeBestIn, session: SessionDep, settings: SettingsDep
) -> TakeGroupsOut:
    """Make a take the best of its group, or (`best` false) let the signals choose again."""
    get_project(session, project_id)
    take_service.set_best(session, settings, project_id, body.shot_id, body.best)
    session.commit()
    return _out(session, settings, project_id)


@router.put(
    "/api/projects/{project_id}/takes/apart",
    response_model=TakeGroupsOut,
    responses=ERRORS,
    operation_id="setTakeApart",
)
def set_take_apart(
    project_id: str, body: TakeApartIn, session: SessionDep, settings: SettingsDep
) -> TakeGroupsOut:
    """Take a shot out of its take group (it stays apart from those shots), or undo that."""
    get_project(session, project_id)
    take_service.set_apart(session, settings, project_id, body.shot_id, body.apart)
    session.commit()
    return _out(session, settings, project_id)
