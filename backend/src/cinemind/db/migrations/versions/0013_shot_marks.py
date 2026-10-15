"""the user's selects, rejects and stars on shots

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shot_marks",
        sa.Column("shot_id", sa.String(32), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "media_id",
            sa.String(32),
            sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mark", sa.String(16), nullable=True),
        sa.Column("stars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("mark IN ('select', 'reject')", name="ck_shot_marks_mark"),
        sa.CheckConstraint("stars BETWEEN 0 AND 5", name="ck_shot_marks_stars"),
    )
    op.create_index("ix_shot_marks_project", "shot_marks", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_shot_marks_project", table_name="shot_marks")
    op.drop_table("shot_marks")
