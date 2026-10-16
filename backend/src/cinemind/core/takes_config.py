"""Take detection settings (settings section `[takes]`, SPEC P1-B).

Two shots are takes of the same material when one of two rules holds:
- both have speech (at least `min_words` words in transcript lines not marked uncertain): their
  words agree at least `text_min` and, when both have picture vectors, the pictures at least
  `picture_min_with_text`;
- otherwise: the pictures agree at least `picture_min` and the shots are at most `max_apart`
  places apart in the project's shot order (clips by file name, then shots in source order).
A pair passing a rule scores the weighted mean of its signals (`pair_weights`); shots are grouped
by average linkage when that score is `group_min` or more on average.

The best take of a group is the one with the highest weighted mean of its signals
(`best_weights` for groups with speech, `best_weights_picture` without), leaving out shots the
user rejected. Every number here is a convention chosen before any evaluation (no labelled takes
existed); EVALUATION.md section 13 measures the grouping they give."""

from typing import Self

from pydantic import BaseModel, model_validator

SPEECH_SIGNALS = ("focus", "exposure", "audio", "complete", "clean")
PICTURE_SIGNALS = ("focus", "exposure", "audio")


class TakesConfig(BaseModel):
    min_words: int = 3
    text_min: float = 0.6
    picture_min_with_text: float = 0.5
    picture_min: float = 0.9
    max_apart: int = 3
    group_min: float = 0.75
    pair_weights: dict[str, float] = {"text": 0.6, "picture": 0.25, "adjacent": 0.15}
    pair_weights_picture: dict[str, float] = {"picture": 0.8, "adjacent": 0.2}
    best_weights: dict[str, float] = {
        "focus": 0.25,
        "exposure": 0.15,
        "audio": 0.15,
        "complete": 0.25,
        "clean": 0.2,
    }
    best_weights_picture: dict[str, float] = {"focus": 0.5, "exposure": 0.3, "audio": 0.2}
    # Speech starting or ending this close to the shot's edge counts as cut off.
    edge_s: float = 0.15
    # Filler words counted as flubs (compared lower case without punctuation).
    fillers: list[str] = ["um", "uh", "erm", "er", "hmm", "uhm", "umm"]

    @model_validator(mode="after")
    def _ranges(self) -> Self:
        for name in ("text_min", "picture_min_with_text", "picture_min", "group_min"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"takes.{name} must be 0..1")
        if not 1 <= self.min_words <= 50 or not 1 <= self.max_apart <= 100:
            raise ValueError("takes.min_words 1..50, takes.max_apart 1..100")
        if not 0 <= self.edge_s <= 2:
            raise ValueError("takes.edge_s must be 0..2")
        checks = (
            ("pair_weights", {"text", "picture", "adjacent"}),
            ("pair_weights_picture", {"picture", "adjacent"}),
            ("best_weights", set(SPEECH_SIGNALS)),
            ("best_weights_picture", set(PICTURE_SIGNALS)),
        )
        for name, allowed in checks:
            weights: dict[str, float] = getattr(self, name)
            if set(weights) - allowed or any(w < 0 for w in weights.values()):
                raise ValueError(f"takes.{name}: names {sorted(allowed)}, weights 0 or more")
            if sum(weights.values()) <= 0:
                raise ValueError(f"takes.{name} cannot all be 0")
        return self
