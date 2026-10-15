"""why each rough cut clip was chosen and trimmed as it is

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("timeline_items", sa.Column("reason", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("timeline_items") as batch:
        batch.drop_column("reason")
