"""Actors: grouping a project's face tracks into people, and the user's corrections.

Two passes (SPEC section 9): tracks are grouped inside each clip first, then those groups are
grouped across the project, both with the method and distance from `[faces]`. Two tracks seen
in the same frame are never the same person. A correction "pins" every face of a track to an
actor (or sets it aside); pins outrank similarity, so they come back however often the project
is grouped again, and they are anchored to clip, time and place so they also survive a clip
being scanned again with other settings.
"""

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from typing import Any

import numpy as np
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from cinemind.ai import face_cluster
from cinemind.core import face_config
from cinemind.core.config import Settings
from cinemind.db.base import utcnow
from cinemind.db.models import MediaAsset
from cinemind.db.people import Actor, ActorRun, Face, FacePin, FaceScan, FaceTrack
from cinemind.pipeline.face_scan import overlap

# A pin finds its face again if one was seen within this time of it, overlapping this much.
PIN_TIME_S = 0.5
PIN_OVERLAP = 0.3
# Pins decide a track only if they reach over this share of the time the track covers, so one
# stray pin on a long track of someone else changes nothing.
PIN_COVERAGE = 0.5
# Pin states. `actor` = the user put this face with the actor; `kept` = it was with the actor
# when the user named or corrected that actor, and stays there; the other two set it aside.
PLACED, KEPT = "actor", "kept"
Vote = tuple[str, str | None]  # (pin state, actor id)


def lock(session: Session) -> None:
    """Take SQLite's write lock before reading what a grouping or a correction is based on. The
    API and the worker are separate processes; without this, one could write a grouping computed
    from what the other has just changed. Released by the caller's commit or rollback."""
    raw: Any = session.connection().connection.dbapi_connection
    if not raw.in_transaction:
        session.execute(text("BEGIN IMMEDIATE"))


def project_tracks(session: Session, project_id: str) -> list[FaceTrack]:
    query = (
        select(FaceTrack)
        .join(MediaAsset, MediaAsset.id == FaceTrack.media_id)
        .where(MediaAsset.project_id == project_id)
        .order_by(FaceTrack.media_id, FaceTrack.index)
    )
    return list(session.scalars(query))


def _rematch_pins(session: Session, project_id: str, track_ids: set[str]) -> int:
    """Give pins whose track is gone the track that now has a face where theirs was. Returns
    how many stay unmatched (kept: a later scan may bring the face back)."""
    pins = [
        pin
        for pin in session.scalars(select(FacePin).where(FacePin.project_id == project_id))
        if pin.track_id not in track_ids
    ]
    faces: dict[str, list[Face]] = {}
    unmatched = 0
    for pin in pins:
        if pin.media_id not in faces:
            faces[pin.media_id] = list(
                session.scalars(select(Face).where(Face.media_id == pin.media_id))
            )
        best, best_overlap = None, PIN_OVERLAP
        for face in faces[pin.media_id]:
            if abs(face.time_s - pin.time_s) > PIN_TIME_S:
                continue
            shared = overlap((pin.x, pin.y, pin.w, pin.h), (face.x, face.y, face.w, face.h))
            if shared >= best_overlap:
                best, best_overlap = face.track_id, shared
        pin.track_id = best
        unmatched += best is None
    return unmatched


def _votes(session: Session, project_id: str, tracks: list[FaceTrack]) -> dict[str, Vote]:
    """What the pins say about each track: the most common (state, actor) among its pins, if
    those pins reach over enough of the track's time (`PIN_COVERAGE`)."""
    times: dict[str, dict[Vote, list[float]]] = {}
    query = select(FacePin).where(FacePin.project_id == project_id, FacePin.track_id.is_not(None))
    for pin in session.scalars(query):
        votes = times.setdefault(str(pin.track_id), {})
        votes.setdefault((pin.state, pin.actor_id), []).append(pin.time_s)
    length = {t.id: t.end_s - t.start_s for t in tracks}
    decided: dict[str, Vote] = {}
    for track, votes in times.items():
        vote, seen = sorted(votes.items(), key=lambda kv: (-len(kv[1]), str(kv[0])))[0]
        reach = max(seen) - min(seen) + 2 * PIN_TIME_S
        if track in length and reach >= PIN_COVERAGE * length[track]:
            decided[track] = vote
    return decided


