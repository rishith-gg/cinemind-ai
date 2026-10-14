"""The user's corrections to the actors: rename, merge, split, move, set aside, hand back, and
answers to "same person?".

A correction changes exactly the chosen tracks and nothing else; the project is not grouped
again (except when tracks are handed back to automatic grouping, which is that request). Each
one stores a pin for every face of the affected tracks, so it comes back when the project is
grouped or a clip is scanned again (`pipeline/actors.py`), and is appended to `feedback_events`.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, selectinload

from cinemind.core.config import Settings
from cinemind.core.errors import InvalidInputError, NotFoundError
from cinemind.db.people import (
    Actor,
    ActorPairAnswer,
    ActorRun,
    FacePin,
    FaceTrack,
    FeedbackEvent,
)
from cinemind.pipeline.actor_pairs import linkage_distance
from cinemind.pipeline.actors import (
    KEPT,
    PLACED,
    basis,
    drop_empty_actors,
    how,
    lock,
    new_actor,
    project_tracks,
    regroup,
)


def _log(session: Session, project_id: str, kind: str, payload: dict[str, Any]) -> None:
    session.add(FeedbackEvent(project_id=project_id, kind=kind, payload=payload))


def _pin(
    session: Session,
    project_id: str,
    tracks: Sequence[FaceTrack],
    state: str,
    actor_id: str | None,
) -> None:
    """Put these tracks where the user said and replace their pins: one pin per face, so a
    later, differently cut track is still found by the places its faces were in."""
    ids = [t.id for t in tracks]
    if not ids:
        return
    session.execute(delete(FacePin).where(FacePin.track_id.in_(ids)))
    query = select(FaceTrack).where(FaceTrack.id.in_(ids)).options(selectinload(FaceTrack.faces))
    for track in session.scalars(query):
        track.actor_id = actor_id
        if state == KEPT:  # the user did not judge this track: keep what is known about it
            track.assignment = {**track.assignment, "how": how(KEPT)}
        else:
            track.assignment = {"how": how(PLACED) if state == PLACED else "set aside by you"}
        track.state = "pinned" if state in (PLACED, KEPT) else state
        for face in track.faces:
            session.add(
                FacePin(
                    project_id=project_id,
                    media_id=track.media_id,
                    time_s=face.time_s,
                    x=face.x,
                    y=face.y,
                    w=face.w,
                    h=face.h,
                    state=state,
                    actor_id=actor_id,
                    track_id=track.id,
                )
            )


def _keep(
    session: Session, project_id: str, actor_ids: Sequence[str], into: str | None = None
) -> None:
    """Pin the tracks of these actors to `into` (default: where they are) as "kept": tracks the
    user already placed there by hand keep that mark."""
    for actor_id in actor_ids:
        target = into or actor_id
        tracks = _tracks_of(session, [actor_id])
        loose = [t for t in tracks if t.state != "pinned" or target != actor_id]
        placed = {t.id for t in loose if t.assignment.get("how") == how(PLACED)}
        _pin(session, project_id, [t for t in loose if t.id not in placed], KEPT, target)
        _pin(session, project_id, [t for t in loose if t.id in placed], PLACED, target)


def _begin(session: Session, settings: Settings, project_id: str) -> bool:
    """Start a correction: take the write lock, and say whether the stored grouping is up to
    date (False while new scans still wait to be grouped)."""
    lock(session)
    session.expire_all()  # read again under the lock
    run = session.get(ActorRun, project_id)
    digest, _, _ = basis(session, settings, project_id, project_tracks(session, project_id))
    return run is not None and run.digest == digest


def _settle(session: Session, settings: Settings, project_id: str, current: bool) -> None:
    """After a correction: it changed exactly what the user asked for and nothing else, so the
    project is not grouped again. If the grouping was up to date before, its stored hash is
    brought up to date too; if tracks were still waiting to be grouped, it is left alone so the
    next idle moment groups them."""
    drop_empty_actors(session, project_id)
    tracks = project_tracks(session, project_id)
    digest, votes, _ = basis(session, settings, project_id, tracks)
    run = session.get(ActorRun, project_id)
    if run is None:
        return
    if current:
        run.digest = digest
    details = dict(run.details)
    details["tracks_placed_by_you"] = sum(vote[0] == PLACED for vote in votes.values())
    details["actors"] = len({t.actor_id for t in tracks if t.actor_id is not None})
    run.details = details


def _tracks_of(session: Session, actor_ids: Sequence[str]) -> list[FaceTrack]:
    return list(session.scalars(select(FaceTrack).where(FaceTrack.actor_id.in_(actor_ids))))


def _pick(session: Session, project_id: str, track_ids: Sequence[str]) -> list[FaceTrack]:
    wanted = set(track_ids)
    found = [t for t in project_tracks(session, project_id) if t.id in wanted]
    if not wanted or len(found) != len(wanted):
        raise NotFoundError("Some of those faces no longer exist. Reload the page and try again.")
    return found


def clean_name(name: str) -> str:
    cleaned = " ".join("".join(ch for ch in name if ch.isprintable()).split())
    if not 1 <= len(cleaned) <= 100:
        raise InvalidInputError("A name needs 1 to 100 characters.")
    return cleaned


def rename(session: Session, settings: Settings, actor: Actor, name: str) -> None:
    """Name the actor and keep its tracks with it: a named person is never merged away or
    renumbered automatically."""
    cleaned = clean_name(name)
    current = _begin(session, settings, actor.project_id)
    actor.name, actor.named = cleaned, True
    _keep(session, actor.project_id, [actor.id])
    _log(session, actor.project_id, "actor_rename", {"actor": actor.id, "name": actor.name})
    _settle(session, settings, actor.project_id, current)


def merge(session: Session, settings: Settings, actor: Actor, others: Sequence[Actor]) -> None:
    """Everything of `others` becomes `actor`. A name the user gave survives the merge."""
    other_ids = [o.id for o in others if o.id != actor.id]
    if not other_ids:
        raise InvalidInputError("Choose at least two different people to merge.")
    current = _begin(session, settings, actor.project_id)
    if not actor.named:
        named = next((o for o in others if o.named), None)
        if named is not None:
            actor.name, actor.named = named.name, True
    session.execute(
        update(FacePin).where(FacePin.actor_id.in_(other_ids)).values(actor_id=actor.id)
    )
    _keep(session, actor.project_id, [actor.id])
    _keep(session, actor.project_id, other_ids, into=actor.id)
    _log(session, actor.project_id, "actor_merge", {"into": actor.id, "merged": other_ids})
    _settle(session, settings, actor.project_id, current)


def _hold(session: Session, project_id: str, moved: Sequence[FaceTrack]) -> None:
    """Keep what stays behind with each actor the moved tracks leave, so the rest is not
    dragged along by its likeness to them."""
    moving = {t.id for t in moved}
    for actor_id in {t.actor_id for t in moved if t.actor_id is not None}:
        rest = [t for t in _tracks_of(session, [actor_id]) if t.id not in moving]
        _pin(session, project_id, [t for t in rest if t.state != "pinned"], KEPT, actor_id)


def split(session: Session, settings: Settings, actor: Actor, track_ids: Sequence[str]) -> Actor:
    """Move the chosen tracks of `actor` to a new actor."""
    current = _begin(session, settings, actor.project_id)
    moved = _pick(session, actor.project_id, track_ids)
    if any(t.actor_id != actor.id for t in moved):
        raise InvalidInputError("Those faces do not all belong to this person.")
    if len(moved) >= len(_tracks_of(session, [actor.id])):
        raise InvalidInputError("Leave at least one face with this person.")
    created = new_actor(session, actor.project_id)
    _hold(session, actor.project_id, moved)
    _pin(session, actor.project_id, moved, PLACED, created.id)
    payload = {"from": actor.id, "to": created.id, "tracks": [t.id for t in moved]}
    _log(session, actor.project_id, "actor_split", payload)
    _settle(session, settings, actor.project_id, current)
    return created


def place(
    session: Session,
    settings: Settings,
    project_id: str,
    track_ids: Sequence[str],
    state: str,
    actor: Actor | None = None,
) -> None:
    """Put tracks with an actor (`actor`), set them aside (`ignored` = not a face, `unknown` =
    someone not worth naming), or hand them back to automatic grouping (`auto`, the one
    correction after which the project is grouped again, to find their place)."""
    if state == PLACED and actor is None:
        raise InvalidInputError("Choose the person to move these faces to.")
    if actor is not None and actor.project_id != project_id:
        raise NotFoundError("That person does not exist in this project.")
    current = _begin(session, settings, project_id)
    moved = _pick(session, project_id, track_ids)
    payload = {
        "tracks": [t.id for t in moved],
        "state": state,
        "actor": actor.id if actor and state == PLACED else None,
    }
    _log(session, project_id, "face_place", payload)
    if state == "auto":
        session.execute(delete(FacePin).where(FacePin.track_id.in_([t.id for t in moved])))
        session.flush()
        regroup(session, settings, project_id, force=True)
        return
    if state == PLACED and actor is not None:
        _hold(session, project_id, [t for t in moved if t.actor_id != actor.id])
        # The actor's own tracks are kept too: it is the group they joined, not a new one.
        _keep(session, project_id, [actor.id])
        _pin(session, project_id, moved, PLACED, actor.id)
    else:
        _pin(session, project_id, moved, state, None)
    _settle(session, settings, project_id, current)


def answer_pair(
    session: Session, settings: Settings, first: Actor, second: Actor, same: bool
) -> Actor:
    """The user's answer to "are these two the same person?". Yes merges them (into the named
    one, else the one with more faces) and returns the actor that remains; no keeps their
    current tracks apart from now on. Both are stored with the distance the two had."""
    if first.id == second.id or first.project_id != second.project_id:
        raise InvalidInputError("Choose two different people of the same project.")
    current = _begin(session, settings, first.project_id)  # before the answer joins the basis
    tracks_a, tracks_b = _tracks_of(session, [first.id]), _tracks_of(session, [second.id])
    if not tracks_a or not tracks_b:
        raise NotFoundError("One of these people has no faces left. Reload the page.")
    distance = linkage_distance(tracks_a, tracks_b)
    ids_a, ids_b = sorted(t.id for t in tracks_a), sorted(t.id for t in tracks_b)
    project_id = first.project_id
    session.add(
        ActorPairAnswer(
            project_id=project_id, tracks_a=ids_a, tracks_b=ids_b, same=same, distance=distance
        )
    )
    payload = {"actors": [first.id, second.id], "same": same, "distance": distance}
    _log(session, project_id, "actor_pair", payload)
    if not same:
        _settle(session, settings, project_id, current)
        return first
    faces = {
        a.id: sum(t.face_count for t in ts) for a, ts in ((first, tracks_a), (second, tracks_b))
    }
    keep, other = sorted((first, second), key=lambda a: (not a.named, -faces[a.id], a.number))
    merge(session, settings, keep, [other])
    return keep
