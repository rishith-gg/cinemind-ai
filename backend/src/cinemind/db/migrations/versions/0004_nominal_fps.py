"""nominal (base) frame rate of a media asset, next to the measured average

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("media_assets") as batch:
        batch.add_column(sa.Column("nominal_fps_num", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("nominal_fps_den", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("media_assets") as batch:
        batch.drop_column("nominal_fps_den")
        batch.drop_column("nominal_fps_num")
