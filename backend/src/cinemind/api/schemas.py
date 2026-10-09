"""Pydantic schemas at the API boundary."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ErrorResponse(BaseModel):
    code: str
    message: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    created_at: datetime
    updated_at: datetime


class JobStageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ordinal: int
    name: str
    status: str
    progress: float
    cache_key: str | None
    params_hash: str | None
    model_name: str
    model_version: str
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None
    media_id: str | None
    chain: str
    status: str
    progress: float
    cancel_requested: bool
    error_code: str | None
    error_message: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    stages: list[JobStageOut]


class JobEventOut(BaseModel):
    id: int
    job_id: str
    type: str
    data: dict[str, Any]


class JobBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    progress: float
    error_code: str | None
    error_message: str | None


class MediaOut(BaseModel):
    id: str
    project_id: str
    filename: str
    path: str
    import_mode: str
    size_bytes: int
    content_hash: str
    created_at: datetime
    source_missing: bool
    probed: bool
    container: str | None
    duration_s: float | None
    width: int | None
    height: int | None
    fps_num: int | None
    fps_den: int | None
    is_vfr: bool
    video_codec: str | None
    audio_codec: str | None
    bit_rate: int | None
    audio_channels: int | None
    audio_sample_rate: int | None
    start_timecode: str | None
    color: dict[str, Any]
    has_proxy: bool
    has_poster: bool
    has_strip: bool
    has_waveform: bool
    proxy_encoder: str | None
    strip_frames: int
    job: JobBrief | None


class ImportRequest(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=500)
    mode: Literal["reference", "copy"] = "reference"


class ImportItem(BaseModel):
    path: str
    media: MediaOut | None = None
    duplicate: bool = False
    error_code: str | None = None
    error_message: str | None = None


class ImportResponse(BaseModel):
    items: list[ImportItem]


class RelinkRequest(BaseModel):
    path: str


class FsEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size_bytes: int | None
    is_media_candidate: bool


class FsListing(BaseModel):
    path: str | None
    parent: str | None
    roots: list[str]
    entries: list[FsEntry]


class KeyframeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slot: int
    frame: int
    time_s: float
    sharpness: float


class ShotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    media_id: str
    index: int
    start_frame: int
    end_frame: int
    start_s: float
    end_s: float
    fps_num: int
    fps_den: int
    detection: dict[str, Any]
    keyframes: list[KeyframeOut]


class ProjectShotOut(ShotOut):
    filename: str


class TimelineCreate(BaseModel):
    name: str = Field(default="All shots", min_length=1, max_length=200)
    kind: Literal["all_shots"] = "all_shots"
    # Timeline frame rate as [numerator, denominator]; omit to use the most common clip rate.
    fps: tuple[int, int] | None = None
    mixed_rates: Literal["include", "exclude"] = "include"

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(ch) < 32 for ch in value):
            raise ValueError("The name must contain visible characters and no control characters.")
        return value


class TimelineItemOut(BaseModel):
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