def _apart(session: Session, project_id: str, position: dict[str, int]) -> set[tuple[int, int]]:
    """Pairs of tracks that have a face in the same frame of the same clip."""
    query = (
        select(Face.media_id, Face.frame, Face.track_id)
        .join(MediaAsset, MediaAsset.id == Face.media_id)
        .where(MediaAsset.project_id == project_id)
    )
    frames: dict[tuple[str, int], list[int]] = {}
    for media, frame, track in session.execute(query):
        if track in position:
            frames.setdefault((media, frame), []).append(position[track])
    pairs: set[tuple[int, int]] = set()
    for members in frames.values():
        for i, a in enumerate(members):
            pairs.update((min(a, b), max(a, b)) for b in members[i + 1 :] if a != b)
    return pairs


def _groups(keys: Sequence[object]) -> list[list[int]]:
    found: dict[object, list[int]] = {}
    for i, key in enumerate(keys):
        if key is not None:
            found.setdefault(key, []).append(i)
    return [members for members in found.values() if len(members) > 1]


def _labels(
    tracks: list[FaceTrack],
    pinned: list[str | None],
    apart: set[tuple[int, int]],
    cfg: face_config.FaceConfig,
) -> tuple[list[int], Any]:
    vectors = np.stack([np.frombuffer(t.embedding, dtype=np.float32) for t in tracks])
    weights = [float(t.face_count) for t in tracks]
    # Tracks pinned to different actors stay apart as well.
    actors = [(i, a) for i, a in enumerate(pinned) if a is not None]
    apart = apart | {
        (i, j) for n, (i, a) in enumerate(actors) for j, b in actors[n + 1 :] if a != b
    }
    together = _groups(pinned)
    by_media: dict[str, list[int]] = {}
    for i, track in enumerate(tracks):
        by_media.setdefault(track.media_id, []).append(i)
    for members in by_media.values():  # pass 1: inside each clip
        local = {index: n for n, index in enumerate(members)}
        labels = face_cluster.cluster(
            vectors[members],
            cfg.cluster_distance,
            cfg.cluster_method,
            [(local[a], local[b]) for a, b in apart if a in local and b in local],
            [[local[i] for i in group if i in local] for group in together],
            weights=[weights[i] for i in members],
        )
        together += [[members[n] for n in group] for group in _groups(labels)]
    labels = face_cluster.cluster(  # pass 2: across the project
        vectors, cfg.cluster_distance, cfg.cluster_method, apart, together, weights
    )
    return labels, vectors


def how(pin_state: str | None) -> str:
    """Plain words for why a track sits with its actor."""
    if pin_state == PLACED:
        return "placed by you"
    if pin_state == KEPT:
        return "kept with this person by your correction"
    return "similar faces"


def new_actor(session: Session, project_id: str, staying: set[str] | None = None) -> Actor:
    """A new actor with the lowest number not in use. `staying` (during a grouping) names the
    actors that will still exist afterwards; the numbers of the others are free again."""
    pinned = set(session.scalars(select(FacePin.actor_id).where(FacePin.actor_id.is_not(None))))
    taken = {
        number
        for actor_id, number in session.execute(
            select(Actor.id, Actor.number).where(Actor.project_id == project_id)
        )
        if staying is None or actor_id in staying or actor_id in pinned
    }
    number = next(n for n in range(1, len(taken) + 2) if n not in taken)
    actor = Actor(project_id=project_id, number=number, name=f"Actor {number:03d}")
    session.add(actor)
    session.flush()
    if staying is not None:
        staying.add(actor.id)
    return actor


def basis(
    session: Session, settings: Settings, project_id: str, tracks: list[FaceTrack]
) -> tuple[str, dict[str, Vote], int]:
    """What a grouping depends on, as a hash (scans, pins, grouping settings), plus what the
    pins say per track and how many pins found no face."""
    cfg = settings.faces
    unmatched = _rematch_pins(session, project_id, {t.id for t in tracks})
    session.flush()
    votes = _votes(session, project_id, tracks)
    scans = session.execute(
        select(FaceScan.media_id, FaceScan.digest)
        .join(MediaAsset, MediaAsset.id == FaceScan.media_id)
        .where(MediaAsset.project_id == project_id)
        .order_by(FaceScan.media_id)
    ).all()
    basis: list[Any] = [cfg.cluster_method, cfg.cluster_distance, [list(row) for row in scans]]
    basis.append(sorted([track, vote[0], vote[1] or ""] for track, vote in votes.items()))
    return hashlib.sha256(json.dumps(basis).encode()).hexdigest(), votes, unmatched


