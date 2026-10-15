"""project settings (spoken languages) and a per-clip speech language chosen by the user

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("media_assets", sa.Column("speech_language", sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("media_assets") as batch:
        batch.drop_column("speech_language")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("settings")
