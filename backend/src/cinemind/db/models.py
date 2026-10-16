"""ORM models. Later phases add tables through Alembic migrations."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cinemind.db.base import Base, UTCDateTime, new_id, utcnow

JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
STAGE_STATUSES = ("pending", "running", "succeeded", "cached", "failed", "cancelled")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    # Per-project choices made in the app (not the machine's settings file), e.g. the spoken
    # languages: {"speech": {"languages": ["en", "kn"], "detect_only": ["kn"]}}.
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")


class MediaAsset(Base):
    """One source file: identity, ffprobe metadata (filled by the validate stage) and artifacts."""

    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    import_mode: Mapped[str] = mapped_column(String(16), default="reference")
    size_bytes: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    # ffprobe metadata (None until the validate stage succeeded)
    probed: Mapped[bool] = mapped_column(default=False)
    container: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_s: Mapped[float | None] = mapped_column(nullable=True)
    width: Mapped[int | None] = mapped_column(nullable=True)
    height: Mapped[int | None] = mapped_column(nullable=True)
    fps_num: Mapped[int | None] = mapped_column(nullable=True)
    fps_den: Mapped[int | None] = mapped_column(nullable=True)
    is_vfr: Mapped[bool] = mapped_column(default=False)
    # The stream's base rate; `fps_*` above is the measured average (they differ for VFR).
    nominal_fps_num: Mapped[int | None] = mapped_column(nullable=True)
    nominal_fps_den: Mapped[int | None] = mapped_column(nullable=True)
    video_codec: Mapped[str | None] = mapped_column(String(50), nullable=True)
    audio_codec: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bit_rate: Mapped[int | None] = mapped_column(nullable=True)
    audio_channels: Mapped[int | None] = mapped_column(nullable=True)
    audio_sample_rate: Mapped[int | None] = mapped_column(nullable=True)
    start_timecode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    color: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Derived artifacts, relative to the project directory (None until generated)
    proxy_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    poster_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    strip_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    waveform_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Technical Quality Score of the whole clip, 0..1 (None until the quality stages ran).
    quality_score: Mapped[float | None] = mapped_column(nullable=True)
    # Language of the speech as set by the user for this clip (None = detect it among the
    # project's spoken languages).
    speech_language: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        Index("ix_media_project", "project_id"),
        UniqueConstraint("project_id", "content_hash", name="uq_media_project_hash"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    media_id: Mapped[str | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=True
    )
    chain: Mapped[str] = mapped_column(String(100))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    progress: Mapped[float] = mapped_column(default=0.0)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    stages: Mapped[list["JobStage"]] = relationship(
        back_populates="job", order_by="JobStage.ordinal", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_jobs_status", "status"),)


class JobStage(Base):
    __tablename__ = "job_stages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    ordinal: Mapped[int]
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    progress: Mapped[float] = mapped_column(default=0.0)
    # Provenance (CLAUDE.md rules 5 and 6): what exactly produced this stage's output.
    cache_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    params_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str] = mapped_column(String(100), default="")
    model_version: Mapped[str] = mapped_column(String(100), default="")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    job: Mapped[Job] = relationship(back_populates="stages")

    __table_args__ = (UniqueConstraint("job_id", "ordinal"),)


class StageResult(Base):
    """Cache: (media content hash, stage, params hash, model name+version) -> result."""

    __tablename__ = "stage_results"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    media_hash: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(100))
    params_hash: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(100))
    model_version: Mapped[str] = mapped_column(String(100))
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class JobEvent(Base):
    """Append-only event log; the SSE endpoint streams it and clients resume by id."""

    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Shot(Base):
    """A continuous run of frames between two detected cuts, on the analysis proxy's frame grid.
    `end_*` is exclusive. The id is derived from (media, frames) so re-detection keeps it stable."""

    __tablename__ = "shots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"))
    index: Mapped[int]
    start_frame: Mapped[int]
    end_frame: Mapped[int]
    start_s: Mapped[float]
    end_s: Mapped[float]
    # Frame rate the frames above are counted in (the constant-rate proxy), as a rational.
    fps_num: Mapped[int]
    fps_den: Mapped[int]
    # Rule 6: detector, threshold, minimum length and library version that produced this shot.
    detection: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Set by the scene grouping (`pipeline/scenes.py`); None until the project was grouped.
    scene_id: Mapped[str | None] = mapped_column(
        ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True
    )

    keyframes: Mapped[list["Keyframe"]] = relationship(
        order_by="Keyframe.slot", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_shots_media", "media_id", "index"),
        Index("ix_shots_scene", "scene_id"),
    )


class Keyframe(Base):
    """A representative frame of a shot: the sharpest candidate near one anchor point."""

    __tablename__ = "keyframes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    shot_id: Mapped[str] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"))
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"))
    slot: Mapped[int]
    frame: Mapped[int]
    time_s: Mapped[float]
    path: Mapped[str] = mapped_column(Text)  # relative to the project directory
    sharpness: Mapped[float]  # variance of the Laplacian; why this candidate was picked

    __table_args__ = (Index("ix_keyframes_shot", "shot_id"),)


class Timeline(Base):
    __tablename__ = "timelines"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32))
    fps_num: Mapped[int]
    fps_den: Mapped[int]
    width: Mapped[int]
    height: Mapped[int]
    # How it was built (rule 6): options, ordering, what was left out and why.
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    items: Mapped[list["TimelineItem"]] = relationship(
        order_by="TimelineItem.position", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (Index("ix_timelines_project", "project_id"),)


class TimelineItem(Base):
    """One cut on the timeline: a source range of an original file, stored in seconds."""

    __tablename__ = "timeline_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    timeline_id: Mapped[str] = mapped_column(ForeignKey("timelines.id", ondelete="CASCADE"))
    position: Mapped[int]
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"))
    shot_id: Mapped[str | None] = mapped_column(
        ForeignKey("shots.id", ondelete="SET NULL"), nullable=True
    )
    source_in_s: Mapped[float]
    source_out_s: Mapped[float]
    # Rough cuts (rule 6): search rank, score breakdown, how it was trimmed, and a summary.
    reason: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (Index("ix_timeline_items_timeline", "timeline_id", "position"),)


class QualityMetric(Base):
    """Technical picture metrics of one shot (median over sampled frames), the sub-scores
    derived from them, and in `details` the weights and thresholds used (rule 6)."""

    __tablename__ = "quality_metrics"

    shot_id: Mapped[str] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), primary_key=True
    )
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"))
    frames: Mapped[int]
    sharpness: Mapped[float]
    blur: Mapped[float]
    luma_mean: Mapped[float]
    luma_std: Mapped[float]
    spread: Mapped[float]
    clipped: Mapped[float]
    crushed: Mapped[float]
    # None when focus could not be judged (no tonal range in the shot).
    sharpness_score: Mapped[float | None] = mapped_column(nullable=True)
    exposure_score: Mapped[float]
    contrast_score: Mapped[float]
    score: Mapped[float]
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (Index("ix_quality_media", "media_id"),)


class AudioMetric(Base):
    """Audio measurements of one clip's first audio stream (from the original file)."""

    __tablename__ = "audio_metrics"

    media_id: Mapped[str] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), primary_key=True
    )
    integrated_lufs: Mapped[float | None] = mapped_column(nullable=True)
    loudness_range: Mapped[float | None] = mapped_column(nullable=True)
    true_peak_db: Mapped[float | None] = mapped_column(nullable=True)
    sample_peak: Mapped[float]
    clipped_pct: Mapped[float]
    silence_s: Mapped[float]
    silence_pct: Mapped[float]
    score: Mapped[float]
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class QcFlag(Base):
    """A technical problem on a time range, with the measured value and the threshold crossed."""

    __tablename__ = "qc_flags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"))
    shot_id: Mapped[str | None] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(16))  # which stage wrote it: picture | audio
    start_s: Mapped[float]
    end_s: Mapped[float]
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (Index("ix_qc_flags_media", "media_id"),)


