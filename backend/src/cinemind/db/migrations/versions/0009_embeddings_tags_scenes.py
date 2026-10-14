"""embeddings, tags and tag reviews, scenes with user edits, vector index records

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
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
        "embedding_sets",
        sa.Column(
            "media_id",
            sa.String(32),
            sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("kind", sa.String(16), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "embeddings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _fk("media_id", "media_assets.id"),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("ref_id", sa.String(32), nullable=False),
        _fk("shot_id", "shots.id", nullable=True),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("vector", sa.LargeBinary(), nullable=False),
    )
    op.create_index("ix_embeddings_media", "embeddings", ["media_id", "kind"])
    op.create_index("ix_embeddings_kind_model", "embeddings", ["kind", "model"])
    op.create_index("ix_embeddings_shot", "embeddings", ["shot_id"])
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _fk("media_id", "media_assets.id"),
        _fk("shot_id", "shots.id"),
        sa.Column("group", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.UniqueConstraint("shot_id", "name", name="uq_tags_shot_name"),
    )
    op.create_index("ix_tags_media", "tags", ["media_id"])
    op.create_index("ix_tags_name", "tags", ["name", "status"])
    op.create_table(
        "tag_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _fk("project_id", "projects.id"),
        _fk("media_id", "media_assets.id"),
        sa.Column("shot_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("shot_id", "name", name="uq_tag_reviews_shot_name"),
    )
    op.create_index("ix_tag_reviews_project", "tag_reviews", ["project_id"])
    op.create_table(
        "scenes",
        sa.Column("id", sa.String(32), primary_key=True),
        _fk("project_id", "projects.id"),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("named", sa.Boolean(), nullable=False),
        sa.Column("shot_count", sa.Integer(), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_index("ix_scenes_project", "scenes", ["project_id", "index"])
    op.create_table(
        "scene_edits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _fk("project_id", "projects.id"),
        sa.Column("shot_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "shot_id", "kind", name="uq_scene_edits"),
    )
    op.create_index("ix_scene_edits_project", "scene_edits", ["project_id"])
    op.create_table(
        "scene_runs",
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("grouped_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "vector_indexes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _fk("project_id", "projects.id"),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("backend", sa.String(16), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("built_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "kind", "model", name="uq_vector_indexes"),
    )
    with op.batch_alter_table("shots") as batch:
        batch.add_column(sa.Column("scene_id", sa.String(32), nullable=True))
        batch.create_foreign_key(
            "fk_shots_scene", "scenes", ["scene_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("ix_shots_scene", ["scene_id"])


def downgrade() -> None:
    with op.batch_alter_table("shots") as batch:
        batch.drop_index("ix_shots_scene")
        batch.drop_constraint("fk_shots_scene", type_="foreignkey")
        batch.drop_column("scene_id")
    for table in (
        "vector_indexes",
        "scene_runs",
        "scene_edits",
        "scenes",
        "tag_reviews",
        "tags",
        "embeddings",
        "embedding_sets",
    ):
        op.drop_table(table)
