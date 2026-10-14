"""Ingest stage `tags` (SPEC section 5, stage 12): tag suggestions for every shot.

Scores come from the picture vectors of `embed_visual` (see `ai/tagger.py` for how). Like the
quality stages (D-045) the stage caches raw scores only; whether a tag is shown is decided when
it is stored, from the evaluated thresholds in `ai/tag_thresholds.json`, so new thresholds take
effect with the next "Process all" without any model run. Two more tags are counted from earlier
results: clear faces (faces stage) and speech (transcript).
"""

from typing import Any

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from cinemind.ai import embedder, tagger
from cinemind.core.config import Settings
from cinemind.core.embed_config import EmbedModel
from cinemind.core.transcribe_config import is_uncertain
from cinemind.db.analysis import Tag
from cinemind.db.models import Shot, TranscriptSegment
from cinemind.db.people import Face, FaceTrack
from cinemind.jobs.registry import StageContext
from cinemind.pipeline.stage_utils import media_id, project_dir

VECTORS = "vectors.npy"  # written by embed_visual
# A shot gets the "speech" tag when transcript segments not marked uncertain cover this long.
SPEECH_MIN_S = 1.0
SPEECH_RULE = f"transcript segments not marked uncertain cover at least {SPEECH_MIN_S} s"
FACES_RULE = "most usable faces in one sampled frame; faces the checks left out are not counted"


_VOCABULARY: dict[tuple[str, str, str], tuple[Any, Any, float]] = {}


def clear_vocabulary() -> None:
    _VOCABULARY.clear()


def vocabulary(spec: EmbedModel, settings: Settings) -> tuple[Any, Any, float]:
    """Text vectors of the vocabulary and the model's temperature (once per process)."""
    key = (spec.key, str(settings.models_path), settings.embed.device)
    if key not in _VOCABULARY:
        texts, size = tagger.prompts(), settings.embed.batch_size * 8
        prompt_vectors = np.concatenate(
            [
                embedder.embed_prompts(spec, settings, texts[i : i + size])
                for i in range(0, len(texts), size)
            ]
        )
        tag_v, cat_v = tagger.class_vectors(prompt_vectors)
        _VOCABULARY.clear()  # one model at a time
        _VOCABULARY[key] = (tag_v, cat_v, embedder.logit_scale(spec, settings))
    return _VOCABULARY[key]


def run_tags(ctx: StageContext) -> dict[str, Any]:
    visual = ctx.previous["embed_visual"]
    base: dict[str, Any] = {
        "model": visual["model"],
        "revision": visual["revision"],
        "vocabulary": tagger.VOCAB_VERSION,
        "keyframes": [],
    }
    if visual["status"] != "done":
        return {**base, "status": visual["status"]}
    spec = embedder.choose_visual(ctx.settings, visual["model"])
    tag_v, cat_v, scale = vocabulary(spec, ctx.settings)
    vectors = np.load(project_dir(ctx) / visual["dir"] / VECTORS)
    scores, cat_probs = tagger.score(vectors, tag_v, cat_v, scale)
    keyframes: list[list[Any]] = []
    for i, (shot, slot, _frame) in enumerate(visual["keyframes"]):
        values = {name: round(float(s[i]), 5) for name, s in scores.items()}
        keyframes.append([shot, slot, values, tagger.top_places(cat_probs[i])])
    return {**base, "status": "done", "keyframes": keyframes, "logit_scale": round(scale, 3)}


def verify_tags(_ctx: StageContext, cached: dict[str, Any]) -> bool:
    return cached.get("status") != "model_missing"


def persist_tags(session: Session, ctx: StageContext, result: dict[str, Any]) -> None:
    """Model tags from the result plus tags counted from the faces and transcript tables.
    Rewritten on every run, so new thresholds take effect with the next "Process all"."""
    media = media_id(ctx)
    replace = delete(Tag).where(Tag.media_id == media)
    if result["status"] == "model_missing":
        # The picture vectors of an earlier run are kept (embed_visual), so are their tags.
        replace = replace.where(Tag.source != "model")
    session.execute(replace)
    session.flush()
    shots = list(session.scalars(select(Shot).where(Shot.media_id == media).order_by(Shot.index)))
    if result["status"] == "done":
        _model_tags(session, media, shots, result, ctx.settings)
    _face_tags(session, media, shots)
    _speech_tags(session, media, shots)


