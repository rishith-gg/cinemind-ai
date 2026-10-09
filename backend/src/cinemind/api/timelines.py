"""Timelines and their export files (FCP7 XML, EDL, OTIO)."""

from fractions import Fraction

from fastapi import APIRouter
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemind.api.deps import SessionDep, SettingsDep
from cinemind.api.media import ERRORS, get_project
from cinemind.api.schemas import TimelineCreate, TimelineDetail, TimelineItemOut, TimelineOut
from cinemind.core.config import Settings
from cinemind.core.errors import InvalidInputError, NotFoundError
from cinemind.db.models import Timeline
from cinemind.export import service
from cinemind.export.sequence import Sequence
from cinemind.rough_cut.assembly import build_all_shots

router = APIRouter(tags=["timelines"])


def _timeline(session: Session, timeline_id: str) -> Timeline:
    timeline = session.get(Timeline, timeline_id)
    if timeline is None:
        raise NotFoundError("That timeline does not exist.")
    return timeline


def _summary(settings: Settings, timeline: Timeline, seq: Sequence) -> TimelineOut:
    rate = Fraction(timeline.fps_num, timeline.fps_den)
    return TimelineOut(
        id=timeline.id,
        project_id=timeline.project_id,
        name=timeline.name,
        kind=timeline.kind,
        fps_num=timeline.fps_num,
        fps_den=timeline.fps_den,
        width=timeline.width,
        height=timeline.height,
        params=timeline.params,
        created_at=timeline.created_at,
        item_count=len(seq.cuts),
        duration_frames=seq.duration,
        duration_s=float(seq.duration / rate),
        warnings=seq.warnings,
        export_dir=str(service.export_dir(settings, timeline)),
        formats=list(service.EXTENSIONS),
    )


def _detail(session: Session, settings: Settings, timeline: Timeline) -> TimelineDetail:
    seq = service.load_sequence(session, timeline)
    items = [
        TimelineItemOut(
            position=position,
            media_id=cut.source.media_id,
            shot_id=cut.shot_id,
            filename=cut.source.name,
            source_in_s=float(cut.src_in / cut.rate),
            source_out_s=float((cut.src_in + cut.duration) / cut.rate),
            record_frame=cut.record,
            duration_frames=cut.duration,
            source_fps_num=cut.source.rate.numerator,
            source_fps_den=cut.source.rate.denominator,
            mixed_rate=cut.mixed_rate,
        )
        for position, cut in enumerate(seq.cuts)
    ]
    return TimelineDetail(**_summary(settings, timeline, seq).model_dump(), items=items)


@router.post(
    "/api/projects/{project_id}/timelines",
    response_model=TimelineDetail,
    status_code=201,
    responses=ERRORS,
    operation_id="createTimeline",
)
def create_timeline(
    project_id: str, body: TimelineCreate, session: SessionDep, settings: SettingsDep
) -> TimelineDetail:
    """Build the chronological "all shots" timeline: every detected shot, nothing selected."""
    get_project(session, project_id)
    fps = None
    if body.fps is not None:
        if body.fps[0] <= 0 or body.fps[1] <= 0:
            raise InvalidInputError("The frame rate must be two positive numbers.")
        fps = Fraction(*body.fps)
    timeline = build_all_shots(session, project_id, body.name.strip(), fps, body.mixed_rates)
    return _detail(session, settings, timeline)


@router.get(
    "/api/projects/{project_id}/timelines",
    response_model=list[TimelineOut],
    responses=ERRORS,
    operation_id="listTimelines",
)
def list_timelines(
    project_id: str, session: SessionDep, settings: SettingsDep
) -> list[TimelineOut]:
    get_project(session, project_id)
    query = (
        select(Timeline)
        .where(Timeline.project_id == project_id)
        .order_by(Timeline.created_at.desc(), Timeline.id)
    )
    return [
        _summary(settings, t, service.load_sequence(session, t)) for t in session.scalars(query)
    ]


@router.get(
    "/api/timelines/{timeline_id}",
    response_model=TimelineDetail,
    responses=ERRORS,
    operation_id="getTimeline",
)
def get_timeline(timeline_id: str, session: SessionDep, settings: SettingsDep) -> TimelineDetail:
    return _detail(session, settings, _timeline(session, timeline_id))


@router.delete(
    "/api/timelines/{timeline_id}",
    status_code=204,
    responses=ERRORS,
    operation_id="deleteTimeline",
)
def delete_timeline(timeline_id: str, session: SessionDep) -> None:
    """Remove the timeline. Files already exported stay in the exports folder."""
    session.delete(_timeline(session, timeline_id))
    session.commit()


@router.get(
    "/api/timelines/{timeline_id}/export/{fmt}",
    responses=ERRORS,
    operation_id="exportTimeline",
)
def export_timeline(
    timeline_id: str, fmt: str, session: SessionDep, settings: SettingsDep
) -> FileResponse:
    """Write the timeline to the project's exports folder and download it."""
    if fmt not in service.EXTENSIONS:
        raise InvalidInputError(f"Unknown export format '{fmt}'. Use fcp7xml, edl or otio.")
    out = service.export_timeline(session, settings, _timeline(session, timeline_id), fmt)
    return FileResponse(out.path, media_type=out.media_type, filename=out.filename)
