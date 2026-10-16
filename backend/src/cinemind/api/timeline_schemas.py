"""Schemas of timelines: the "all shots" timeline, the AI-assisted rough cut, and the editor's
changes to either."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, Field

from cinemind.core.rough_cut_config import Order


def _clean_name(value: str) -> str:
    value = value.strip()
    if not value or any(ord(ch) < 32 for ch in value):
        raise ValueError("The name must contain visible characters and no control characters.")
    return value


Name = Annotated[str, Field(min_length=1, max_length=200), AfterValidator(_clean_name)]


class TimelineCreate(BaseModel):
    name: Name = "All shots"
    kind: Literal["all_shots"] = "all_shots"
    # Timeline frame rate as [numerator, denominator]; omit to use the most common clip rate.
    fps: tuple[int, int] | None = None
    mixed_rates: Literal["include", "exclude"] = "include"


class RoughCutCreate(BaseModel):
    # e.g. "2-minute sequence about the grandfather walking home at night"
    brief: str = Field(min_length=1, max_length=1000)
    # Seconds; omit to take the length from the brief, else `[rough_cut] default_target_s`.
    target_s: float | None = Field(default=None, ge=1, le=3600, allow_inf_nan=False)
    # Omit to take the order from the brief, else `[rough_cut] order`.
    order: Order | None = None
    actor_id: str | None = None
    scene_id: str | None = None
    name: Name | None = None
    fps: tuple[int, int] | None = None


Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class TimelineItemEdit(BaseModel):
    id: str
    source_in_s: Seconds
    source_out_s: Seconds


class TimelineUpdate(BaseModel):
    name: Name | None = None
    # The whole new item list, in order: items left out are removed.
    items: list[TimelineItemEdit] | None = Field(default=None, max_length=5000)


class SwapRequest(BaseModel):
    shot_id: str


class TimelineItemOut(BaseModel):
    id: str
    position: int
    media_id: str
    shot_id: str | None
    filename: str
    source_in_s: float
    source_out_s: float
    record_frame: int
    duration_frames: int
    source_fps_num: int
    source_fps_den: int
    mixed_rate: bool
    media_duration_s: float | None = None
    shot_start_s: float | None = None
    shot_end_s: float | None = None
    scene_id: str | None = None
    # The take group the shot is in now (other takes of it are offered first as swaps).
    take_group_id: str | None = None
    keyframe_id: str | None = None
    # Rough cuts: search rank, score breakdown, how it was trimmed, and a one-line summary.
    reason: dict[str, Any] | None = None


class AlternativeOut(BaseModel):
    shot_id: str
    media_id: str
    filename: str
    start_s: float
    end_s: float
    scene_id: str | None
    take_group_id: str | None = None
    keyframe_id: str | None
    summary: str
    rank: int | None


class TimelineOut(BaseModel):
    id: str
    project_id: str
    name: str
    kind: str
    fps_num: int
    fps_den: int
    width: int
    height: int
    params: dict[str, Any]
    created_at: datetime
    item_count: int
    duration_frames: int
    duration_s: float
    warnings: list[str]
    export_dir: str
    formats: list[str]


class TimelineDetail(TimelineOut):
    items: list[TimelineItemOut]
    alternatives: list[AlternativeOut] = []