def _model_tags(
    session: Session, media: str, shots: list[Shot], result: dict[str, Any], settings: Settings
) -> None:
    spec = embedder.choose_visual(settings, result["model"])
    calibration = tagger.calibration_for(spec)
    per_shot: dict[int, list[list[Any]]] = {}
    for shot, slot, values, places in result["keyframes"]:
        per_shot.setdefault(int(shot), []).append([slot, values, places])
    about = {"model": spec.key, "revision": spec.revision[:12], "vocabulary": tagger.VOCAB_VERSION}
    if calibration is not None:
        about |= {
            "calibrated": calibration.get("date"),
            "calibration_source": calibration.get("source"),
        }
    evaluated: dict[str, Any] = (calibration or {}).get("tags") or {}
    for shot in shots:
        frames = per_shot.get(shot.index)
        if not frames:
            continue
        for tag in tagger.MODEL_TAGS:
            values = [float(f[1][tag.name]) for f in frames]
            value = float(np.mean(values))
            status, threshold = tagger.decide(tag.name, values, calibration)
            entry: dict[str, Any] = evaluated.get(tag.name) or {}
            details: dict[str, Any] = {
                **about,
                "keyframe_scores": [round(v, 4) for v in values],
                "rule": tagger.SHOT_RULE,
                "evaluation": {
                    k: entry.get(k)
                    for k in ("dataset", "precision", "precision_ci95", "recall", "reason")
                    if k in entry
                },
            }
            if tag.group == "place":
                details["top_places"] = [f[2] for f in frames]  # per keyframe
            session.add(
                Tag(
                    media_id=media,
                    shot_id=shot.id,
                    group=tag.group,
                    name=tag.name,
                    label=tag.label,
                    source="model",
                    score=round(value, 4),
                    threshold=threshold,
                    status=status,
                    details=details,
                )
            )


def _face_tags(session: Session, media: str, shots: list[Shot]) -> None:
    """Most clear faces seen in one sampled frame of the shot (from the faces stage)."""
    per_frame = (
        select(FaceTrack.shot_id, Face.frame, func.count().label("n"))
        .join(FaceTrack, FaceTrack.id == Face.track_id)
        .where(Face.media_id == media)
        .group_by(FaceTrack.shot_id, Face.frame)
        .subquery()
    )
    most = dict(
        session.execute(
            select(per_frame.c.shot_id, func.max(per_frame.c.n)).group_by(per_frame.c.shot_id)
        ).all()
    )
    for shot in shots:
        count = int(most.get(shot.id) or 0)
        if count:
            label = "1 clear face" if count == 1 else f"{count} clear faces"
            session.add(
                Tag(
                    media_id=media,
                    shot_id=shot.id,
                    group="faces",
                    name="faces",
                    label=label,
                    source="faces",
                    status="shown",
                    details={
                        "max_in_frame": count,
                        "rule": FACES_RULE,
                    },
                )
            )


def _speech_tags(session: Session, media: str, shots: list[Shot]) -> None:
    segments = list(
        session.scalars(select(TranscriptSegment).where(TranscriptSegment.media_id == media))
    )
    for shot in shots:
        covered, used = 0.0, 0
        for seg in segments:
            if is_uncertain(seg.avg_logprob, seg.compression_ratio):
                continue
            overlap = min(seg.end_s, shot.end_s) - max(seg.start_s, shot.start_s)
            if overlap > 0:
                covered += overlap
                used += 1
        if covered >= SPEECH_MIN_S:
            session.add(
                Tag(
                    media_id=media,
                    shot_id=shot.id,
                    group="speech",
                    name="speech",
                    label="Speech",
                    source="transcript",
                    score=None,
                    status="shown",
                    details={
                        "speech_s": round(covered, 2),
                        "segments": used,
                        "rule": SPEECH_RULE,
                    },
                )
            )
