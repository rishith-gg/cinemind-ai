"""The four result lists hybrid search fuses, each a ranking of the project's shots.

- keyword: SQLite FTS5 / BM25 over transcript lines (all words must occur, matched from the
  start of a word). Lines marked uncertain are left out (D-084).
- labels: the query's words against what the app shows about a shot: shown or approved tags,
  actor names, the scene name and the file name. Ranked by how many query words matched.
- text: the query through the sentence model (MiniLM) against transcript-line vectors.
- visual: the query through the picture model's text side (CLIP / SigLIP) against keyframe
  vectors; or a picture (a dropped image, or the keyframes of a shot) against them.

Existing models and libraries: FTS5, MiniLM, CLIP / SigLIP. Ours: what each list covers, how a
line or keyframe becomes a shot, and the label matching rule. Every list keeps one entry per
shot (its best line or keyframe) and its own score, so the result can say why it is there.
"""

# numpy arrays are untyped.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemind.ai import embedder
from cinemind.core.config import Settings
from cinemind.core.embed_config import EmbedModel
from cinemind.core.errors import InvalidInputError
from cinemind.core.transcribe_config import is_uncertain
from cinemind.db.analysis import Embedding, Scene, Tag
from cinemind.db.models import Keyframe, MediaAsset, Shot, TranscriptSegment
from cinemind.db.people import Actor, FaceTrack
from cinemind.pipeline import tag_review
from cinemind.search import transcript_search, vector_index

# A label word matches a query word when equal, or when the query word has at least this many
# letters and starts the label word ("walk" finds "walking"; "in" does not find "indoor").
LABEL_PREFIX_MIN = 4
# Words that say nothing about a shot; left out of label matching ("a photo of a dog" would
# otherwise match every label containing "a" or "of").
STOPWORDS = frozenset(
    "a an and are at be by for from in into is it of on or the this to with".split()  # noqa: SIM905
)


@dataclass
class Item:
    """One shot in one result list."""

    shot_id: str
    score: float  # the list's own score: BM25 (lower is better), words matched, or cosine
    time_s: float  # where to jump in the clip
    text: str | None = None  # the matched transcript line
    parts: list[tuple[str, bool]] | None = None  # that line with the matched words marked
    matched: list[str] = field(default_factory=lambda: [])  # labels that matched


class Unavailable(Exception):
    """A list cannot run (its model is not downloaded); the message says how to fix it."""


class Shots:
    """The project's shots, to turn a time in a clip into the shot it falls in."""

    def __init__(self, session: Session, project_id: str) -> None:
        query = (
            select(Shot.id, Shot.media_id, Shot.start_s, Shot.end_s)
            .join(MediaAsset, MediaAsset.id == Shot.media_id)
            .where(MediaAsset.project_id == project_id)
            .order_by(Shot.media_id, Shot.start_s)
        )
        self.starts: dict[str, list[float]] = {}
        self.ids: dict[str, list[str]] = {}
        self.start: dict[str, float] = {}
        for shot_id, media_id, start_s, _end_s in session.execute(query):
            self.starts.setdefault(media_id, []).append(start_s)
            self.ids.setdefault(media_id, []).append(shot_id)
            self.start[shot_id] = start_s

    def at(self, media_id: str, time_s: float) -> str | None:
        """The shot whose start is the last at or before `time_s` (the first shot for an earlier
        time; shots cover the whole clip, so a later time belongs to the last shot)."""
        ids = self.ids.get(media_id)
        if not ids:
            return None
        return ids[max(0, bisect_right(self.starts[media_id], time_s) - 1)]


def _best_per_shot(items: Iterable[Item], higher_is_better: bool = True) -> list[Item]:
    sign = 1.0 if higher_is_better else -1.0
    best: dict[str, Item] = {}
    for item in items:
        kept = best.get(item.shot_id)
        if kept is None or sign * item.score > sign * kept.score:
            best[item.shot_id] = item
    return sorted(best.values(), key=lambda i: (-sign * i.score, i.shot_id))


# --- keyword ----------------------------------------------------------------------------------


