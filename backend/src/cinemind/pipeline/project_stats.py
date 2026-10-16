"""Footage statistics of one project for the Dashboard: counts read from the database, nothing
estimated. Each clip's processing state is the state of its latest job."""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cinemind.core.config import Settings
from cinemind.db.analysis import Scene, ShotMark
from cinemind.db.models import (
    Job,
    MediaAsset,
    QcFlag,
    QualityMetric,
    Shot,
    Timeline,
    Transcript,
    TranscriptSegment,
)
from cinemind.db.people import Actor
from cinemind.db.takes import TakeGroup, TakeMember

# Shot quality is shown in these bands (Technical Quality Score, 0..1).
BANDS = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0001)


@dataclass
class ProjectStats:
    clips: int = 0
    duration_s: float = 0.0
    size_bytes: int = 0
    states: dict[str, int] = field(default_factory=lambda: {})
    codecs: dict[str, int] = field(default_factory=lambda: {})
    portrait: int = 0
    landscape: int = 0
    variable_rate: int = 0
    no_audio: int = 0
    frame_rates: list[str] = field(default_factory=lambda: [])
    shots: int = 0
    scenes: int = 0
    quality_bands: list[int] = field(default_factory=lambda: [0] * (len(BANDS) - 1))
    quality_measured: int = 0
    low_quality: int = 0
    low_quality_below: float = 0.5
    qc_flags: dict[str, int] = field(default_factory=lambda: {})
    transcripts: dict[str, int] = field(default_factory=lambda: {})
    languages: dict[str, int] = field(default_factory=lambda: {})
    speech_s: float = 0.0
    segments: int = 0
    actors: int = 0
    actors_named: int = 0
    take_groups: int = 0
    shots_in_takes: int = 0
    selected: int = 0
    rejected: int = 0
    timelines: dict[str, int] = field(default_factory=lambda: {})


def _rate(asset: MediaAsset) -> str | None:
    num, den = asset.nominal_fps_num or asset.fps_num, asset.nominal_fps_den or asset.fps_den
    if not num or not den:
        return None
    value = num / den
    return f"{value:.3f}".rstrip("0").rstrip(".")


def project_stats(session: Session, settings: Settings, project_id: str) -> ProjectStats:
    st = ProjectStats(low_quality_below=settings.quality.low_quality_below)
    assets = list(session.scalars(select(MediaAsset).where(MediaAsset.project_id == project_id)))
    ids = [a.id for a in assets]
    st.clips = len(assets)
    st.duration_s = round(sum(a.duration_s or 0.0 for a in assets), 1)
    st.size_bytes = sum(a.size_bytes or 0 for a in assets)
    st.codecs = dict(Counter((a.video_codec or "none") for a in assets).most_common())
    st.portrait = sum(1 for a in assets if a.width and a.height and a.height > a.width)
    st.landscape = sum(1 for a in assets if a.width and a.height and a.width >= a.height)
    st.variable_rate = sum(1 for a in assets if a.is_vfr)
    st.no_audio = sum(1 for a in assets if a.probed and not a.audio_codec)
    st.frame_rates = sorted({r for a in assets if (r := _rate(a))}, key=float)

    latest: dict[str, tuple[Any, str]] = {}
    for media_id, created, status in session.execute(
        select(Job.media_id, Job.created_at, Job.status).where(Job.media_id.in_(ids))
    ):
        if media_id not in latest or created > latest[media_id][0]:
            latest[str(media_id)] = (created, status)
    states = Counter(status for _, status in latest.values())
    states["not processed"] = st.clips - len(latest)
    st.states = {k: v for k, v in states.items() if v}

    st.shots = (
        session.scalar(select(func.count()).select_from(Shot).where(Shot.media_id.in_(ids))) or 0
    )
    st.scenes = (
        session.scalar(
            select(func.count()).select_from(Scene).where(Scene.project_id == project_id)
        )
        or 0
    )
    for (score,) in session.execute(
        select(QualityMetric.score).where(QualityMetric.media_id.in_(ids))
    ):
        st.quality_measured += 1
        band = next(i for i in range(len(BANDS) - 1) if score < BANDS[i + 1])
        st.quality_bands[band] += 1
        st.low_quality += score < st.low_quality_below
    st.qc_flags = dict(
        Counter(session.scalars(select(QcFlag.kind).where(QcFlag.media_id.in_(ids)))).most_common()
    )

    for status, language, speech in session.execute(
        select(Transcript.status, Transcript.language, Transcript.speech_s).where(
            Transcript.media_id.in_(ids)
        )
    ):
        st.transcripts[status] = st.transcripts.get(status, 0) + 1
        if language:
            st.languages[language] = st.languages.get(language, 0) + 1
        st.speech_s += speech or 0.0
    st.speech_s = round(st.speech_s, 1)
    st.segments = (
        session.scalar(
            select(func.count())
            .select_from(TranscriptSegment)
            .where(TranscriptSegment.media_id.in_(ids))
        )
        or 0
    )

    for named in session.scalars(select(Actor.named).where(Actor.project_id == project_id)):
        st.actors += 1
        st.actors_named += bool(named)
    st.take_groups = (
        session.scalar(
            select(func.count()).select_from(TakeGroup).where(TakeGroup.project_id == project_id)
        )
        or 0
    )
    st.shots_in_takes = (
        session.scalar(
            select(func.count())
            .select_from(TakeMember)
            .join(TakeGroup, TakeGroup.id == TakeMember.group_id)
            .where(TakeGroup.project_id == project_id)
        )
        or 0
    )
    marks = Counter(session.scalars(select(ShotMark.mark).where(ShotMark.project_id == project_id)))
    st.selected, st.rejected = marks.get("select", 0), marks.get("reject", 0)
    st.timelines = dict(
        Counter(
            session.scalars(select(Timeline.kind).where(Timeline.project_id == project_id))
        ).most_common()
    )
    return st
