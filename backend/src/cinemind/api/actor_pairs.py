""" "Same person?" review: the pairs of people most likely to be one person, and the user's
answers (yes merges them, no keeps them apart from then on)."""

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cinemind.api.actor_schemas import ActorPairAnswerIn, ActorPairOut, ActorPairsOut
from cinemind.api.actors import actor_of, actor_out
from cinemind.api.deps import SessionDep, SettingsDep
from cinemind.api.media import ERRORS, get_project
from cinemind.core.config import Settings
from cinemind.core.errors import NotFoundError
from cinemind.db.people import ActorPairAnswer, FaceTrack
from cinemind.pipeline import actor_corrections as corrections
from cinemind.pipeline import actor_pairs

router = APIRouter(tags=["actors"])


def _pairs(session: Session, settings: Settings, project_id: str) -> ActorPairsOut:
    found = actor_pairs.candidates(session, project_id)
    wanted = {i for c in found for i in (c.actor_a, c.actor_b)}
    tracks: dict[str, list[FaceTrack]] = {}
    for track in session.scalars(select(FaceTrack).where(FaceTrack.actor_id.in_(wanted))):
        tracks.setdefault(str(track.actor_id), []).append(track)
    out = {i: actor_out(actor_of(session, i), tracks[i]) for i in wanted}
    counts = session.execute(
        select(ActorPairAnswer.same, func.count())
        .where(ActorPairAnswer.project_id == project_id)
        .group_by(ActorPairAnswer.same)
    ).all()
    by_answer = {bool(same): int(count) for same, count in counts}
    cfg = settings.faces
    return ActorPairsOut(
        pairs=[
            ActorPairOut(first=out[c.actor_a], second=out[c.actor_b], distance=c.distance)
            for c in found
        ],  # fmt: skip
        cluster_distance=cfg.cluster_distance if cfg.cluster_method == "agglomerative" else None,
        answered=sum(by_answer.values()),
        answered_same=by_answer.get(True, 0),
    )


@router.get(
    "/api/projects/{project_id}/actors/pairs",
    response_model=ActorPairsOut,
    responses=ERRORS,
    operation_id="listActorPairs",
)
def list_actor_pairs(project_id: str, session: SessionDep, settings: SettingsDep) -> ActorPairsOut:
    """People whose faces look most alike, closest first: questions for the user."""
    get_project(session, project_id)
    return _pairs(session, settings, project_id)


@router.post(
    "/api/projects/{project_id}/actors/pairs/answer",
    response_model=ActorPairsOut,
    responses=ERRORS,
    operation_id="answerActorPair",
)
def answer_actor_pair(
    project_id: str, body: ActorPairAnswerIn, session: SessionDep, settings: SettingsDep
) -> ActorPairsOut:
    """Same person: merge the two. Different people: keep them apart in every later grouping."""
    get_project(session, project_id)
    first, second = actor_of(session, body.first_id), actor_of(session, body.second_id)
    if first.project_id != project_id or second.project_id != project_id:
        raise NotFoundError("Those people are not in this project.")
    corrections.answer_pair(session, settings, first, second, body.same)
    session.commit()
    return _pairs(session, settings, project_id)
