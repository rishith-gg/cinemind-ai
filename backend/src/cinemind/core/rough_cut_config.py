"""Rough cut settings (settings section `[rough_cut]`, SPEC section 11).

Every number here is an editing convention chosen before any evaluation, not a tuned value:
a phone-footage rough cut wants clips of a few seconds, whole sentences where people speak, and
nothing the quality check scored as poor. The editor changes the result on the Timeline page."""

from typing import Literal, Self

from pydantic import BaseModel, model_validator

Order = Literal["chronological", "scene", "score"]
ORDERS: tuple[Order, ...] = ("chronological", "scene", "score")


class RoughCutConfig(BaseModel):
    # Length of the cut when the brief names none.
    default_target_s: float = 60.0
    # The cut may end up this much shorter or longer than the target (a clip is not cut
    # mid-sentence to hit the target exactly).
    tolerance: float = 0.1
    # Shots whose Technical Quality Score is below this are left out (the QC "low quality" limit).
    min_quality: float = 0.5
    # A clip without speech is cut to at most this long, around the moment that matched.
    max_clip_s: float = 6.0
    # Shorter shots are not used (they read as flashes in a rough cut).
    min_clip_s: float = 1.5
    # A clip with speech keeps whole lines, plus this much room before and after.
    speech_pad_s: float = 0.25
    # ... and is at most this long (later lines are dropped, never cut in the middle).
    max_speech_clip_s: float = 15.0
    # How many ranked search results are considered.
    candidates: int = 50
    # Unused candidates kept on the timeline as swap suggestions.
    alternatives: int = 20
    order: Order = "chronological"

    @model_validator(mode="after")
    def _ranges(self) -> Self:
        if not 1 <= self.default_target_s <= 3600:
            raise ValueError("rough_cut.default_target_s must be between 1 and 3600")
        if not 0 <= self.tolerance < 1 or not 0 <= self.min_quality <= 1:
            raise ValueError("rough_cut.tolerance must be 0..1 (below 1), min_quality 0..1")
        if not 0 < self.min_clip_s <= self.max_clip_s <= self.max_speech_clip_s:
            raise ValueError("rough_cut: 0 < min_clip_s <= max_clip_s <= max_speech_clip_s")
        if not 0 <= self.speech_pad_s <= 2:
            raise ValueError("rough_cut.speech_pad_s must be between 0 and 2")
        if not 1 <= self.candidates <= 500 or not 0 <= self.alternatives <= 100:
            raise ValueError("rough_cut.candidates 1..500, alternatives 0..100")
        return self
