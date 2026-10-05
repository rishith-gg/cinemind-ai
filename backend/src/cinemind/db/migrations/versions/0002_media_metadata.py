"""media asset metadata and artifacts

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_COLUMNS: list[sa.Column[object]] = [
    sa.Column("import_mode", sa.String(16), nullable=False, server_default="reference"),
    sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("probed", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("container", sa.String(100), nullable=True),
    sa.Column("duration_s", sa.Float(), nullable=True),
    sa.Column("width", sa.Integer(), nullable=True),
    sa.Column("height", sa.Integer(), nullable=True),
    sa.Column("fps_num", sa.Integer(), nullable=True),
    sa.Column("fps_den", sa.Integer(), nullable=True),
    sa.Column("is_vfr", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("video_codec", sa.String(50), nullable=True),
    sa.Column("audio_codec", sa.String(50), nullable=True),
    sa.Column("bit_rate", sa.Integer(), nullable=True),
    sa.Column("audio_channels", sa.Integer(), nullable=True),
    sa.Column("audio_sample_rate", sa.Integer(), nullable=True),
    sa.Column("start_timecode", sa.String(32), nullable=True),
    sa.Column("color", sa.JSON(), nullable=False, server_default="{}"),
    sa.Column("proxy_path", sa.Text(), nullable=True),
    sa.Column("poster_path", sa.Text(), nullable=True),
    sa.Column("strip_path", sa.Text(), nullable=True),
    sa.Column("waveform_path", sa.Text(), nullable=True),
    sa.Column("artifacts", sa.JSON(), nullable=False, server_default="{}"),
]


def upgrade() -> None:
    with op.batch_alter_table("media_assets") as batch:
        for column in _COLUMNS:
            batch.add_column(column)
        batch.create_unique_constraint("uq_media_project_hash", ["project_id", "content_hash"])


def downgrade() -> None:
    with op.batch_alter_table("media_assets") as batch:
        batch.drop_constraint("uq_media_project_hash", type_="unique")
        for column in reversed(_COLUMNS):
            batch.drop_column(column.name)
