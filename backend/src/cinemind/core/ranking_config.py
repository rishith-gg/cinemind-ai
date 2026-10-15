"""Ranking settings (settings section `[ranking]`, SPEC section 10).

final = relevance·w + quality·w + selection·w + person·w + scene·w - duplicate·w, every signal
0..1 (see `search/ranking.py`). The default weights are conventions chosen before any
evaluation: relevance leads, the others nudge. They are heuristics, not validated values; the
Search page lets the editor change them and see the order change."""

from typing import Self

from pydantic import BaseModel, model_validator

SIGNALS = ("relevance", "quality", "selection", "person", "scene", "duplicate")


DEFAULT_WEIGHTS = {
    "relevance": 1.0,
    "quality": 0.2,
    "selection": 0.3,
    "person": 0.1,
    "scene": 0.1,
    "duplicate": 0.3,
}


class RankingConfig(BaseModel):
    # Signals left out keep their default (setting one weight never turns the others off).
    weights: dict[str, float] = dict(DEFAULT_WEIGHTS)
    # Two shots count as duplicates only above this picture similarity (cosine of their mean
    # keyframe vectors); the penalty grows from 0 there to 1 at identical pictures. A convention:
    # on the user's footage half of all shot pairs are above 0.45 and 1 % above 0.82 (printed by
    # eval/search_eval.py), so 0.85 keeps the penalty for near-identical shots.
    duplicate_threshold: float = 0.85

    @model_validator(mode="after")
    def _known(self) -> Self:
        check_weights(self.weights)
        self.weights = {**DEFAULT_WEIGHTS, **self.weights}
        if not 0 <= self.duplicate_threshold < 1:
            raise ValueError("ranking.duplicate_threshold must be at least 0 and below 1")
        return self


def check_weights(weights: dict[str, float]) -> None:
    unknown = set(weights) - set(SIGNALS)
    if unknown:
        raise ValueError(f"unknown ranking signals: {', '.join(sorted(unknown))}")
    if any(not 0 <= w <= 5 for w in weights.values()):
        raise ValueError("ranking weights go from 0 to 5")
