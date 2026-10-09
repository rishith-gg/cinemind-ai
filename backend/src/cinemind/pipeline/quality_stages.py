"""Ingest stages `quality` (picture metrics, black/frozen picture) and `audio_qc` (loudness,
silence, clipping). SPEC section 5, stages 6 and 7.

The stages cache raw MEASUREMENTS only. Scores and flags are derived in the `persist_*` functions
from the current `[quality]` settings, so changing a weight or threshold and pressing "Process
all" re-scores every clip from the cache without decoding any video again.
"""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cinemind.core.errors import SourceMissingError, UnreadableMediaError
from cinemind.core.quality_config import QualityConfig
from cinemind.db.models import AudioMetric, MediaAsset, QcFlag, QualityMetric, Shot
from cinemind.jobs.registry import Stage, StageContext
from cinemind.pipeline import qc, quality
from cinemind.pipeline.stage_utils import (
    checked_source,
    media_id,
    proxy_file,
    source_info,
)

PIPELINE_VERSION = "2"  # 2: loudness says why there is no reading; decode failures are kept


def _detector_params(ctx: StageContext) -> dict[str, float]:
    return dict(ctx.params.get("qc_detect") or qc.detector_params(ctx.settings.quality))


# --- quality (picture) ------------------------------------------------------------------------


def run_quality(ctx: StageContext) -> dict[str, Any]:
    info = source_info(ctx)
    shots = [(int(a), int(b)) for a, b in ctx.previous["shots"]["shots"]]
    if not info.has_video or not shots:
        return {"shots": [], "black": [], "frozen": []}
    num, den = ctx.previous["shots"]["fps"]
    video = proxy_file(ctx)

    def first_half(fraction: float) -> None:
        ctx.progress(fraction / 2)

    def second_half(fraction: float) -> None:
        ctx.progress(0.5 + fraction / 2)

    measured = quality.measure_shots(video, shots, num / den, first_half, ctx.check_cancelled)
    ranges = qc.detect_black_freeze(
        video, info.duration_s, _detector_params(ctx), second_half, ctx.check_cancelled
    )
    return {"shots": measured, **ranges}


def _scoring(cfg: QualityConfig) -> dict[str, float]:
    """The settings a score depends on, stored next to it (rule 6)."""
    return cfg.model_dump()


def update_clip_score(session: Session, media: str, cfg: QualityConfig) -> None:
    """Clip score = shot scores weighted by shot length, blended with the audio score when the
    clip has measured sound; None when nothing could be measured. Called after EITHER stage
    persists, so the clip score never disagrees with the rows it is made from."""
    session.flush()
    rows = session.execute(
        select(QualityMetric.score, Shot.start_s, Shot.end_s)
        .join(Shot, Shot.id == QualityMetric.shot_id)
        .where(QualityMetric.media_id == media)
    ).all()
    seconds = sum(end - start for _, start, end in rows)
    picture = sum(s * (end - start) for s, start, end in rows) / seconds if seconds > 0 else None
    audio = session.scalar(select(AudioMetric.score).where(AudioMetric.media_id == media))
    if picture is None:
        score = audio
    elif audio is None:
        score = round(picture, 4)
    else:
        score = round(picture * (1 - cfg.weight_audio) + audio * cfg.weight_audio, 4)
    asset = session.get(MediaAsset, media)
    if asset is not None:
        asset.quality_score = score


def persist_quality(session: Session, ctx: StageContext, result: dict[str, Any]) -> None:
    cfg = ctx.settings.quality
    media = media_id(ctx)
    shots = {s.index: s for s in session.scalars(select(Shot).where(Shot.media_id == media))}
    session.execute(delete(QcFlag).where(QcFlag.media_id == media, QcFlag.source == "picture"))
    session.execute(delete(QualityMetric).where(QualityMetric.media_id == media))
    for index, entry in enumerate(result["shots"]):
        shot, metrics = shots.get(index), entry["metrics"]
        if shot is None or metrics is None:
            continue
        scores = quality.sub_scores(metrics, cfg)
        details = {"metrics_version": quality.METRICS_VERSION, "settings": _scoring(cfg)}
        session.add(
            QualityMetric(
                shot_id=shot.id,
                media_id=media,
                frames=entry["frames"],
                **metrics,
                sharpness_score=scores["sharpness"],
                exposure_score=scores["exposure"] or 0.0,
                contrast_score=scores["contrast"] or 0.0,
                score=quality.video_score(scores, cfg),
                details=details,
            )
        )
        for flag in quality.picture_flags(metrics, cfg):
            kind = flag.pop("kind")
            session.add(
                QcFlag(
                    media_id=media,
                    shot_id=shot.id,
                    kind=kind,
                    source="picture",
                    start_s=shot.start_s,
                    end_s=shot.end_s,
                    details=flag,
                )
            )
    detector = _detector_params(ctx)
    for kind, key, tool, names in (
        ("black_frames", "black", "ffmpeg blackdetect", ("black_min_s", "black_pixel_threshold")),
        ("frozen_frames", "frozen", "ffmpeg freezedetect", ("freeze_min_s", "freeze_noise_db")),
    ):
        settings = {name: detector[name] for name in names}
        for start, end in result[key]:
            session.add(
                QcFlag(
                    media_id=media,
                    kind=kind,
                    source="picture",
                    start_s=start,
                    end_s=end,
                    details={"detector": tool, "settings": settings},
                )
            )
    update_clip_score(session, media, cfg)


# --- audio QC ---------------------------------------------------------------------------------


