"""quality metrics, audio metrics, QC flags, clip quality score

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _fk(target: str) -> sa.ForeignKey:
    return sa.ForeignKey(target, ondelete="CASCADE")


def _floats(*names: str) -> list[sa.Column[float]]:
    return [sa.Column(name, sa.Float(), nullable=False) for name in names]


def upgrade() -> None:
    with op.batch_alter_table("media_assets") as batch:
        batch.add_column(sa.Column("quality_score", sa.Float(), nullable=True))
    op.create_table(
        "quality_metrics",
        sa.Column("shot_id", sa.String(32), _fk("shots.id"), primary_key=True),
        sa.Column("media_id", sa.String(32), _fk("media_assets.id"), nullable=False),
        sa.Column("frames", sa.Integer(), nullable=False),
        *_floats("sharpness", "blur", "luma_mean", "luma_std", "spread", "clipped", "crushed"),
        sa.Column("sharpness_score", sa.Float(), nullable=True),
        *_floats("exposure_score", "contrast_score", "score"),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_index("ix_quality_media", "quality_metrics", ["media_id"])
    op.create_table(
        "audio_metrics",
        sa.Column("media_id", sa.String(32), _fk("media_assets.id"), primary_key=True),
        sa.Column("integrated_lufs", sa.Float(), nullable=True),
        sa.Column("loudness_range", sa.Float(), nullable=True),
        sa.Column("true_peak_db", sa.Float(), nullable=True),
        *_floats("sample_peak", "clipped_pct", "silence_s", "silence_pct", "score"),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_table(
        "qc_flags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("media_id", sa.String(32), _fk("media_assets.id"), nullable=False),
        sa.Column("shot_id", sa.String(32), _fk("shots.id"), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("start_s", sa.Float(), nullable=False),
        sa.Column("end_s", sa.Float(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_index("ix_qc_flags_media", "qc_flags", ["media_id"])


def downgrade() -> None:
    for table in ("qc_flags", "audio_metrics", "quality_metrics"):
        op.drop_table(table)
    with op.batch_alter_table("media_assets") as batch:
        batch.drop_column("quality_score")
