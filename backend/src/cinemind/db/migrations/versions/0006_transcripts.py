"""transcripts, segments, words and the FTS5 keyword index

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# External-content FTS5 table: the text lives in transcript_segments only, and the triggers keep
# the index in step with every insert, update and delete (including cascaded deletes).
_FTS = [
    """CREATE VIRTUAL TABLE transcript_fts USING fts5(
           text, content='transcript_segments', content_rowid='id',
           tokenize='unicode61 remove_diacritics 2')""",
    """CREATE TRIGGER transcript_segments_ai AFTER INSERT ON transcript_segments BEGIN
           INSERT INTO transcript_fts(rowid, text) VALUES (new.id, new.text);
       END""",
    """CREATE TRIGGER transcript_segments_ad AFTER DELETE ON transcript_segments BEGIN
           INSERT INTO transcript_fts(transcript_fts, rowid, text)
           VALUES ('delete', old.id, old.text);
       END""",
    """CREATE TRIGGER transcript_segments_au AFTER UPDATE ON transcript_segments BEGIN
           INSERT INTO transcript_fts(transcript_fts, rowid, text)
           VALUES ('delete', old.id, old.text);
           INSERT INTO transcript_fts(rowid, text) VALUES (new.id, new.text);
       END""",
]


def _media() -> sa.Column[str]:
    return sa.Column(
        "media_id",
        sa.String(32),
        sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "transcripts",
        sa.Column(
            "media_id",
            sa.String(32),
            sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("language_probability", sa.Float(), nullable=True),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("model_revision", sa.String(64), nullable=False),
        sa.Column("speech_s", sa.Float(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _media(),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("start_s", sa.Float(), nullable=False),
        sa.Column("end_s", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("avg_logprob", sa.Float(), nullable=False),
        sa.Column("no_speech_prob", sa.Float(), nullable=False),
        sa.Column("compression_ratio", sa.Float(), nullable=False),
    )
    op.create_index("ix_transcript_segments_media", "transcript_segments", ["media_id", "index"])
    op.create_table(
        "transcript_words",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "segment_id",
            sa.Integer(),
            sa.ForeignKey("transcript_segments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _media(),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("start_s", sa.Float(), nullable=False),
        sa.Column("end_s", sa.Float(), nullable=False),
        sa.Column("word", sa.String(200), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
    )
    op.create_index("ix_transcript_words_segment", "transcript_words", ["segment_id", "index"])
    for statement in _FTS:
        op.execute(statement)


def downgrade() -> None:
    for trigger in ("ai", "ad", "au"):
        op.execute(f"DROP TRIGGER transcript_segments_{trigger}")
    op.execute("DROP TABLE transcript_fts")
    for table in ("transcript_words", "transcript_segments", "transcripts"):
        op.drop_table(table)
