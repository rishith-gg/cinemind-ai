"""ORM models for faces and actors (Phase 7). Registered with the others through `db.models`."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cinemind.db.base import Base, UTCDateTime, new_id, utcnow

FACE_SCAN_STATUSES = ("done", "no_faces", "no_video", "model_missing")
# Where a track stands: grouped by similarity, placed by the user, set aside by the user, or set
# aside automatically because it was seen too briefly.
TRACK_STATES = ("auto", "pinned", "ignored", "unknown", "brief")
# actor = put there by the user; kept = was there when the user named or corrected the actor.
PIN_STATES = ("actor", "kept", "ignored", "unknown")


def _media_fk() -> Mapped[str]:
    return mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"))


class FaceScan(Base):
    """What the faces stage found in one clip, and what produced it (rule 6)."""

    __tablename__ = "face_scans"

    media_id: Mapped[str] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(32))
    frames_sampled: Mapped[int] = mapped_column(default=0)
    faces_detected: Mapped[int] = mapped_column(default=0)
    faces_used: Mapped[int] = mapped_column(default=0)
    max_in_frame: Mapped[int] = mapped_column(default=0)
    # Hash of the stage result the rows were written from: an unchanged result keeps its rows.
    digest: Mapped[str] = mapped_column(String(64), default="")
    # Models and revisions, settings, how many faces each check rejected, and any reason.
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Actor(Base):
    """A group of face tracks the app believes show one person. Local to the project; never
    matched to a real-world identity. `name` is "Actor 001" until the user renames it."""

    __tablename__ = "actors"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    number: Mapped[int]
    name: Mapped[str] = mapped_column(String(100))
    named: Mapped[bool] = mapped_column(default=False)  # True once the user chose the name
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (Index("ix_actors_project", "project_id", "number"),)


class FaceTrack(Base):
    """One face followed through one shot. `embedding` is the mean SFace vector (float32,
    length-normalised) of its faces; `assignment` says why it sits with its actor (rule 6)."""

    __tablename__ = "face_tracks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    media_id: Mapped[str] = _media_fk()
    shot_id: Mapped[str | None] = mapped_column(
        ForeignKey("shots.id", ondelete="SET NULL"), nullable=True
    )
    index: Mapped[int]
    start_s: Mapped[float]
    end_s: Mapped[float]
    face_count: Mapped[int]
    embedding: Mapped[bytes] = mapped_column(LargeBinary)
    crop_path: Mapped[str] = mapped_column(String(255))  # relative to the project directory
    actor_id: Mapped[str | None] = mapped_column(
        ForeignKey("actors.id", ondelete="SET NULL"), nullable=True
    )
    state: Mapped[str] = mapped_column(String(16), default="auto")
    assignment: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    faces: Mapped[list["Face"]] = relationship(
        order_by="Face.frame", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_face_tracks_media", "media_id", "index"),
        Index("ix_face_tracks_actor", "actor_id"),
    )


class Face(Base):
    """One used face. The box is a fraction of the frame, so it fits proxy and original alike."""

    __tablename__ = "faces"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    track_id: Mapped[str] = mapped_column(ForeignKey("face_tracks.id", ondelete="CASCADE"))
    media_id: Mapped[str] = _media_fk()
    frame: Mapped[int]
    time_s: Mapped[float]
    x: Mapped[float]
    y: Mapped[float]
    w: Mapped[float]
    h: Mapped[float]
    score: Mapped[float]
    size_px: Mapped[float]
    sharpness: Mapped[float]
    turn: Mapped[float]

    __table_args__ = (
        Index("ix_faces_track", "track_id"),
        Index("ix_faces_media", "media_id", "frame"),
    )


class FacePin(Base):
    """A user correction, anchored to where a face was (clip, time, box) rather than to a track
    id, so it can be found again after the clip is processed with other settings. `track_id` is
    the track it currently belongs to (None until matched)."""

    __tablename__ = "face_pins"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    media_id: Mapped[str] = _media_fk()
    time_s: Mapped[float]
    x: Mapped[float]
    y: Mapped[float]
    w: Mapped[float]
    h: Mapped[float]
    state: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str | None] = mapped_column(
        ForeignKey("actors.id", ondelete="CASCADE"), nullable=True
    )
    track_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        Index("ix_face_pins_project", "project_id"),
        Index("ix_face_pins_track", "track_id"),
    )


class ActorRun(Base):
    """The last grouping of a project's tracks: a hash of its inputs (so an unchanged project is
    not grouped again) and in `details` the method, threshold, models and counts."""

    __tablename__ = "actor_runs"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    digest: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    clustered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class FeedbackEvent(Base):
    """Append-only log of what the user corrected (kind + payload), kept for later phases."""

    __tablename__ = "feedback_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (Index("ix_feedback_project", "project_id", "id"),)


class ActorPairAnswer(Base):
    """The user's answer to "are these two the same person?". Kept by track, not by actor, so it
    still means the same after the project is grouped again: tracks the user called different
    are never grouped together. `distance` is the average-linkage distance of the two when
    asked, so the answers can measure where the grouping limit should sit."""

    __tablename__ = "actor_pair_answers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    tracks_a: Mapped[list[str]] = mapped_column(JSON)
    tracks_b: Mapped[list[str]] = mapped_column(JSON)
    same: Mapped[bool] = mapped_column(Boolean)
    distance: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (Index("ix_actor_pair_answers_project", "project_id", "id"),)
