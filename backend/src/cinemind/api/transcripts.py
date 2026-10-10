"""Transcripts: per clip (segments with word timings), per project (overview) and keyword search."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute, selectinload

from cinemind.ai.transcriber import PULL_HINT
from cinemind.api.deps import SessionDep
from cinemind.api.media import ERRORS, get_asset, get_project
from cinemind.api.schemas import (
    TextPart,
    TranscriptHit,
    TranscriptOut,
    TranscriptSearchOut,
    TranscriptSegmentOut,
    TranscriptStatus,
    TranscriptSummary,
    TranscriptWordOut,
)
from cinemind.core import transcribe_config as limits
from cinemind.db.models import MediaAsset, Transcript, TranscriptSegment, TranscriptWord
from cinemind.rough_cut.assembly import natural_key
from cinemind.search import transcript_search

router = APIRouter(tags=["transcripts"])

_THRESHOLDS = {
    "uncertain_logprob_below": limits.UNCERTAIN_LOGPROB_BELOW,
    "uncertain_compression_above": limits.UNCERTAIN_COMPRESSION_ABOVE,
    "uncertain_language_below": limits.UNCERTAIN_LANGUAGE_BELOW,
}


def _message(row: Transcript | None) -> str | None:
    """What to tell the user when a clip has no transcript text."""
    if row is None:
        return "Not transcribed yet. Processing may still be running; otherwise press Reprocess."
    reason = str(row.details.get("reason") or "")
    return {
        "done": None,
        "no_speech": "No speech was found in this clip.",
        "no_audio": "This clip has no audio track.",
        "model_missing": f"{reason} {PULL_HINT}".strip(),
        "audio_unreadable": reason or "The audio track could not be decoded.",
    }.get(row.status, reason or None)


def _status(row: Transcript | None) -> TranscriptStatus:
    return row.status if row is not None else "pending"  # pyright: ignore[reportReturnType]


@router.get(
    "/api/media/{media_id}/transcript",
    response_model=TranscriptOut,
    responses=ERRORS,
    operation_id="getMediaTranscript",
)
def get_media_transcript(media_id: str, session: SessionDep) -> TranscriptOut:
    """The clip's transcript with word timings, and what produced it (model, revision, engine,
    settings). Segments the model itself did not accept are marked `uncertain`."""
    get_asset(session, media_id)
    row = session.get(Transcript, media_id)
    segments = session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.media_id == media_id)
        .options(selectinload(TranscriptSegment.words))
        .order_by(TranscriptSegment.index)
    )
    probability = row.language_probability if row else None
    return TranscriptOut(
        media_id=media_id,
        status=_status(row),
        message=_message(row),
        language=row.language if row else None,
        language_probability=probability,
        language_uncertain=bool(
            row
            and row.details.get("language_detected", True)
            and probability is not None
            and probability < limits.UNCERTAIN_LANGUAGE_BELOW
        ),
        model=row.model if row else "",
        model_revision=row.model_revision if row else "",
        speech_s=row.speech_s if row else 0.0,
        details=row.details if row else {},
        thresholds=_THRESHOLDS,
        segments=[
            TranscriptSegmentOut(
                id=s.id,
                index=s.index,
                start_s=s.start_s,
                end_s=s.end_s,
                text=s.text,
                confidence=s.confidence,
                avg_logprob=s.avg_logprob,
                no_speech_prob=s.no_speech_prob,
                compression_ratio=s.compression_ratio,
                uncertain=limits.is_uncertain(s.avg_logprob, s.compression_ratio),
                words=[TranscriptWordOut.model_validate(w) for w in s.words],
            )
            for s in segments
        ],
    )


@router.get(
    "/api/projects/{project_id}/transcripts",
    response_model=list[TranscriptSummary],
    responses=ERRORS,
    operation_id="listProjectTranscripts",
)
def list_project_transcripts(project_id: str, session: SessionDep) -> list[TranscriptSummary]:
    """One row per clip: transcript state, language, and how much text there is."""
    get_project(session, project_id)
    assets = session.execute(
        select(MediaAsset, Transcript)
        .outerjoin(Transcript, Transcript.media_id == MediaAsset.id)
        .where(MediaAsset.project_id == project_id)
    ).all()

    def counts(column: InstrumentedAttribute[str]) -> dict[str, int]:
        query = (
            select(column, func.count())
            .join(MediaAsset, MediaAsset.id == column)
            .where(MediaAsset.project_id == project_id)
            .group_by(column)
        )
        return {row[0]: row[1] for row in session.execute(query)}

    segments = counts(TranscriptSegment.media_id)
    words = counts(TranscriptWord.media_id)
    rows = sorted(assets, key=lambda pair: (natural_key(pair[0].filename), pair[0].id))
    return [
        TranscriptSummary(
            media_id=asset.id,
            filename=asset.filename,
            duration_s=asset.duration_s,
            status=_status(row),
            message=_message(row),
            language=row.language if row else None,
            speech_s=row.speech_s if row else 0.0,
            segments=segments.get(asset.id, 0),
            words=words.get(asset.id, 0),
        )
        for asset, row in rows
    ]


@router.get(
    "/api/projects/{project_id}/transcripts/search",
    response_model=TranscriptSearchOut,
    responses=ERRORS,
    operation_id="searchTranscripts",
)
def search_transcripts(
    project_id: str,
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    media_id: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> TranscriptSearchOut:
    """Keyword search in the project's transcripts (all words must occur; each matches the start
    of a word). Hits are ordered by BM25 and carry the time the first matching word is spoken."""
    get_project(session, project_id)
    terms, hits = transcript_search.search(session, project_id, q, media_id, limit)
    return TranscriptSearchOut(
        query=q,
        terms=terms,
        hits=[
            TranscriptHit(
                segment_id=h.segment_id,
                media_id=h.media_id,
                filename=h.filename,
                start_s=h.start_s,
                end_s=h.end_s,
                jump_s=h.jump_s,
                parts=[TextPart(text=text, match=match) for text, match in h.parts],
                uncertain=limits.is_uncertain(h.avg_logprob, h.compression_ratio),
                rank=h.rank,
            )
            for h in hits
        ],
    )
