"""Script-to-footage alignment (SPEC P1-A): the uploaded screenplay, its lines, and the takes
found for each dialogue line. Imported by `db/models.py` to register the tables."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cinemind.db.base import Base, UTCDateTime, new_id, utcnow


class ScriptDoc(Base):
    """One screenplay per project (uploading another replaces it)."""

    __tablename__ = "script_docs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True
    )
    name: Mapped[str] = mapped_column(String(200))
    format: Mapped[str] = mapped_column(String(16))  # fountain | plain
    text: Mapped[str] = mapped_column(Text)
    # Rule 6: how the last alignment ran (model, weights, threshold, counts, when).
    alignment: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    lines: Mapped[list["ScriptLine"]] = relationship(
        order_by="ScriptLine.index", cascade="all, delete-orphan", passive_deletes=True
    )


class ScriptLine(Base):
    """A scene heading, an action paragraph or a dialogue line, in script order. Only dialogue
    is aligned. `choice`: auto (the best take), take (the user's `picked_*` take), not_filmed."""

    __tablename__ = "script_lines"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    doc_id: Mapped[str] = mapped_column(ForeignKey("script_docs.id", ondelete="CASCADE"))
    index: Mapped[int]
    kind: Mapped[str] = mapped_column(String(16))  # scene | action | dialogue
    character: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scene: Mapped[str | None] = mapped_column(String(300), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    choice: Mapped[str] = mapped_column(String(16), default="auto", server_default="auto")
    # The user's take, by place in the footage, so it survives aligning again.
    picked_media_id: Mapped[str | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )
    picked_start_s: Mapped[float | None] = mapped_column(nullable=True)
    picked_end_s: Mapped[float | None] = mapped_column(nullable=True)

    takes: Mapped[list["ScriptTake"]] = relationship(
        order_by="ScriptTake.rank", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_script_lines_doc", "doc_id", "index"),
        CheckConstraint("choice IN ('auto', 'take', 'not_filmed')", name="ck_script_lines_choice"),
    )


class ScriptTake(Base):
    """Where a dialogue line was found: a stretch of transcript in one clip, with its scores."""

    __tablename__ = "script_takes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    line_id: Mapped[str] = mapped_column(ForeignKey("script_lines.id", ondelete="CASCADE"))
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"))
    rank: Mapped[int]  # 1 = best match
    start_s: Mapped[float]
    end_s: Mapped[float]
    text: Mapped[str] = mapped_column(Text)  # the words heard there
    lexical: Mapped[float]
    semantic: Mapped[float | None] = mapped_column(nullable=True)
    score: Mapped[float]
    segment_ids: Mapped[list[int]] = mapped_column(JSON, default=list)

    __table_args__ = (Index("ix_script_takes_line", "line_id", "rank"),)
