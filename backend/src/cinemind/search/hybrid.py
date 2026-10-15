"""Hybrid search: the four result lists of `retrievers.py`, filtered and fused with Reciprocal
Rank Fusion (RRF).

Each list gives a shot `weight / (k + rank)` (rank from 1); a shot's fused score is the sum over
the lists it is in. RRF needs no score calibration between lists (a BM25 value and a cosine
cannot be compared), which is why it is used. Settings: `[search]` (k = 60 from the RRF paper,
weights 1). A query is a text, a shot ("more like this") or a picture; the last two use the
picture list only. Filters remove shots from every list before fusion.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemind.core.config import Settings
from cinemind.core.errors import InvalidInputError
from cinemind.core.search_config import RETRIEVERS
from cinemind.db.analysis import Tag
from cinemind.db.models import MediaAsset, QualityMetric, Shot
from cinemind.db.people import FaceTrack
from cinemind.pipeline import tag_review
from cinemind.search import retrievers
from cinemind.search.retrievers import Item, Shots, Unavailable


@dataclass
class Filters:
    media_id: str | None = None
    actor_id: str | None = None
    scene_id: str | None = None
    min_quality: float | None = None  # the shot's Technical Quality Score, 0..1
    has_dialogue: bool = False  # the shot has the "speech" tag (certain transcript lines)

    def active(self) -> bool:
        return any(
            (self.media_id, self.actor_id, self.scene_id, self.min_quality is not None,
             self.has_dialogue)
        )  # fmt: skip


def allowed_shots(session: Session, project_id: str, filters: Filters) -> set[str] | None:
    """The shots the filters keep, or None when no filter is set."""
    if not filters.active():
        return None
    query = (
        select(Shot.id)
        .join(MediaAsset, MediaAsset.id == Shot.media_id)
        .where(MediaAsset.project_id == project_id)
    )
    if filters.media_id:
        query = query.where(Shot.media_id == filters.media_id)
    if filters.scene_id:
        query = query.where(Shot.scene_id == filters.scene_id)
    if filters.actor_id:
        with_actor = select(FaceTrack.shot_id).where(FaceTrack.actor_id == filters.actor_id)
        query = query.where(Shot.id.in_(with_actor))
    if filters.min_quality is not None:
        good = select(QualityMetric.shot_id).where(QualityMetric.score >= filters.min_quality)
        query = query.where(Shot.id.in_(good))
    kept = set(session.scalars(query))
    if filters.has_dialogue:  # the speech tag as the app shows it: the user's review decides
        tags = list(
            session.scalars(select(Tag).where(Tag.group == "speech", Tag.shot_id.in_(kept)))
        )
        reviews = tag_review.reviews_for(session, [t.shot_id for t in tags])
        kept = {
            t.shot_id
            for t in tags
            if tag_review.visible(t.status, reviews.get((t.shot_id, t.name)))
        }
    return kept


@dataclass
class Fused:
    shot_id: str
    score: float
    # Per list the shot is in: its entry, its rank (from 1) and what it added to the score.
    parts: dict[str, tuple[Item, int, float]] = field(default_factory=lambda: {})

    @property
    def jump_s(self) -> float:
        """Where the best evidence is: a spoken word, a line, a keyframe, else the shot start."""
        for name in ("keyword", "text", "visual", "labels"):
            if name in self.parts:
                return self.parts[name][0].time_s
        return 0.0


def fuse(
    lists: dict[str, list[Item]], weights: dict[str, float], k: int, limit: int
) -> list[Fused]:
    """RRF over best-first lists. Equal scores share a rank (competition ranking: 1, 2, 2, 4),
    so shots a list cannot tell apart get the same share."""
    fused: dict[str, Fused] = {}
    for name, items in lists.items():
        weight = weights.get(name, 1.0)
        if weight <= 0:
            continue
        rank = 0
        for position, item in enumerate(items, start=1):
            if position == 1 or item.score != items[position - 2].score:
                rank = position
            entry = fused.setdefault(item.shot_id, Fused(item.shot_id, 0.0))
            part = weight / (k + rank)
            entry.parts[name] = (item, rank, part)
            entry.score += part
    ranked = sorted(fused.values(), key=lambda f: (-f.score, f.shot_id))
    for entry in ranked:
        entry.score = round(entry.score, 6)
    return ranked[:limit]


@dataclass
class Query:
    text: str | None = None
    like_shot_id: str | None = None
    image: Any = None  # BGR array of a dropped picture
    filters: Filters = field(default_factory=Filters)
    # Which lists to use (all by default; the evaluation turns lists off one by one).
    use: Sequence[str] = RETRIEVERS


@dataclass
class Outcome:
    results: list[Fused]
    lists: dict[str, int]  # how many shots each list found (after filters)
    unavailable: dict[str, str]  # list -> why it could not run


def run(session: Session, settings: Settings, project_id: str, query: Query) -> Outcome:
    cfg = settings.search
    keep = allowed_shots(session, project_id, query.filters)
    # With a filter every list is searched in full and cut to `depth` after filtering, so the
    # shots a filter keeps are found however far down the project-wide ranking they are.
    depth = cfg.depth if keep is None else 1_000_000
    shots = Shots(session, project_id)
    unknown = set(query.use) - set(RETRIEVERS)
    if unknown:
        raise InvalidInputError(f"Unknown result lists: {', '.join(sorted(unknown))}.")
    jobs: dict[str, Callable[[], list[Item]]] = {}
    if query.image is not None:
        jobs["visual"] = lambda: retrievers.like_image(
            session, settings, project_id, query.image, depth
        )
    elif query.like_shot_id:
        jobs["visual"] = lambda: retrievers.like_shot(
            session, settings, project_id, str(query.like_shot_id), depth
        )
    elif query.text and query.text.strip():
        q = query.text.strip()
        jobs = {
            "keyword": lambda: retrievers.keyword(session, project_id, shots, q, depth),
            "labels": lambda: retrievers.labels(session, project_id, shots, q, depth),
            "text": lambda: retrievers.text(session, settings, project_id, shots, q, depth),
            "visual": lambda: retrievers.visual(session, settings, project_id, q, depth),
        }
    else:
        raise InvalidInputError("Type something to search for, or pick a picture.")
    if not set(jobs) & set(query.use):
        raise InvalidInputError("A picture search needs the picture list; it was turned off.")
    lists: dict[str, list[Item]] = {}
    unavailable: dict[str, str] = {}
    for name, job in jobs.items():
        if name not in query.use:
            continue
        try:
            found = job()
        except Unavailable as exc:
            unavailable[name] = str(exc)
            continue
        lists[name] = [i for i in found if keep is None or i.shot_id in keep][: cfg.depth]
    results = fuse(lists, cfg.weights, cfg.rrf_k, cfg.max_results)
    return Outcome(results, {name: len(items) for name, items in lists.items()}, unavailable)
