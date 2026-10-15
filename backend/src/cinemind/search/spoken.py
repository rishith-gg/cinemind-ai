"""Transcript lines a later step may rely on: those not marked uncertain (D-084), with their
timed words. Used by the rough cut's speech-aware trim and by the SRT export."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from cinemind.core.transcribe_config import is_uncertain
from cinemind.db.models import TranscriptSegment


@dataclass(frozen=True)
class Word:
    start_s: float
    end_s: float
    text: str


@dataclass(frozen=True)
class SpokenLine:
    start_s: float
    end_s: float
    text: str
    words: tuple[Word, ...] = ()


def spoken_lines(session: Session, media_ids: set[str]) -> dict[str, list[SpokenLine]]:
    """Transcript lines not marked uncertain, with their timed words, per clip."""
    query = (
        select(TranscriptSegment)
        .options(selectinload(TranscriptSegment.words))
        .where(TranscriptSegment.media_id.in_(media_ids))
        .order_by(TranscriptSegment.media_id, TranscriptSegment.start_s)
    )
    found: dict[str, list[SpokenLine]] = {}
    for seg in session.scalars(query):
        if is_uncertain(seg.avg_logprob, seg.compression_ratio):
            continue
        words = tuple(Word(w.start_s, w.end_s, w.word) for w in seg.words)
        found.setdefault(seg.media_id, []).append(
            SpokenLine(seg.start_s, seg.end_s, seg.text, words)
        )
    return found
