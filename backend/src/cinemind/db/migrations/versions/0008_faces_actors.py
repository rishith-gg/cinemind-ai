"""faces, face tracks, actors, correction pins, grouping runs and the feedback log

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _fk(
    name: str, target: str, ondelete: str = "CASCADE", nullable: bool = False
) -> sa.Column[str]:
    return sa.Column(
        name, sa.String(32), sa.ForeignKey(target, ondelete=ondelete), nullable=nullable
    )


def upgrade() -> None:
    op.create_table(
        "face_scans",
        sa.Column(
            "media_id",
            sa.String(32),
            sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("frames_sampled", sa.Integer(), nullable=False),
        sa.Column("faces_detected", sa.Integer(), nullable=False),
        sa.Column("faces_used", sa.Integer(), nullable=False),
        sa.Column("max_in_frame", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_table(
        "actors",
        sa.Column("id", sa.String(32), primary_key=True),
        _fk("project_id", "projects.id"),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("named", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_actors_project", "actors", ["project_id", "number"])
    op.create_table(
        "face_tracks",
        sa.Column("id", sa.String(32), primary_key=True),
        _fk("media_id", "media_assets.id"),
        _fk("shot_id", "shots.id", "SET NULL", nullable=True),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("start_s", sa.Float(), nullable=False),
        sa.Column("end_s", sa.Float(), nullable=False),
        sa.Column("face_count", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("crop_path", sa.String(255), nullable=False),
        _fk("actor_id", "actors.id", "SET NULL", nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("assignment", sa.JSON(), nullable=False),
    )
    op.create_index("ix_face_tracks_media", "face_tracks", ["media_id", "index"])
    op.create_index("ix_face_tracks_actor", "face_tracks", ["actor_id"])
    op.create_table(
        "faces",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _fk("track_id", "face_tracks.id"),
        _fk("media_id", "media_assets.id"),
        sa.Column("frame", sa.Integer(), nullable=False),
        sa.Column("time_s", sa.Float(), nullable=False),
        *(sa.Column(name, sa.Float(), nullable=False) for name in ("x", "y", "w", "h")),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("size_px", sa.Float(), nullable=False),
        sa.Column("sharpness", sa.Float(), nullable=False),
        sa.Column("turn", sa.Float(), nullable=False),
    )
    op.create_index("ix_faces_track", "faces", ["track_id"])
    op.create_index("ix_faces_media", "faces", ["media_id", "frame"])
    op.create_table(
        "face_pins",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _fk("project_id", "projects.id"),
        _fk("media_id", "media_assets.id"),
        sa.Column("time_s", sa.Float(), nullable=False),
        *(sa.Column(name, sa.Float(), nullable=False) for name in ("x", "y", "w", "h")),
        sa.Column("state", sa.String(16), nullable=False),
        _fk("actor_id", "actors.id", nullable=True),
        sa.Column("track_id", sa.String(32), nullable=True),
    )
    op.create_index("ix_face_pins_project", "face_pins", ["project_id"])
    op.create_index("ix_face_pins_track", "face_pins", ["track_id"])
    op.create_table(
        "actor_runs",
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("clustered_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "feedback_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _fk("project_id", "projects.id"),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_feedback_project", "feedback_events", ["project_id", "id"])


def downgrade() -> None:
    for table in ("feedback_events", "actor_runs", "face_pins", "faces", "face_tracks"):
        op.drop_table(table)
    op.drop_table("actors")
    op.drop_table("face_scans")