def run_audio_qc(ctx: StageContext) -> dict[str, Any]:
    info = source_info(ctx)
    if not info.has_audio:
        return {"has_audio": False}
    source = checked_source(ctx)
    if not source.is_file():
        raise SourceMissingError(
            f"The original file '{source.name}' is missing or was moved. Relink it to continue."
        )
    params = _detector_params(ctx)
    base = {"has_audio": True, "duration_s": info.duration_s}
    try:
        loudness = qc.measure_loudness(
            source, info.duration_s, params, ctx.progress, ctx.check_cancelled
        )
        clipping = qc.count_clipped(source, params["clip_sample_level"], ctx.check_cancelled)
    except UnreadableMediaError as exc:
        # The picture analysis succeeded; a broken audio track must not fail the whole clip.
        return {**base, "measured": False, "reason": exc.message}
    return {**base, "measured": True, **loudness, **clipping}


def audio_score(result: dict[str, Any], cfg: QualityConfig) -> dict[str, float]:
    """Level and clipping sub-scores (0..1) and their minimum. A track with no loudness reading
    scores level 0 when it is silent, and is not penalised when it was only too short to
    measure. Ranges of silence inside a track are reported, not scored."""
    lufs = result["integrated_lufs"]
    if lufs is None:
        level = 1.0 if result.get("loudness_note") == "too_short" else 0.0
    else:
        span = cfg.good_level_lufs - cfg.low_level_lufs_below
        level = min(1.0, max(0.0, (lufs - cfg.low_level_lufs_below) / span))
    clean = 1.0 - min(1.0, result["clipped_pct"] / cfg.clipped_samples_pct_above)
    return {
        "level": round(level, 4),
        "clipping": round(clean, 4),
        "score": round(min(level, clean), 4),
    }


Flag = tuple[str, float, float, dict[str, Any]]


def audio_flags(
    result: dict[str, Any], cfg: QualityConfig, detector: dict[str, float]
) -> list[Flag]:
    duration = float(result["duration_s"])
    if not result.get("measured", True):
        return [("audio_unreadable", 0.0, duration, {"reason": result["reason"]})]
    flags: list[Flag] = [
        (
            "long_silence",
            start,
            end,
            {
                "detector": "ffmpeg silencedetect",
                "metric": "seconds",
                "value": round(end - start, 2),
                "threshold": detector["long_silence_s"],
                "direction": "above",
                "noise_db": detector["silence_noise_db"],
            },
        )
        for start, end in result["silences"]
    ]
    if result["clipped_pct"] > cfg.clipped_samples_pct_above:
        details = {
            "metric": "clipped_pct",
            "value": result["clipped_pct"],
            "threshold": cfg.clipped_samples_pct_above,
            "direction": "above",
        }
        flags.append(("clipped_audio", 0.0, duration, details))
    lufs, note = result["integrated_lufs"], result.get("loudness_note")
    if (lufs is None and note != "too_short") or (
        lufs is not None and lufs < cfg.low_level_lufs_below
    ):
        details = {
            "metric": "integrated_lufs",
            "value": lufs,
            "threshold": cfg.low_level_lufs_below,
            "direction": "below",
        }
        flags.append(("low_audio_level", 0.0, duration, details))
    return flags


def persist_audio_qc(session: Session, ctx: StageContext, result: dict[str, Any]) -> None:
    cfg = ctx.settings.quality
    media = media_id(ctx)
    session.execute(delete(QcFlag).where(QcFlag.media_id == media, QcFlag.source == "audio"))
    session.execute(delete(AudioMetric).where(AudioMetric.media_id == media))
    if result["has_audio"]:
        if result.get("measured", True):
            scores = audio_score(result, cfg)
            silence = sum(end - start for start, end in result["silences"])
            duration = float(result["duration_s"])
            details = {
                "sub_scores": scores,
                "settings": _scoring(cfg),
                "analysed": "source",
                "loudness_note": result.get("loudness_note"),
            }
            session.add(
                AudioMetric(
                    media_id=media,
                    integrated_lufs=result["integrated_lufs"],
                    loudness_range=result["loudness_range"],
                    true_peak_db=result["true_peak_db"],
                    sample_peak=result["sample_peak"],
                    clipped_pct=result["clipped_pct"],
                    silence_s=round(silence, 3),
                    silence_pct=round(100 * silence / duration, 2) if duration > 0 else 0.0,
                    score=scores["score"],
                    details=details,
                )
            )
        for kind, start, end, details in audio_flags(result, cfg, _detector_params(ctx)):
            session.add(
                QcFlag(
                    media_id=media,
                    kind=kind,
                    source="audio",
                    start_s=start,
                    end_s=end,
                    details=details,
                )
            )
    update_clip_score(session, media, cfg)


QUALITY_STAGES = [
    Stage(
        "quality",
        run_quality,
        model_name="opencv-metrics+ffmpeg-detect",
        model_version=f"{quality.METRICS_VERSION}+{PIPELINE_VERSION}",
        params={
            "max_frames_per_shot": quality.MAX_FRAMES_PER_SHOT,
            "min_frame_gap_s": quality.MIN_FRAME_GAP_S,
        },
        param_keys=("qc_detect",),
        persist=persist_quality,
    ),
    Stage(
        "audio_qc",
        run_audio_qc,
        model_name="ffmpeg-ebur128",
        model_version=PIPELINE_VERSION,
        param_keys=("qc_detect",),
        persist=persist_audio_qc,
    ),
]