def keyword(session: Session, project_id: str, shots: Shots, query: str, depth: int) -> list[Item]:
    try:
        _, hits = transcript_search.search(session, project_id, query, None, depth)
    except InvalidInputError:
        return []
    items: list[Item] = []
    for hit in hits:
        shot = shots.at(hit.media_id, hit.jump_s)
        if shot is not None:
            text = "".join(part for part, _ in hit.parts)
            items.append(Item(shot, hit.rank, hit.jump_s, text, hit.parts))
    return _best_per_shot(items, higher_is_better=False)


# --- labels -----------------------------------------------------------------------------------


def _matches(term: str, words: Sequence[str]) -> bool:
    return any(w == term or (len(term) >= LABEL_PREFIX_MIN and w.startswith(term)) for w in words)


def shot_labels(session: Session, project_id: str) -> dict[str, list[tuple[str, str]]]:
    """(kind, label) of every shot: file, scene, shown or approved tags, and the people the user
    named ("Actor 003" is not a label anyone searches for)."""
    labels: dict[str, list[tuple[str, str]]] = {}
    rows = session.execute(
        select(Shot.id, MediaAsset.filename, Scene.name)
        .join(MediaAsset, MediaAsset.id == Shot.media_id)
        .outerjoin(Scene, Scene.id == Shot.scene_id)
        .where(MediaAsset.project_id == project_id)
    )
    for shot_id, filename, scene in rows:
        labels[shot_id] = [("file", filename)] + ([("scene", scene)] if scene else [])
    tags = list(
        session.scalars(
            select(Tag)
            .join(MediaAsset, MediaAsset.id == Tag.media_id)
            .where(MediaAsset.project_id == project_id)
        )
    )
    reviews = tag_review.reviews_for(session, list(labels))
    for tag in tags:
        if tag_review.visible(tag.status, reviews.get((tag.shot_id, tag.name))):
            labels[tag.shot_id].append(("tag", tag.label))
    actors = session.execute(
        select(FaceTrack.shot_id, Actor.name)
        .join(Actor, Actor.id == FaceTrack.actor_id)
        .where(
            Actor.project_id == project_id, Actor.named.is_(True), FaceTrack.shot_id.is_not(None)
        )
        .distinct()
    )
    for shot_id, name in actors:
        if shot_id in labels:
            labels[shot_id].append(("actor", name))
    return labels


def labels(session: Session, project_id: str, shots: Shots, query: str, depth: int) -> list[Item]:
    try:
        words = [
            w for t in transcript_search.query_terms(query) for w in transcript_search.words(t)
        ]
    except InvalidInputError:
        return []
    terms = [w for w in words if w not in STOPWORDS and len(w) > 1]
    items: list[Item] = []
    for shot_id, found in shot_labels(session, project_id).items():
        hit_terms: set[str] = set()
        matched: list[str] = []
        for kind, label in found:
            words = transcript_search.words(label)
            hits = {t for t in terms if _matches(t, words)}
            if hits:
                hit_terms |= hits
                matched.append(f"{kind}: {label}")
        if hit_terms:
            items.append(
                Item(shot_id, float(len(hit_terms)), shots.start[shot_id], matched=matched)
            )
    return sorted(items, key=lambda i: (-i.score, i.shot_id))[:depth]


# --- text vectors -----------------------------------------------------------------------------


def _ready(spec: EmbedModel, settings: Settings, what: str) -> None:
    if not spec.ready(settings.models_path):
        raise Unavailable(
            f"The {what} model '{spec.key}' is not downloaded, so this part of search is off. "
            f"{embedder.PULL_HINT}"
        )


