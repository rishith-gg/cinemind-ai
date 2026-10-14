""" "Same person?" questions: the pairs of actors whose faces look most alike, and the user's
answers.

Ours: which pairs are asked (closest first, never two people seen in the same frame, never a
pair the user already called different) and how an answer is kept. A "no" is stored by track and
keeps those tracks apart in every later grouping; a "yes" merges the two (an ordinary merge
correction). Every answer also records how far apart the two were when asked, so
`eval/actor_pairs.py` can measure on the user's own footage where the grouping limit
(`[faces] cluster_distance`) should sit.

Distance between two actors: average linkage over their tracks, the mean of 1 - cosine similarity
over every pair of one track from each. The grouping compares the same kind of number with
`cluster_distance` (it first merges the tracks of one clip, so the two can differ a little).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from cinemind.db.people import FaceTrack
from cinemind.pipeline import actors

ASK_AT_MOST = 12


def _vectors(tracks: Sequence[FaceTrack]) -> Any:
    return np.stack([np.frombuffer(t.embedding, dtype=np.float32) for t in tracks])


def linkage_distance(tracks_a: Sequence[FaceTrack], tracks_b: Sequence[FaceTrack]) -> float:
    similarity: Any = _vectors(tracks_a) @ _vectors(tracks_b).T
    distance: Any = 1.0 - similarity
    return round(float(distance.mean()), 4)


@dataclass
class Candidate:
    actor_a: str
    actor_b: str
    distance: float


def candidates(session: Session, project_id: str, limit: int = ASK_AT_MOST) -> list[Candidate]:
    """The pairs most worth asking about, closest first. Leaves out pairs seen in the same frame
    (they cannot be one person) and pairs the user already answered "no" for."""
    by_actor: dict[str, list[FaceTrack]] = {}
    for track in actors.project_tracks(session, project_id):
        if track.actor_id is not None:
            by_actor.setdefault(track.actor_id, []).append(track)
    position: dict[str, int] = {}
    owner: list[str] = []
    for actor_id, tracks in by_actor.items():
        for track in tracks:
            position[track.id] = len(owner)
            owner.append(actor_id)
    blocked = actors.co_occurring(session, project_id, position)
    blocked |= actors.kept_apart(session, project_id, position)
    excluded = {frozenset((owner[a], owner[b])) for a, b in blocked}
    ids = sorted(by_actor)
    found = [
        Candidate(a, b, linkage_distance(by_actor[a], by_actor[b]))
        for n, a in enumerate(ids)
        for b in ids[n + 1 :]
        if frozenset((a, b)) not in excluded
    ]
    found.sort(key=lambda c: (c.distance, c.actor_a, c.actor_b))
    return found[:limit]
