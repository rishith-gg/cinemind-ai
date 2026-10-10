"""Ingest stage `transcribe` (SPEC section 5, stage 8): speech to text with word timings.

The stage never downloads anything. Without the model on disk it records `model_missing`, the
clip's other results stay usable, and the next run tries again. Its cache key hangs on the
source file only (`upstream=("validate",)`), so changing shot or quality settings does not send
the audio through the model again.
"""

import hashlib
import json
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from cinemind.ai import transcriber
from cinemind.core.config import Settings
from cinemind.core.errors import ModelMissingError, SourceMissingError, UnreadableMediaError
from cinemind.db.models import Transcript, TranscriptSegment, TranscriptWord
from cinemind.jobs.registry import Stage, StageContext
from cinemind.pipeline.stage_utils import checked_source, media_id, source_info

PIPELINE_VERSION = "1"


def job_params(settings: Settings) -> dict[str, Any]:
    """What a transcript depends on (part of the stage cache key): the model and its pinned
    revision plus the `[transcribe]` settings."""
    choice = transcriber.choose_model(settings)
    return {
        "model": choice.name,
        "revision": choice.revision,
        **settings.transcribe.model_dump(exclude={"model"}),
    }


def run_transcribe(ctx: StageContext) -> dict[str, Any]:
    params: dict[str, Any] = ctx.params.get("transcribe") or job_params(ctx.settings)
    choice = transcriber.choose_model(ctx.settings, params["model"])
    base: dict[str, Any] = {"model": choice.name, "revision": choice.revision, "segments": []}
    info = source_info(ctx)
    if not info.has_audio:
        return {**base, "status": "no_audio"}
    if not choice.ready:
        return {
            **base,
            "status": "model_missing",
            "reason": f"The speech model '{choice.name}' ({choice.size_mb} MB) is not downloaded.",
        }
    source = checked_source(ctx)
    if not source.is_file():
        raise SourceMissingError(
            f"The original file '{source.name}' is missing or was moved. Relink it to continue."
        )
    cfg = ctx.settings.transcribe.model_copy(
        update={k: v for k, v in params.items() if k not in ("model", "revision")}
    )
    try:
        audio = transcriber.decode_audio(source, ctx.check_cancelled)
    except UnreadableMediaError as exc:
        # The picture analysis succeeded; a broken audio track must not fail the whole clip.
        return {**base, "status": "audio_unreadable", "reason": exc.message}
    ctx.progress(0.02)
    try:
        found = transcriber.transcribe(choice, audio, cfg, ctx.progress, ctx.check_cancelled)
    except ModelMissingError as exc:  # removed between the check above and loading
        return {**base, "status": "model_missing", "reason": exc.message}
    return {
        **base,
        **found,
        "status": "done" if found["segments"] else "no_speech",
        "engine": transcriber.engine_version(),
        "settings": cfg.model_dump(exclude={"model"}),
    }


def verify_transcribe(_ctx: StageContext, cached: dict[str, Any]) -> bool:
    """A missing model or an unreadable track (which can be a disk hiccup) is not a result worth
    keeping: try again on the next run. Both fail fast."""
    return cached.get("status") not in ("model_missing", "audio_unreadable")


def _confidence(words: list[list[Any]]) -> float | None:
    return round(sum(float(w[3]) for w in words) / len(words), 4) if words else None


def persist_transcribe(session: Session, ctx: StageContext, result: dict[str, Any]) -> None:
    media = media_id(ctx)
    digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    row = session.get(Transcript, media)
    if row is not None and row.digest == digest:
        return  # same result as stored: keep the rows and their ids
    session.execute(delete(TranscriptSegment).where(TranscriptSegment.media_id == media))
    if row is None:
        row = Transcript(media_id=media)
        session.add(row)
    row.status = result["status"]
    row.language = result.get("language")
    row.language_probability = result.get("language_probability")
    row.model, row.model_revision = result["model"], result["revision"]
    row.speech_s = float(result.get("speech_s", 0.0))
    row.digest = digest
    keys = ("engine", "device", "compute_type", "settings", "language_detected", "reason")
    row.details = {key: result[key] for key in keys if key in result}
    for index, seg in enumerate(result["segments"]):
        words: list[list[Any]] = seg["words"]
        session.add(
            TranscriptSegment(
                media_id=media,
                index=index,
                start_s=seg["start"],
                end_s=seg["end"],
                text=seg["text"],
                confidence=_confidence(words),
                avg_logprob=seg["avg_logprob"],
                no_speech_prob=seg["no_speech_prob"],
                compression_ratio=seg["compression_ratio"],
                words=[
                    TranscriptWord(
                        media_id=media, index=i, start_s=a, end_s=b, word=text, probability=p
                    )
                    for i, (a, b, text, p) in enumerate(words)
                ],
            )
        )


TRANSCRIBE_STAGES = [
    Stage(
        "transcribe",
        run_transcribe,
        model_name="faster-whisper",
        model_version=f"{transcriber.engine_version()}+{PIPELINE_VERSION}",
        params={"sample_rate": transcriber.SAMPLE_RATE, "vad": "silero (faster-whisper)"},
        param_keys=("transcribe",),
        upstream=("validate",),
        verify=verify_transcribe,
        persist=persist_transcribe,
    ),
]
