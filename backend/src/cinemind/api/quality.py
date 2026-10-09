"""Technical quality of a clip: scores, the measurements behind them, and QC flags."""

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from cinemind.api.deps import SessionDep, SettingsDep
from cinemind.api.media import ERRORS, get_asset
from cinemind.api.schemas import AudioQualityOut, QcFlagOut, QualityOut, ShotQualityOut
from cinemind.db.models import AudioMetric, QcFlag, QualityMetric, Shot

router = APIRouter(tags=["quality"])


def _columns(metric: QualityMetric) -> dict[str, Any]:
    return {c.name: getattr(metric, c.name) for c in QualityMetric.__table__.columns}


@router.get(
    "/api/media/{media_id}/quality",
    response_model=QualityOut,
    responses=ERRORS,
    operation_id="getMediaQuality",
)
def get_media_quality(media_id: str, session: SessionDep, settings: SettingsDep) -> QualityOut:
    """Everything needed to explain a clip's score: per-shot metrics and sub-scores, audio
    measurements, flags with the value and threshold behind each, and the settings in force."""
    asset = get_asset(session, media_id)
    cfg = settings.quality
    shots = session.execute(
        select(QualityMetric, Shot.index)
        .join(Shot, Shot.id == QualityMetric.shot_id)
        .where(QualityMetric.media_id == media_id)
        .order_by(Shot.index)
    ).all()
    audio = session.get(AudioMetric, media_id)
    current = cfg.model_dump()
    stored: dict[str, float] = next(
        (row.details["settings"] for row in [*(m for m, _ in shots), audio] if row is not None),
        current,
    )
    flags = session.scalars(
        select(QcFlag).where(QcFlag.media_id == media_id).order_by(QcFlag.start_s, QcFlag.id)
    )
    score = asset.quality_score
    return QualityOut(
        media_id=media_id,
        measured=score is not None,
        score=score,
        low_quality=score is not None and score < cfg.low_quality_below,
        shots=[
            ShotQualityOut.model_validate({**_columns(metric), "index": index})
            for metric, index in shots
        ],
        audio=AudioQualityOut.model_validate(audio) if audio else None,
        flags=[
            QcFlagOut(
                kind=f.kind,
                source=f.source,
                shot_id=f.shot_id,
                start_s=f.start_s,
                end_s=f.end_s,
                details=f.details,
            )
            for f in flags
        ],
        config=stored,
        settings_changed=stored != current,
    )
