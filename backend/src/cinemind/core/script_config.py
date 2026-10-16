"""Script alignment settings (settings section `[script]`, SPEC P1-A).

A take's score is `(lexical_weight * lexical + semantic_weight * semantic) / (sum of weights)`.
A line counts as found when its best take reaches `min_score`. Without the text model the
lexical score is used alone, with `words_only_min_score`. Weights and limits were chosen in
eval/script_align.py on the development half of the Tears of Steel subtitles (EVALUATION.md
section 12, D-097): meaning alone with limit 0.3 scored best there (words alone: 0.45). On 48
lines per half the variants differ by a few lines only, so this is a weak preference; the
lexical match still sets each take's in and out points."""

from typing import Self

from pydantic import BaseModel, model_validator


class ScriptConfig(BaseModel):
    lexical_weight: float = 0.0
    semantic_weight: float = 1.0
    min_score: float = 0.3
    words_only_min_score: float = 0.45
    # A line may be spoken over up to this many neighbouring transcript segments of one clip,
    # when the pause between them is at most `max_gap_s`.
    max_window: int = 3
    max_gap_s: float = 2.0
    # Takes kept per line (the best first), for the user to choose from.
    takes_kept: int = 5

    def limit(self, semantic: bool) -> float:
        """The match limit for an alignment made with (True) or without the text model."""
        return self.min_score if semantic else self.words_only_min_score

    @model_validator(mode="after")
    def _ranges(self) -> Self:
        if self.lexical_weight < 0 or self.semantic_weight < 0:
            raise ValueError("script weights must be 0 or more")
        if self.lexical_weight + self.semantic_weight <= 0:
            raise ValueError("script weights cannot both be 0")
        if not 0 <= self.min_score <= 1 or not 0 <= self.words_only_min_score <= 1:
            raise ValueError("script.min_score and words_only_min_score must be 0..1")
        if not 1 <= self.max_window <= 10:
            raise ValueError("script.max_window 1..10")
        if not 0 <= self.max_gap_s <= 30 or not 1 <= self.takes_kept <= 20:
            raise ValueError("script.max_gap_s 0..30, takes_kept 1..20")
        return self
