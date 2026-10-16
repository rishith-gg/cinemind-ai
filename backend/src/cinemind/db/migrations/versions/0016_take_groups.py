"""take groups, their members, the user's take corrections and the last grouping (SPEC P1-B)

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def _project() -> sa.Column[str]:
    return sa.Column(
        "project_id",
        sa.String(32),
        sa.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "take_groups",
        sa.Column("id", sa.String(32), primary_key=True),
        _project(),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("best_shot_id", sa.String(32), nullable=True),
        sa.Column("best_by", sa.String(16), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.CheckConstraint("kind IN ('speech', 'picture')", name="ck_take_groups_kind"),
    )
    op.create_index("ix_take_groups_project", "take_groups", ["project_id", "index"])
    op.create_table(
        "take_group_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "group_id",
            sa.String(32),
            sa.ForeignKey("take_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shot_id", sa.String(32), sa.ForeignKey("shots.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("signals", sa.JSON(), nullable=False),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index("ix_take_members_group", "take_group_members", ["group_id", "rank"])
    op.create_index("ix_take_members_shot", "take_group_members", ["shot_id"])
    op.create_table(
        "take_edits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _project(),
        sa.Column("shot_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("other_id", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "shot_id", "kind", "other_id", name="uq_take_edits"),
        sa.CheckConstraint("kind IN ('best', 'apart')", name="ck_take_edits_kind"),
    )
    op.create_index("ix_take_edits_project", "take_edits", ["project_id"])
    op.create_table(
        "take_runs",
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("grouped_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("take_runs")
    op.drop_table("take_edits")
    op.drop_table("take_group_members")
    op.drop_table("take_groups")
