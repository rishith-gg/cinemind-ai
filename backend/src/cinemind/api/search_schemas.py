"""API schemas for hybrid search."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cinemind.api.schemas import TextPart

ListName = Literal["keyword", "labels", "text", "visual"]


class SearchFilters(BaseModel):
    media_id: str | None = Field(default=None, max_length=32)
    actor_id: str | None = Field(default=None, max_length=32)
    scene_id: str | None = Field(default=None, max_length=32)
    min_quality: float | None = Field(default=None, ge=0, le=1)
    has_dialogue: bool = False


class SearchRequest(BaseModel):
    # A typed query, or a shot to find more like ("more like this"); one of the two.
    q: str | None = Field(default=None, max_length=200)
    like_shot_id: str | None = Field(default=None, max_length=32)
    filters: SearchFilters = SearchFilters()
    # Which result lists to use (default: all); for comparing them.
    use: list[ListName] | None = None


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


class JudgmentIn(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    shot_id: str = Field(min_length=1, max_length=32)
    # True = a good result, False = not, None = take the judgment back.
    relevant: bool | None


class JudgmentOut(JudgmentIn):
    judged: int  # judgments the user has made in this project
