"""Timelines (the "all shots" timeline and the AI-assisted rough cut), the editor's changes to
them, and their export files (FCP7 XML, EDL, OTIO, SRT)."""

from fractions import Fraction
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemind.api.deps import SessionDep, SettingsDep
from cinemind.api.media import ERRORS, get_project
from cinemind.api.timeline_schemas import (
    AlternativeOut,
    RoughCutCreate,
    SwapRequest,
    TimelineCreate,
    TimelineDetail,
    TimelineItemOut,
    TimelineOut,
    TimelineUpdate,
)
from cinemind.core.config import Settings
from cinemind.core.errors import InvalidInputError, NotFoundError
from cinemind.db.models import Keyframe, MediaAsset, Shot, Timeline
from cinemind.export import service
from cinemind.export.sequence import Sequence
from cinemind.rough_cut import editing, engine
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


def _rate(fps: tuple[int, int] | None) -> Fraction | None:
    if fps is None:
        return None
    if fps[0] <= 0 or fps[1] <= 0:
        raise InvalidInputError("The frame rate must be two positive numbers.")
    return Fraction(*fps)


def _keyframes(session: Session, shot_ids: set[str]) -> dict[str, str]:
    """The middle keyframe of each shot, for thumbnails."""
    rows: dict[str, list[tuple[int, str]]] = {}
    query = select(Keyframe.shot_id, Keyframe.slot, Keyframe.id).where(
        Keyframe.shot_id.in_(shot_ids)
    )
    for shot_id, slot, keyframe_id in session.execute(query):
        rows.setdefault(shot_id, []).append((slot, keyframe_id))
    return {s: sorted(k)[len(k) // 2][1] for s, k in rows.items()}


def _alternatives(
    session: Session, timeline: Timeline, keyframes: dict[str, str]
) -> list[AlternativeOut]:
    entries: list[dict[str, Any]] = timeline.params.get("alternatives", [])
    used = {i.shot_id for i in timeline.items}
    wanted = [e for e in entries if e["shot_id"] not in used]
    shots = {
        s.id: s
        for s in session.scalars(select(Shot).where(Shot.id.in_([e["shot_id"] for e in wanted])))
    }
    found: list[AlternativeOut] = []
    for e in wanted:
        shot = shots.get(e["shot_id"])
        if shot is None:  # re-detected or removed since the cut was built
            continue
        reason: dict[str, Any] = e.get("reason") or {}
        found.append(
            AlternativeOut(
                shot_id=shot.id,
                media_id=shot.media_id,
                filename=e.get("filename", ""),
                start_s=shot.start_s,
                end_s=shot.end_s,
                scene_id=shot.scene_id,
                keyframe_id=keyframes.get(shot.id),
                summary=str(reason.get("summary", "")),
                rank=reason.get("rank"),
            )
        )
    return found


def _detail(session: Session, settings: Settings, timeline: Timeline) -> TimelineDetail:
    seq = service.load_sequence(session, timeline)
    items_by_id = {i.id: i for i in timeline.items}
    alt_ids = {a["shot_id"] for a in timeline.params.get("alternatives", [])}
    shot_ids = {c.shot_id for c in seq.cuts if c.shot_id} | alt_ids
    shots = {s.id: s for s in session.scalars(select(Shot).where(Shot.id.in_(shot_ids)))}
    durations = dict(
        session.execute(
            select(MediaAsset.id, MediaAsset.duration_s).where(
                MediaAsset.id.in_({c.source.media_id for c in seq.cuts})
            )
        ).all()
    )
    keyframes = _keyframes(session, shot_ids)
    items: list[TimelineItemOut] = []
    for position, cut in enumerate(seq.cuts):
        item = items_by_id.get(cut.item_id or "")
        shot = shots.get(cut.shot_id or "")
        items.append(
            TimelineItemOut(
                id=cut.item_id or "",
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
                media_duration_s=durations.get(cut.source.media_id),
                shot_start_s=shot.start_s if shot else None,
                shot_end_s=shot.end_s if shot else None,
                scene_id=shot.scene_id if shot else None,
                keyframe_id=keyframes.get(cut.shot_id or ""),
                reason=item.reason if item else None,
            )
        )
    return TimelineDetail(
        **_summary(settings, timeline, seq).model_dump(),
        items=items,
        alternatives=_alternatives(session, timeline, keyframes),
    )


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
    fps = _rate(body.fps)
    timeline = build_all_shots(session, project_id, body.name.strip(), fps, body.mixed_rates)
    return _detail(session, settings, timeline)


@router.post(
    "/api/projects/{project_id}/rough-cut",
    response_model=TimelineDetail,
    status_code=201,
    responses=ERRORS,
    operation_id="createRoughCut",
)
def create_rough_cut(
    project_id: str, body: RoughCutCreate, session: SessionDep, settings: SettingsDep
) -> TimelineDetail:
    """Build an AI-assisted rough cut from a brief: search, filter, select, trim, fit the
    length, order. Every clip carries the reason it was chosen. Human review required."""
    get_project(session, project_id)
    request = engine.Request(
        brief=body.brief,
        target_s=body.target_s,
        order=body.order,
        actor_id=body.actor_id,
        scene_id=body.scene_id,
        name=body.name,
        fps=_rate(body.fps),
    )
    timeline = engine.build_rough_cut(session, settings, project_id, request)
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


@router.patch(
    "/api/timelines/{timeline_id}",
    response_model=TimelineDetail,
    responses=ERRORS,
    operation_id="updateTimeline",
)
def update_timeline(
    timeline_id: str, body: TimelineUpdate, session: SessionDep, settings: SettingsDep
) -> TimelineDetail:
    """Rename, and/or set the clips: the list given is the new order with its in/out points;
    clips left out are removed. Source footage is never touched."""
    timeline = _timeline(session, timeline_id)
    items = (
        None
        if body.items is None
        else [editing.ItemEdit(e.id, e.source_in_s, e.source_out_s) for e in body.items]
    )
    editing.edit(session, timeline, body.name, items)
    session.commit()
    return _detail(session, settings, timeline)


@router.post(
    "/api/timelines/{timeline_id}/items/{item_id}/swap",
    response_model=TimelineDetail,
    responses=ERRORS,
    operation_id="swapTimelineItem",
)
def swap_timeline_item(
    timeline_id: str, item_id: str, body: SwapRequest, session: SessionDep, settings: SettingsDep
) -> TimelineDetail:
    """Replace a clip with another shot (usually a suggested alternative), trimmed with the
    rough cut rules; the clip taken out becomes a suggestion."""
    timeline = _timeline(session, timeline_id)
    editing.swap(session, settings, timeline, item_id, body.shot_id)
    session.commit()
    return _detail(session, settings, timeline)


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
        raise InvalidInputError(service.UNKNOWN_FORMAT.format(fmt))
    out = service.export_timeline(session, settings, _timeline(session, timeline_id), fmt)
    return FileResponse(out.path, media_type=out.media_type, filename=out.filename)
