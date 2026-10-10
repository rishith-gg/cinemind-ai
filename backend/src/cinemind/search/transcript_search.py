"""Keyword search over transcript segments with SQLite FTS5 (BM25 ranking is SQLite's; ours is
the query building and finding the moment a match is spoken)."""

import logging
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from cinemind.core.errors import InvalidInputError
from cinemind.db.models import TranscriptWord

log = logging.getLogger(__name__)

MAX_TERMS = 16
_OPEN, _CLOSE = "\x02", "\x03"  # highlight markers that cannot occur in a transcript

_SQL = text(
    """
    SELECT s.id, s.media_id, m.filename, s.start_s, s.end_s, s.avg_logprob, s.compression_ratio,
           highlight(transcript_fts, 0, char(2), char(3)) AS marked,
           bm25(transcript_fts) AS rank
    FROM transcript_fts
    JOIN transcript_segments s ON s.id = transcript_fts.rowid
    JOIN media_assets m ON m.id = s.media_id
    WHERE transcript_fts MATCH :match AND m.project_id = :project
      AND (:media IS NULL OR s.media_id = :media)
    ORDER BY rank, m.filename, s.start_s
    LIMIT :limit
    """
)


@dataclass
class Hit:
    segment_id: int
    media_id: str
    filename: str
    start_s: float
    end_s: float
    jump_s: float
    parts: list[tuple[str, bool]]
    avg_logprob: float
    compression_ratio: float
    rank: float


def _pieces(value: str) -> list[str]:
    """Roughly what the index makes of a word: case and accents ignored, split at anything that
    is not a letter, digit or combining mark ("well-known" -> well, known; "café" -> cafe)."""
    pieces: list[str] = []
    current = ""
    for ch in unicodedata.normalize("NFKD", value).casefold():
        category = unicodedata.category(ch)
        if ch.isalnum() or category == "Mc":
            current += ch
        elif category != "Mn":  # accents and other non-spacing marks are dropped, not a break
            pieces += [current] if current else []
            current = ""
    return pieces + ([current] if current else [])


def query_terms(query: str) -> list[str]:
    """The words of a search box entry. Quotes, control characters and FTS5 operators typed by
    the user are data, never syntax."""
    cleaned = "".join(" " if ord(ch) < 32 else ch for ch in query).replace('"', "")
    terms = [t for t in cleaned.split() if _pieces(t)]
    if not terms:
        raise InvalidInputError("Type at least one word to search for.")
    if len(terms) > MAX_TERMS:
        raise InvalidInputError(f"Search for at most {MAX_TERMS} words at a time.")
    return terms


def match_expression(terms: list[str]) -> str:
    """FTS5 query: every term must occur (implicit AND); each is quoted, so it is tokenized as
    text, and matches the beginning of a word (`walk` finds `walking`)."""
    return " ".join('"' + term.replace('"', '""') + '"*' for term in terms)


def _parts(marked: str) -> list[tuple[str, bool]]:
    parts: list[tuple[str, bool]] = []
    for i, piece in enumerate(marked.split(_OPEN)):
        if i == 0:
            hit, rest = "", piece
        else:
            hit, _, rest = piece.partition(_CLOSE)
        parts += [(hit, True)] if hit else []
        parts += [(rest, False)] if rest else []
    return parts


def search(
    session: Session, project_id: str, query: str, media_id: str | None = None, limit: int = 50
) -> tuple[list[str], list[Hit]]:
    terms = query_terms(query)
    rows = session.execute(
        _SQL,
        {
            "match": match_expression(terms),
            "project": project_id,
            "media": media_id,
            "limit": limit,
        },
    ).all()
    words: dict[int, list[Any]] = {}
    ids = [row.id for row in rows]
    for word in session.scalars(
        select(TranscriptWord)
        .where(TranscriptWord.segment_id.in_(ids))
        .order_by(TranscriptWord.segment_id, TranscriptWord.index)
    ):
        words.setdefault(word.segment_id, []).append(word)
    first = _pieces(terms[0])[0]
    hits: list[Hit] = []
    for row in rows:
        spoken = next(
            (
                w.start_s
                for w in words.get(row.id, [])
                if any(piece.startswith(first) for piece in _pieces(w.word))
            ),
            row.start_s,
        )
        hits.append(
            Hit(
                segment_id=row.id,
                media_id=row.media_id,
                filename=row.filename,
                start_s=row.start_s,
                end_s=row.end_s,
                jump_s=spoken,
                parts=_parts(row.marked),
                avg_logprob=row.avg_logprob,
                compression_ratio=row.compression_ratio,
                rank=row.rank,
            )
        )
    return terms, hits
