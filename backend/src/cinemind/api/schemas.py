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
    # Technical Quality Score 0..1 (None until measured) and the kinds of QC flags on the clip.
    quality_score: float | None
    low_quality: bool
    qc_flags: list[str]
    # Transcript state (None until the transcribe stage ran) and the detected language.
    transcript_status: str | None
    transcript_language: str | None
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
    scene_id: str | None = None


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


class QcFlagOut(BaseModel):
    kind: str
    source: str
    shot_id: str | None
    start_s: float
    end_s: float
    # Why it was raised: metric, value, threshold, direction, or the detector and its settings.
    details: dict[str, Any]


class ShotQualityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    shot_id: str
    index: int
    frames: int
    sharpness: float
    blur: float
    luma_mean: float
    luma_std: float
    spread: float
    clipped: float
    crushed: float
    # None = focus was not judged (the shot has no tonal range, e.g. black or a plain wall).
    sharpness_score: float | None
    exposure_score: float
    contrast_score: float
    score: float


class AudioQualityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    integrated_lufs: float | None
    loudness_range: float | None
    true_peak_db: float | None
    sample_peak: float
    clipped_pct: float
    silence_s: float
    silence_pct: float
    score: float
    details: dict[str, Any]


class QualityOut(BaseModel):
    media_id: str
    measured: bool
    score: float | None
    low_quality: bool
    shots: list[ShotQualityOut]
    audio: AudioQualityOut | None
    flags: list[QcFlagOut]
    # The weights and thresholds these scores were computed with, and whether the settings
    # have changed since (reprocess to re-score).
    config: dict[str, float]
    settings_changed: bool


class TranscriptWordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start_s: float
    end_s: float
    word: str
    probability: float


class TranscriptSegmentOut(BaseModel):
    id: int
    index: int
    start_s: float
    end_s: float
    text: str
    # Mean word probability; None when the segment has no timed words.
    confidence: float | None
    avg_logprob: float
    no_speech_prob: float
    compression_ratio: float
    # The model's own acceptance limits were crossed: treat the text as a guess.
    uncertain: bool
    words: list[TranscriptWordOut]


TranscriptStatus = Literal[
    "pending", "done", "no_speech", "no_audio", "model_missing", "audio_unreadable"
]


class TranscriptOut(BaseModel):
    media_id: str
    status: TranscriptStatus
    # Plain-language explanation whenever there is no text to show.
    message: str | None
    language: str | None
    language_probability: float | None
    language_uncertain: bool
    model: str
    model_revision: str
    speech_s: float
    # Engine version, device, compute type and the settings the transcript was made with.
    details: dict[str, Any]
    # The limits behind `uncertain` and `language_uncertain`.
    thresholds: dict[str, float]
    segments: list[TranscriptSegmentOut]


class TranscriptSummary(BaseModel):
    media_id: str
    filename: str
    duration_s: float | None
    status: TranscriptStatus
    message: str | None
    language: str | None
    speech_s: float
    segments: int
    words: int


class TextPart(BaseModel):
    text: str
    match: bool


class TranscriptHit(BaseModel):
    segment_id: int
    media_id: str
    filename: str
    start_s: float
    end_s: float
    # When the first word starting with the first search term is spoken (else the segment start).
    jump_s: float
    parts: list[TextPart]
    uncertain: bool
    # BM25 rank from SQLite FTS5 (lower is better); hits are returned in this order.
    rank: float


class TranscriptSearchOut(BaseModel):
    query: str
    # How the query was read: every term must occur, each matching the start of a word.
    terms: list[str]
    hits: list[TranscriptHit]
