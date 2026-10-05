"""ORM models for Phase 1. Later phases add tables through Alembic migrations."""

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


class MediaAsset(Base):
    """One source file. Phase 1 only has identity; Phase 3 adds ffprobe metadata."""

    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (Index("ix_media_project", "project_id"),)


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
