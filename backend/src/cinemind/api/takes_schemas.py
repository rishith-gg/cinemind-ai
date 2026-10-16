"""Schemas of take groups and the user's take corrections (SPEC P1-B)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TakeShotOut(BaseModel):
    shot_id: str
    media_id: str
    filename: str
    index: int
    start_s: float
    end_s: float
    keyframe_id: str | None
    mark: Literal["select", "reject"] | None = None
    stars: int = 0


class TakeMemberOut(TakeShotOut):
    rank: int  # 1 = the best take (or the user's pick)
    best: bool
    # Weighted mean of the signals below (None when none was measured).
    score: float | None
    # focus, exposure, audio (and for speech groups complete, clean): each 0..1 or None.
    signals: dict[str, float | None]
    notes: list[str]  # flubs, cut-off speech, rejected, ...
    text: str  # the words heard in the shot


class TakePairOut(BaseModel):
    """Why two members were linked (or not): the signals, the rule and the pair score."""

    a: str
    b: str
    rule: str  # speech | picture | none
    text: float | None
    picture: float | None
    adjacent: float
    score: float
    why: str


class TakeGroupOut(BaseModel):
    id: str
    index: int
    kind: Literal["speech", "picture"]
    best_shot_id: str | None
    best_by: Literal["auto", "you", "none"]
    members: list[TakeMemberOut]
    pairs: list[TakePairOut]


class TakeGroupsOut(BaseModel):
    groups: list[TakeGroupOut]
    # Shots the user took out of a take group (they stay apart from those shots).
    kept_apart: list[TakeShotOut]
    grouped_at: datetime | None
    # Model, settings, counts of the last grouping (rule 6).
    details: dict[str, Any]
    settings: dict[str, Any]
    shots: int
    message: str | None = None


class TakeBestIn(BaseModel):
    shot_id: str = Field(min_length=1, max_length=32)
    # True: this take is the best of its group; False: the signals decide again.
    best: bool = True


class TakeApartIn(BaseModel):
    shot_id: str = Field(min_length=1, max_length=32)
    # True: not a take of the others in its group; False: forget those answers.
    apart: bool = True