TRANSCRIPT_STATUSES = ("done", "no_speech", "no_audio", "model_missing", "audio_unreadable")


class Transcript(Base):
    """What the transcribe stage found for one clip, and what produced it (rule 6)."""

    __tablename__ = "transcripts"

    media_id: Mapped[str] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(32))
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    language_probability: Mapped[float | None] = mapped_column(nullable=True)
    model: Mapped[str] = mapped_column(String(100), default="")
    model_revision: Mapped[str] = mapped_column(String(64), default="")
    # Seconds of audio the voice-activity detector kept as speech.
    speech_s: Mapped[float] = mapped_column(default=0.0)
    # Hash of the stage result these rows were written from: an unchanged result keeps its rows
    # (and their ids) when a clip is processed again.
    digest: Mapped[str] = mapped_column(String(64), default="")
    # Engine version, device, compute type, settings, and the reason when there is no text.
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class TranscriptSegment(Base):
    """One stretch of speech. `text` is indexed for keyword search in the FTS5 table
    `transcript_fts`, kept in step by triggers (see migration 0006)."""

    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"))
    index: Mapped[int]
    start_s: Mapped[float]
    end_s: Mapped[float]
    text: Mapped[str] = mapped_column(Text)
    # Mean word probability (None if the segment has no timed words) and the model's own
    # per-segment figures.
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    avg_logprob: Mapped[float]
    no_speech_prob: Mapped[float]
    compression_ratio: Mapped[float]

    words: Mapped[list["TranscriptWord"]] = relationship(
        order_by="TranscriptWord.index", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (Index("ix_transcript_segments_media", "media_id", "index"),)


class TranscriptWord(Base):
    __tablename__ = "transcript_words"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    segment_id: Mapped[int] = mapped_column(
        ForeignKey("transcript_segments.id", ondelete="CASCADE")
    )
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"))
    index: Mapped[int]
    start_s: Mapped[float]
    end_s: Mapped[float]
    word: Mapped[str] = mapped_column(String(200))
    probability: Mapped[float]

    __table_args__ = (Index("ix_transcript_words_segment", "segment_id", "index"),)


# Faces and actors, the Phase 8 analysis tables and the script tables live in their own modules;
# importing them here registers their tables.
from cinemind.db import analysis as analysis  # noqa: E402
from cinemind.db import people as people  # noqa: E402
from cinemind.db import script as script  # noqa: E402
