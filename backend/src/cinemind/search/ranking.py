"""Ranking the fused search results (SPEC section 10): a weighted sum of signals with a
duplicate penalty, decided greedily (Maximal Marginal Relevance, Carbonell and Goldstein 1998).

Signals, each 0..1:
- relevance: the shot's fused RRF score scaled to the results: the best 1, the last 0 (a single
  result 1). RRF scores are close together (rank 1 and rank 10 differ by 13 % at k = 60), so
  dividing by the best one would let a small quality weight outvote relevance.
- quality: the shot's Technical Quality Score (0 when not measured; the breakdown says so).
- selection: 1 for a shot the user selected, otherwise its stars / 5.
- person / scene: 1 when the query matched the name of a person the user named, or of the
  shot's scene (the labels list says which).
- duplicate: how near-identical the shot's picture is to one already placed higher: the cosine
  of mean keyframe vectors, 0 up to `[ranking] duplicate_threshold` (0.85) and rising to 1 at
  identical pictures. It is subtracted. Off for "more like this" and picture searches, whose
  results look alike by design.

Each step places the remaining shot with the highest `sum(w * signal) - w_dup * duplicate`;
ties go to the smaller shot id, so the same weights always give the same order. Ours: the
signals, their normalisation and the default weights (conventions, `[ranking]`); MMR is the
existing method. The breakdown of every result is returned so the UI can show why.
"""

# numpy arrays are untyped.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemind.core.config import Settings
from cinemind.core.ranking_config import SIGNALS
from cinemind.db.analysis import Embedding
from cinemind.db.models import QualityMetric
from cinemind.pipeline import shot_marks
from cinemind.search import hybrid
from cinemind.search.hybrid import Fused
from cinemind.search.retrievers import Unavailable, visual_model


@dataclass
class Ranked:
    fused: Fused
    final: float
    # signal -> (value 0..1, weight, contribution to `final`; negative for the duplicate)
    breakdown: dict[str, tuple[float, float, float]] = field(default_factory=lambda: {})
    duplicate_of: str | None = None
    notes: list[str] = field(default_factory=lambda: [])


def _mean_vectors(
    session: Session, settings: Settings, project_id: str, shot_ids: list[str]
) -> dict[str, Any]:
    try:
        spec = visual_model(session, settings, project_id)
    except Unavailable:
        return {}
    rows = session.execute(
        select(Embedding.shot_id, Embedding.vector).where(
            Embedding.shot_id.in_(shot_ids),
            Embedding.kind == "keyframe",
            Embedding.model == spec.key,
        )
    )
    sums: dict[str, Any] = {}
    for shot_id, blob in rows:
        vector = np.frombuffer(blob, dtype=np.float32)
        sums[str(shot_id)] = sums.get(str(shot_id), 0) + vector
    return {s: v / max(float(np.linalg.norm(v)), 1e-9) for s, v in sums.items()}


def rank(
    session: Session,
    settings: Settings,
    project_id: str,
    fused: list[Fused],
    weights: dict[str, float],
) -> list[Ranked]:
    if not fused:
        return []
    w = {name: float(weights.get(name, 0.0)) for name in SIGNALS}
    threshold = settings.ranking.duplicate_threshold
    ids = [f.shot_id for f in fused]
    quality = dict(
        session.execute(
            select(QualityMetric.shot_id, QualityMetric.score).where(QualityMetric.shot_id.in_(ids))
        ).all()
    )
    marks = shot_marks.marks_for(session, ids)
    vectors = _mean_vectors(session, settings, project_id, ids) if w["duplicate"] > 0 else {}
    best, worst = max(f.score for f in fused), min(f.score for f in fused)
    spread = best - worst

    values: dict[str, dict[str, float]] = {}  # unrounded; rounded only for the breakdown
    gains: dict[str, float] = {}
    for f in fused:
        mark = marks.get(f.shot_id)
        matched = f.parts["labels"][0].matched if "labels" in f.parts else []
        if mark is None or mark.mark == "reject":  # shown only with "show rejected"
            selection = 0.0
        else:
            selection = 1.0 if mark.mark == "select" else mark.stars / 5
        values[f.shot_id] = {
            "relevance": (f.score - worst) / spread if spread > 0 else 1.0,
            "quality": float(quality.get(f.shot_id) or 0.0),
            "selection": selection,
            "person": 1.0 if any(m.startswith("actor: ") for m in matched) else 0.0,
            "scene": 1.0 if any(m.startswith("scene: ") for m in matched) else 0.0,
        }
        gains[f.shot_id] = sum(v * w[name] for name, v in values[f.shot_id].items())

    # MMR with a running maximum: after each placement only the similarity to the shot just
    # placed has to be checked.
    by_id = {f.shot_id: f for f in fused}
    penalty: dict[str, tuple[float, str | None]] = {s: (0.0, None) for s in ids}
    placed: list[Ranked] = []
    remaining = sorted(ids)
    while remaining:
        shot_id = max(
            remaining, key=lambda s: (gains[s] - w["duplicate"] * penalty[s][0], _desc(s))
        )
        duplicate, like = penalty[shot_id]
        entry = Ranked(by_id[shot_id], round(gains[shot_id] - w["duplicate"] * duplicate, 6))
        for name, value in values[shot_id].items():
            entry.breakdown[name] = (round(value, 4), w[name], round(value * w[name], 4))
        entry.breakdown["duplicate"] = (
            round(duplicate, 4),
            w["duplicate"],
            round(-duplicate * w["duplicate"], 4),
        )
        entry.duplicate_of = like
        if shot_id not in quality:
            entry.notes.append("quality not measured")
        placed.append(entry)
        remaining.remove(shot_id)
        vector = vectors.get(shot_id)
        if vector is None:
            continue
        for other in remaining:
            other_vector = vectors.get(other)
            if other_vector is None:
                continue
            cosine = float(vector @ other_vector)
            scaled = max(0.0, (cosine - threshold) / (1 - threshold))
            if scaled > penalty[other][0]:
                penalty[other] = (scaled, shot_id)
    return placed


def _desc(shot_id: str) -> tuple[int, ...]:
    """Sort key that makes `max` prefer the smaller shot id on equal scores."""
    return tuple(-ord(ch) for ch in shot_id)


def run_ranked(
    session: Session,
    settings: Settings,
    project_id: str,
    query: hybrid.Query,
    weights: dict[str, float],
) -> tuple[hybrid.Outcome, list[Ranked]]:
    """Fuse the lists for `query` and rank the result with `weights` (already merged with the
    defaults by the caller). A search by a shot or a picture finds look-alikes by design, so
    the duplicate penalty is off for it."""
    outcome = hybrid.run(session, settings, project_id, query)
    if query.like_shot_id or query.image is not None:
        weights = {**weights, "duplicate": 0.0}
    return outcome, rank(session, settings, project_id, outcome.results, weights)
