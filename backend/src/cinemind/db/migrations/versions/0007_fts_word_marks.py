"""keyword index: keep combining marks inside words (Indic vowel signs)

Revision ID: 0007
Revises: 0006

The default `unicode61` tokenizer treats combining marks as separators, which cuts Hindi, Kannada
and similar words at every vowel sign. Adding the mark categories keeps such words whole. The
index is rebuilt from `transcript_segments`; the triggers from 0006 stay as they are.
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_CREATE = """CREATE VIRTUAL TABLE transcript_fts USING fts5(
    text, content='transcript_segments', content_rowid='id',
    tokenize="unicode61 remove_diacritics 2{extra}")"""
_REBUILD = "INSERT INTO transcript_fts(transcript_fts) VALUES ('rebuild')"


def _recreate(extra: str) -> None:
    op.execute("DROP TABLE transcript_fts")
    op.execute(_CREATE.format(extra=extra))
    op.execute(_REBUILD)


def upgrade() -> None:
    _recreate(" categories 'L* N* Co Mn Mc'")


def downgrade() -> None:
    _recreate("")
