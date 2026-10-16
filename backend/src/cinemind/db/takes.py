"""Take groups (SPEC P1-B): shots that repeat the same material, the best take of each, and the
user's corrections. Imported by `db/models.py` to register the tables."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cinemind.db.base import Base, UTCDateTime, utcnow

TAKE_EDIT_KINDS = ("best", "apart")


class TakeGroup(Base):
    """Shots found to be takes of the same material. Rebuilt by every grouping; the user's
    corrections live in `take_edits`. `kind`: speech (grouped by words) or picture."""

    __tablename__ = "take_groups"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    index: Mapped[int]
    kind: Mapped[str] = mapped_column(String(16))
    best_shot_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    best_by: Mapped[str] = mapped_column(String(16))  # auto | you | none (all rejected)
    # Rule 6: the pairs that linked the members, with their signals and scores.
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    members: Mapped[list["TakeMember"]] = relationship(
        order_by="TakeMember.rank", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        Index("ix_take_groups_project", "project_id", "index"),
        CheckConstraint("kind IN ('speech', 'picture')", name="ck_take_groups_kind"),
    )


class TakeMember(Base):
    """One take in a group: its best-take signals (each 0..1 or missing), their weighted mean,
    and the plain-language notes behind them (flubs, cut-off speech, rejected)."""

    __tablename__ = "take_group_members"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("take_groups.id", ondelete="CASCADE"))
    shot_id: Mapped[str] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"))
    rank: Mapped[int]  # 1 = best
    score: Mapped[float | None] = mapped_column(nullable=True)
    signals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    text: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (
        Index("ix_take_members_group", "group_id", "rank"),
        Index("ix_take_members_shot", "shot_id"),
    )


class TakeEdit(Base):
    """A user correction, by shot id (stable while the shot's frames do not change, D-039):
    `best` = this shot is the best take of whatever group it is in; `apart` = this shot and
    `other_id` are not takes of the same material."""

    __tablename__ = "take_edits"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    shot_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    other_id: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "shot_id", "kind", "other_id", name="uq_take_edits"),
        Index("ix_take_edits_project", "project_id"),
        CheckConstraint("kind IN ('best', 'apart')", name="ck_take_edits_kind"),
    )


class TakeRun(Base):
    """The last take grouping of a project: a hash of its result and the settings used."""

    __tablename__ = "take_runs"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    digest: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    grouped_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
