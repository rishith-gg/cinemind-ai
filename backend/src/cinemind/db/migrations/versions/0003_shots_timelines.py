"""shots, keyframes, timelines, timeline items

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _fk(target: str, ondelete: str = "CASCADE") -> sa.ForeignKey:
    return sa.ForeignKey(target, ondelete=ondelete)


def upgrade() -> None:
    op.create_table(
        "shots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("media_id", sa.String(32), _fk("media_assets.id"), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame", sa.Integer(), nullable=False),
        sa.Column("start_s", sa.Float(), nullable=False),
        sa.Column("end_s", sa.Float(), nullable=False),
        sa.Column("fps_num", sa.Integer(), nullable=False),
        sa.Column("fps_den", sa.Integer(), nullable=False),
        sa.Column("detection", sa.JSON(), nullable=False),
    )
    op.create_index("ix_shots_media", "shots", ["media_id", "index"])
    op.create_table(
        "keyframes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("shot_id", sa.String(32), _fk("shots.id"), nullable=False),
        sa.Column("media_id", sa.String(32), _fk("media_assets.id"), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("frame", sa.Integer(), nullable=False),
        sa.Column("time_s", sa.Float(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("sharpness", sa.Float(), nullable=False),
    )
    op.create_index("ix_keyframes_shot", "keyframes", ["shot_id"])
    op.create_table(
        "timelines",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(32), _fk("projects.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("fps_num", sa.Integer(), nullable=False),
        sa.Column("fps_den", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_timelines_project", "timelines", ["project_id"])
    op.create_table(
        "timeline_items",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("timeline_id", sa.String(32), _fk("timelines.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("media_id", sa.String(32), _fk("media_assets.id"), nullable=False),
        sa.Column("shot_id", sa.String(32), _fk("shots.id", "SET NULL"), nullable=True),
        sa.Column("source_in_s", sa.Float(), nullable=False),
        sa.Column("source_out_s", sa.Float(), nullable=False),
    )
    op.create_index("ix_timeline_items_timeline", "timeline_items", ["timeline_id", "position"])


def downgrade() -> None:
    for table in ("timeline_items", "timelines", "keyframes", "shots"):
        op.drop_table(table)
