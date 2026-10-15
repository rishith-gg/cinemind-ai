"""ORM models for embeddings, tags, scenes and vector indexes (Phase 8). Registered with the
others through `db.models`."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cinemind.db.base import Base, UTCDateTime, utcnow

EMBED_STATUSES = ("done", "no_video", "no_speech", "no_transcript", "model_missing")
# shown = above its evaluated threshold; below = under it; disabled = the evaluation found the
# tag too often wrong; not_evaluated = no labelled data to set a threshold. Only `shown` (or a
# tag the user approved) is displayed as a tag.
TAG_STATUSES = ("shown", "below", "disabled", "not_evaluated")
SCENE_EDIT_KINDS = ("split", "join", "name")


def _media_fk() -> Mapped[str]:
    return mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"))


def _project_fk() -> Mapped[str]:
    return mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))


class EmbeddingSet(Base):
    """What one embedding stage produced for one clip (`kind` visual | text), and with what."""

    __tablename__ = "embedding_sets"

    media_id: Mapped[str] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(100), default="")
    revision: Mapped[str] = mapped_column(String(64), default="")
    count: Mapped[int] = mapped_column(default=0)
    # Hash of the stage result plus the rows it points at; unchanged = rows are left alone.
    digest: Mapped[str] = mapped_column(String(64), default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Embedding(Base):
    """One vector (float32, unit length except colour histograms, which sum to 1). The vector
    index files are built from these rows and can always be rebuilt from them.

    kind: keyframe (picture model) | color (HSV histogram) | segment (transcript text model).
    `ref_id` is the keyframe id or the transcript segment id."""

    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    media_id: Mapped[str] = _media_fk()
    kind: Mapped[str] = mapped_column(String(16))
    ref_id: Mapped[str] = mapped_column(String(32))
    shot_id: Mapped[str | None] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), nullable=True
    )
    model: Mapped[str] = mapped_column(String(100))
    dim: Mapped[int]
    vector: Mapped[bytes] = mapped_column(LargeBinary)

    __table_args__ = (
        Index("ix_embeddings_media", "media_id", "kind"),
        Index("ix_embeddings_kind_model", "kind", "model"),
        Index("ix_embeddings_shot", "shot_id"),
    )


class Tag(Base):
    """A tag suggestion for one shot, with the score, the threshold it was held against and the
    evaluation behind that threshold (rule 6). Rewritten whenever the clip is processed."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    media_id: Mapped[str] = _media_fk()
    shot_id: Mapped[str] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"))
    group: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(16))  # model | faces | transcript
    score: Mapped[float | None] = mapped_column(nullable=True)
    threshold: Mapped[float | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint("shot_id", "name", name="uq_tags_shot_name"),
        Index("ix_tags_media", "media_id"),
        Index("ix_tags_name", "name", "status"),
    )


class TagReview(Base):
    """The user's decision on a tag of a shot. Kept by shot id (stable while the shot's frames
    stay the same), so it outlives the tag rows, which are rewritten on every run."""

    __tablename__ = "tag_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = _project_fk()
    media_id: Mapped[str] = _media_fk()
    shot_id: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))  # approved | rejected
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("shot_id", "name", name="uq_tag_reviews_shot_name"),
        Index("ix_tag_reviews_project", "project_id"),
    )


class Scene(Base):
    """Neighbouring shots that look alike (or that the user put together). Rebuilt by every
    grouping; the user's edits live in `scene_edits`. `details` holds the boundary decisions."""

    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = _project_fk()
    index: Mapped[int]
    name: Mapped[str] = mapped_column(String(100))
    named: Mapped[bool] = mapped_column(default=False)
    shot_count: Mapped[int] = mapped_column(default=0)
    duration_s: Mapped[float] = mapped_column(default=0.0)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (Index("ix_scenes_project", "project_id", "index"),)


class SceneEdit(Base):
    """A user edit: `split` = a scene starts at this shot; `join` = this shot stays with the one
    before it; `name` = the scene holding this shot is called `value`."""

    __tablename__ = "scene_edits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = _project_fk()
    shot_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "shot_id", "kind", name="uq_scene_edits"),
        Index("ix_scene_edits_project", "project_id"),
    )


class SceneRun(Base):
    """The last scene grouping of a project: a hash of its inputs and the settings used."""

    __tablename__ = "scene_runs"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    digest: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    grouped_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class VectorIndexRow(Base):
    """A vector index file under the project's `index/` folder, built from `embeddings` rows.
    `digest` is a hash of the rows it holds; another digest means the file is out of date."""

    __tablename__ = "vector_indexes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = _project_fk()
    kind: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(100))
    backend: Mapped[str] = mapped_column(String(16))  # faiss | numpy
    dim: Mapped[int]
    count: Mapped[int]
    digest: Mapped[str] = mapped_column(String(64))
    # Count and id range of the rows (`vector_index.fingerprint`): checked by every search
    # without reading any vector; a different value means the index may be out of date.
    fingerprint: Mapped[str] = mapped_column(String(100), default="", server_default="")
    path: Mapped[str] = mapped_column(Text)  # relative to the project directory
    built_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("project_id", "kind", "model", name="uq_vector_indexes"),)


class SearchJudgment(Base):
    """Is this shot a good result for this query? The labels of `eval/search_eval.py`.
    `query` is stored normalised (`normal_query`); `shot_id` has no foreign key, so a judgment
    outlives a re-detection that keeps the shot's frames (like tag reviews). `judge` says who
    decided: "user" from the app, or the name given to the evaluation script's import."""

    __tablename__ = "search_judgments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = _project_fk()
    media_id: Mapped[str] = _media_fk()
    query: Mapped[str] = mapped_column(String(200))
    shot_id: Mapped[str] = mapped_column(String(32))
    relevant: Mapped[bool]
    judge: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "query", "shot_id", "judge", name="uq_search_judgment"),
        Index("ix_search_judgments_project", "project_id", "query"),
    )


def normal_query(text: str) -> str:
    """How a query is stored with its judgments: trimmed, case-folded, single spaces."""
    return " ".join(text.casefold().split())[:200]