def drop_empty_actors(session: Session, project_id: str) -> None:
    session.flush()
    in_use = select(FaceTrack.actor_id).where(FaceTrack.actor_id.is_not(None))
    has_pins = select(FacePin.actor_id).where(FacePin.actor_id.is_not(None))
    session.execute(
        delete(Actor).where(
            Actor.project_id == project_id, Actor.id.not_in(in_use), Actor.id.not_in(has_pins)
        )
    )


def regroup(session: Session, settings: Settings, project_id: str, force: bool = False) -> ActorRun:
    """Group the project's tracks into actors. Skipped when nothing it depends on changed
    (same scans, pins and settings) unless `force`. The caller commits."""
    lock(session)
    cfg = settings.faces
    tracks = project_tracks(session, project_id)
    digest, votes, unmatched = basis(session, settings, project_id, tracks)
    run = session.get(ActorRun, project_id)
    if run is not None:
        session.refresh(run)  # the API may have written it since this session last looked
    if run is not None and run.digest == digest and not force:
        return run
    used: dict[str, Any] = {"method": cfg.cluster_method}
    if cfg.cluster_method == "agglomerative":  # HDBSCAN does not use the distance
        used["cluster_distance"] = cfg.cluster_distance

    active: list[FaceTrack] = []
    for track in tracks:
        state = votes.get(track.id, ("auto", None))[0]
        if state in ("ignored", "unknown"):
            track.actor_id, track.state = None, state
            track.assignment = {"how": "set aside by you"}
        else:
            active.append(track)
    pinned = [votes[t.id][1] if t.id in votes else None for t in active]
    labels: list[int] = []
    if active:
        apart = _apart(session, project_id, {t.id: i for i, t in enumerate(active)})
        labels, vectors = _labels(active, pinned, apart, cfg)
        similarity = face_cluster.centroid_similarity(vectors, labels)
        chosen = _actors_for(session, project_id, active, pinned, labels)
        for track, label, pin, near in zip(active, labels, pinned, similarity, strict=True):
            track.actor_id = chosen[label]
            track.state = "pinned" if pin is not None else "auto"
            track.assignment = {"how": how(votes[track.id][0] if pin else None)}
            if pin is None:
                track.assignment = {**track.assignment, "similarity_to_group": near, **used}
    drop_empty_actors(session, project_id)
    if run is None:
        run = ActorRun(project_id=project_id, digest=digest)
        session.add(run)
    run.digest, run.clustered_at = digest, utcnow()
    run.details = {
        "engine": face_config.ENGINE,
        **used,
        "tracks": len(tracks),
        "tracks_grouped": len(active),
        "actors": len(set(labels)),
        "tracks_placed_by_you": sum(votes[t.id][0] == PLACED for t in active if t.id in votes),
        "corrections_not_found": unmatched,
    }
    return run


def _actors_for(
    session: Session,
    project_id: str,
    tracks: list[FaceTrack],
    pinned: list[str | None],
    labels: list[int],
) -> dict[int, str]:
    """Which actor each group becomes: the one its tracks are pinned to; else the actor most of
    its faces belonged to before (each actor is reused once, so names and numbers stay put);
    else a new one."""
    chosen: dict[int, str] = {}
    for label, pin in zip(labels, pinned, strict=True):
        if pin is not None:
            chosen.setdefault(label, pin)
    before: Counter[tuple[int, str]] = Counter()
    for track, label in zip(tracks, labels, strict=True):
        if label not in chosen and track.actor_id is not None:
            before[(label, track.actor_id)] += track.face_count
    taken = set(chosen.values())
    for (label, actor), _ in sorted(before.items(), key=lambda kv: (-kv[1], kv[0])):
        if label not in chosen and actor not in taken:
            chosen[label] = actor
            taken.add(actor)
    for label in dict.fromkeys(labels):
        if label not in chosen:
            chosen[label] = new_actor(session, project_id, taken).id
    return chosen
