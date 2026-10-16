"""screenplay, its lines and the takes found for each dialogue line (SPEC P1-A)

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "script_docs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("alignment", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "script_lines",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "doc_id",
            sa.String(32),
            sa.ForeignKey("script_docs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("character", sa.String(100), nullable=True),
        sa.Column("scene", sa.String(300), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("choice", sa.String(16), nullable=False, server_default="auto"),
        sa.Column(
            "picked_media_id",
            sa.String(32),
            sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("picked_start_s", sa.Float(), nullable=True),
        sa.Column("picked_end_s", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "choice IN ('auto', 'take', 'not_filmed')", name="ck_script_lines_choice"
        ),
    )
    op.create_index("ix_script_lines_doc", "script_lines", ["doc_id", "index"])
    op.create_table(
        "script_takes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "line_id",
            sa.String(32),
            sa.ForeignKey("script_lines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "media_id",
            sa.String(32),
            sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("start_s", sa.Float(), nullable=False),
        sa.Column("end_s", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("lexical", sa.Float(), nullable=False),
        sa.Column("semantic", sa.Float(), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("segment_ids", sa.JSON(), nullable=False),
    )
    op.create_index("ix_script_takes_line", "script_takes", ["line_id", "rank"])


def downgrade() -> None:
    op.drop_table("script_takes")
    op.drop_table("script_lines")
    op.drop_table("script_docs")
