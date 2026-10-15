"""API schemas for hybrid search."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cinemind.api.schemas import TextPart
from cinemind.core.ranking_config import check_weights

ListName = Literal["keyword", "labels", "text", "visual"]


class SearchFilters(BaseModel):
    media_id: str | None = Field(default=None, max_length=32)
    actor_id: str | None = Field(default=None, max_length=32)
    scene_id: str | None = Field(default=None, max_length=32)
    min_quality: float | None = Field(default=None, ge=0, le=1)
    has_dialogue: bool = False
    selects_only: bool = False
    # Rejected shots are left out unless this is set.
    include_rejected: bool = False


class SearchRequest(BaseModel):
    # A typed query, or a shot to find more like ("more like this"); one of the two.
    q: str | None = Field(default=None, max_length=200)
    like_shot_id: str | None = Field(default=None, max_length=32)
    filters: SearchFilters = SearchFilters()
    # Which result lists to use (default: all); for comparing them.
    use: list[ListName] | None = None
    # Ranking weights to try instead of the `[ranking]` ones ("what if"); missing = default.
    weights: dict[str, float] | None = None

    @field_validator("weights")
    @classmethod
    def _weights(cls, value: dict[str, float] | None) -> dict[str, float] | None:
        if value is not None:
            check_weights(value)
        return value


class SignalOut(BaseModel):
    value: float  # 0..1
    weight: float
    contribution: float  # value x weight; negative for the duplicate penalty


class ListHit(BaseModel):
    """Why a result is there, for one list."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    rank: int  # in that list, from 1
    score: float  # the list's own score: BM25 (lower is better), words matched, or cosine
    contribution: float  # what the list added to the fused score: weight / (k + rank)
    time_s: float
    text: str | None = None
    parts: list[TextPart] | None = None
    matched: list[str] = []


class SearchResult(BaseModel):
    shot_id: str
    media_id: str
    filename: str
    shot_index: int
    start_s: float
    end_s: float
    jump_s: float
    keyframe_url: str | None
    scene_name: str | None
    quality_score: float | None
    score: float  # fused RRF score (heuristic, only meaningful as an order)
    why: dict[str, ListHit]
    # The ranking: final score (sum of the contributions) and how each signal added to it; the
    # shot it looks most alike among those placed higher (the duplicate penalty), if any.
    final: float
    breakdown: dict[str, SignalOut]
    duplicate_of: str | None
    notes: list[str]
    mark: Literal["select", "reject"] | None
    stars: int
    # The user's judgment of this result for this query (None = not judged).
    relevant: bool | None


class SearchOut(BaseModel):
    query: str | None
    like_shot_id: str | None
    results: list[SearchResult]
    # Shots each list found (after filters), and lists that could not run with the reason.
    lists: dict[str, int]
    unavailable: dict[str, str]
    rrf_k: int
    weights: dict[str, float]
    # The ranking weights used for this order, and the `[ranking]` defaults (for "reset").
    ranking_weights: dict[str, float]
    ranking_defaults: dict[str, float]


class JudgmentIn(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    shot_id: str = Field(min_length=1, max_length=32)
    # True = a good result, False = not, None = take the judgment back.
    relevant: bool | None


class JudgmentOut(JudgmentIn):
    judged: int  # judgments the user has made in this project


class MarkIn(BaseModel):
    # "select", "reject", "none" (clear); leave out to keep the mark as it is.
    mark: Literal["select", "reject", "none"] | None = None
    # 0..5; leave out to keep the stars as they are.
    stars: int | None = Field(default=None, ge=0, le=5)


class MarkOut(BaseModel):
    shot_id: str
    mark: Literal["select", "reject"] | None
    stars: int
