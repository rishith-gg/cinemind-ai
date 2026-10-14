"""the user's answers to "same person?" questions about two actors

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "actor_pair_answers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tracks_a", sa.JSON(), nullable=False),
        sa.Column("tracks_b", sa.JSON(), nullable=False),
        sa.Column("same", sa.Boolean(), nullable=False),
        sa.Column("distance", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_actor_pair_answers_project", "actor_pair_answers", ["project_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_actor_pair_answers_project", table_name="actor_pair_answers")
    op.drop_table("actor_pair_answers")