def text(
    session: Session, settings: Settings, project_id: str, shots: Shots, query: str, depth: int
) -> list[Item]:
    spec = embedder.choose_text(settings)
    made_with = vector_index.models_in_use(session, project_id, "segment")
    if not made_with:
        return []  # no transcript line has a vector: nothing to find, nothing wrong
    if spec.key not in made_with:
        raise Unavailable(_other_model("transcript lines", made_with, spec.key))
    _ready(spec, settings, "text")
    vector = embedder.embed_texts(spec, settings, [query])
    found = vector_index.search(session, settings, project_id, "segment", spec.key, vector, depth)
    ids = [int(ref) for ref, _ in found]
    segments = {
        s.id: s
        for s in session.scalars(select(TranscriptSegment).where(TranscriptSegment.id.in_(ids)))
    }
    items: list[Item] = []
    for ref, score in found:
        seg = segments.get(int(ref))
        if seg is None or is_uncertain(seg.avg_logprob, seg.compression_ratio):
            continue
        if score < settings.search.text_min_similarity:
            break  # the hits are ordered: everything after is less similar still
        shot = shots.at(seg.media_id, seg.start_s)
        if shot is not None:
            items.append(Item(shot, round(score, 4), seg.start_s, seg.text))
    return _best_per_shot(items)


# --- picture vectors --------------------------------------------------------------------------


def _other_model(what: str, made_with: list[str], wanted: str) -> str:
    return (
        f"The {what} were turned into vectors with {', '.join(made_with)}, but this machine's "
        f"settings use {wanted}. Press Process all in the Library to make them again, or set "
        f"the model back."
    )


def visual_model(session: Session, settings: Settings, project_id: str) -> EmbedModel:
    """The picture model to search with; Unavailable when the keyframes have no vectors of it."""
    spec = embedder.choose_visual(settings)
    made_with = vector_index.models_in_use(session, project_id, "keyframe")
    if not made_with:
        raise Unavailable(
            "No keyframe has a picture vector yet: processing has not reached that step, or the "
            f"picture model is not downloaded. {embedder.PULL_HINT}"
        )
    if spec.key not in made_with:
        raise Unavailable(_other_model("keyframes", made_with, spec.key))
    return spec


def by_picture(
    session: Session,
    settings: Settings,
    project_id: str,
    spec: EmbedModel,
    vector: Any,
    depth: int,
    leave_out: str | None = None,
) -> list[Item]:
    """Shots whose keyframes are closest to a picture-space vector (best keyframe per shot)."""
    # A shot has a few keyframes: ask for more so `depth` shots remain after merging.
    found = vector_index.search(
        session, settings, project_id, "keyframe", spec.key, vector, depth * 4
    )
    keyframes = {
        k.id: k
        for k in session.scalars(select(Keyframe).where(Keyframe.id.in_([r for r, _ in found])))
    }
    items = [
        Item(keyframes[ref].shot_id, round(score, 4), keyframes[ref].time_s)
        for ref, score in found
        if ref in keyframes and keyframes[ref].shot_id != leave_out
    ]
    return _best_per_shot(items)[:depth]


def visual(
    session: Session, settings: Settings, project_id: str, query: str, depth: int
) -> list[Item]:
    spec = visual_model(session, settings, project_id)
    _ready(spec, settings, "picture")
    prompt = settings.search.visual_prompt.format(query.strip())
    vector = embedder.embed_prompts(spec, settings, [prompt])
    return by_picture(session, settings, project_id, spec, vector, depth)


def like_shot(
    session: Session, settings: Settings, project_id: str, shot_id: str, depth: int
) -> list[Item]:
    """ "More like this": the mean picture vector of the shot's keyframes as the query."""
    spec = visual_model(session, settings, project_id)
    rows = session.scalars(
        select(Embedding.vector).where(
            Embedding.shot_id == shot_id, Embedding.kind == "keyframe", Embedding.model == spec.key
        )
    ).all()
    if not rows:
        raise InvalidInputError("That shot has no picture vectors yet. Process the clip first.")
    mean = np.mean([np.frombuffer(v, dtype=np.float32) for v in rows], axis=0)
    vector = (mean / max(float(np.linalg.norm(mean)), 1e-9)).reshape(1, -1)
    return by_picture(session, settings, project_id, spec, vector, depth, leave_out=shot_id)


def like_image(
    session: Session, settings: Settings, project_id: str, image: Any, depth: int
) -> list[Item]:
    """A picture the user dropped (BGR array) as the query."""
    spec = visual_model(session, settings, project_id)
    _ready(spec, settings, "picture")
    vector = embedder.embed_images(spec, settings, [image])
    return by_picture(session, settings, project_id, spec, vector, depth)
