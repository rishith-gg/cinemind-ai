"""relevance judgments for search results (the labels of the search evaluation), and a cheap
fingerprint of the rows each vector index was built from

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_judgments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
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
        sa.Column("query", sa.String(200), nullable=False),
        sa.Column("shot_id", sa.String(32), nullable=False),
        sa.Column("relevant", sa.Boolean(), nullable=False),
        sa.Column("judge", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "query", "shot_id", "judge", name="uq_search_judgment"),
    )
    op.create_index("ix_search_judgments_project", "search_judgments", ["project_id", "query"])
    op.add_column(
        "vector_indexes",
        sa.Column("fingerprint", sa.String(100), nullable=False, server_default=""),
    )


def downgrade() -> None:
    with op.batch_alter_table("vector_indexes") as batch:
        batch.drop_column("fingerprint")
    op.drop_index("ix_search_judgments_project", table_name="search_judgments")
    op.drop_table("search_judgments")
