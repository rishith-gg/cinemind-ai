"""Faces and actors: what was found per clip, the project's people, and the user's corrections
(rename, merge, split, not a face, unknown). Groups are suggestions by face similarity, local to
the project; nothing here matches a face to a real-world identity."""

from fastapi import APIRouter
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, defer

from cinemind.ai.faces import PULL_HINT
from cinemind.api.actor_schemas import (
    ActorDetail,
    ActorMerge,
    ActorOut,
    ActorRename,
    ActorsOut,
    FaceScanStatus,
    FaceTrackOut,
    MediaFacesOut,
    TrackPlacement,
    TrackSelection,
    TrackState,
)
from cinemind.api.deps import SessionDep, SettingsDep
from cinemind.api.media import ERRORS, get_asset, get_project, serve_derived
from cinemind.core.errors import NotFoundError
from cinemind.db.models import MediaAsset
from cinemind.db.people import Actor, ActorRun, FaceScan, FaceTrack
from cinemind.pipeline import actor_corrections as corrections
from cinemind.pipeline import actors as service
from cinemind.rough_cut.assembly import natural_key

router = APIRouter(tags=["actors"])

_MODEL_MISSING = f"The face models are not downloaded. {PULL_HINT}"


def _actor(session: Session, actor_id: str) -> Actor:
    actor = session.get(Actor, actor_id)
    if actor is None:
        raise NotFoundError("That person no longer exists. Reload the page.")
    return actor


def _tracks(
    session: Session,
    project_id: str,
    media_id: str | None = None,
    actor_id: str | None = None,
) -> list[tuple[FaceTrack, str]]:
    """Tracks with their clip's file name, without the vectors (only grouping reads those)."""
    query = (
        select(FaceTrack, MediaAsset.filename)
        .join(MediaAsset, MediaAsset.id == FaceTrack.media_id)
        .where(MediaAsset.project_id == project_id)
        .options(defer(FaceTrack.embedding))
    )
    if media_id is not None:
        query = query.where(FaceTrack.media_id == media_id)
    if actor_id is not None:
        query = query.where(FaceTrack.actor_id == actor_id)
    rows = [(track, name) for track, name in session.execute(query)]
    return sorted(rows, key=lambda row: (natural_key(row[1]), row[0].media_id, row[0].start_s))


def _track_out(track: FaceTrack, filename: str, names: dict[str, str]) -> FaceTrackOut:
    state: TrackState = track.state  # pyright: ignore[reportAssignmentType]
    return FaceTrackOut(
        id=track.id,
        media_id=track.media_id,
        filename=filename,
        start_s=track.start_s,
        end_s=track.end_s,
        face_count=track.face_count,
        crop_url=f"/api/face-tracks/{track.id}/image",
        actor_id=track.actor_id,
        actor_name=names.get(track.actor_id or ""),
        state=state,
        assignment=track.assignment,
    )


def _actor_out(actor: Actor, tracks: list[FaceTrack]) -> ActorOut:
    best = max(tracks, key=lambda t: (t.face_count, t.id), default=None)
    return ActorOut(
        id=actor.id,
        project_id=actor.project_id,
        number=actor.number,
        name=actor.name,
        named=actor.named,
        tracks=len(tracks),
        faces=sum(t.face_count for t in tracks),
        clips=len({t.media_id for t in tracks}),
        seen_s=round(sum(t.end_s - t.start_s for t in tracks), 2),
        crop_url=f"/api/face-tracks/{best.id}/image" if best else None,
    )


def _names(session: Session, project_id: str) -> dict[str, str]:
    query = select(Actor.id, Actor.name).where(Actor.project_id == project_id)
    return {actor_id: name for actor_id, name in session.execute(query)}


def _overview(session: Session, project_id: str) -> ActorsOut:
    by_actor: dict[str, list[FaceTrack]] = {}
    aside = {"ignored": 0, "unknown": 0}
    for track, _ in _tracks(session, project_id):
        if track.actor_id is not None:
            by_actor.setdefault(track.actor_id, []).append(track)
        elif track.state in aside:
            aside[track.state] += 1
    people = session.scalars(select(Actor).where(Actor.project_id == project_id))
    listed = [_actor_out(actor, by_actor[actor.id]) for actor in people if actor.id in by_actor]
    scans: dict[str, int] = {
        status: count
        for status, count in session.execute(
            select(func.coalesce(FaceScan.status, "pending"), func.count())
            .select_from(MediaAsset)
            .outerjoin(FaceScan, FaceScan.media_id == MediaAsset.id)
            .where(MediaAsset.project_id == project_id)
            .group_by(FaceScan.status)
        )
    }
    message = None
    if scans.get("model_missing"):
        message = _MODEL_MISSING
    elif scans.get("pending") and not listed:
        message = (
            "No clip has been searched for faces yet. Processing may still be running; "
            "otherwise press Process all in the Library."
        )
    run = session.get(ActorRun, project_id)
    return ActorsOut(
        actors=sorted(listed, key=lambda a: (-a.faces, a.number)),
        ignored=aside["ignored"],
        unknown=aside["unknown"],
        scans=scans,
        message=message,
        run=run.details if run else None,
        clustered_at=run.clustered_at if run else None,
    )


def _detail(session: Session, actor: Actor) -> ActorDetail:
    names = {actor.id: actor.name}
    rows = _tracks(session, actor.project_id, actor_id=actor.id)
    summary = _actor_out(actor, [track for track, _ in rows])
    track_list = [_track_out(track, name, names) for track, name in rows]
    return ActorDetail(**summary.model_dump(), track_list=track_list)


@router.get(
    "/api/projects/{project_id}/actors",
    response_model=ActorsOut,
    responses=ERRORS,
    operation_id="listActors",
)
def list_actors(project_id: str, session: SessionDep) -> ActorsOut:
    """The project's people, most seen first, with what the last grouping used."""
    get_project(session, project_id)
    return _overview(session, project_id)


@router.post(
    "/api/projects/{project_id}/actors/regroup",
    response_model=ActorsOut,
    responses=ERRORS,
    operation_id="regroupActors",
)
def regroup_actors(project_id: str, session: SessionDep, settings: SettingsDep) -> ActorsOut:
    """Group the project's faces again with the current `[faces]` settings. Corrections stay."""
    get_project(session, project_id)
    service.regroup(session, settings, project_id, force=True)
    session.commit()
    return _overview(session, project_id)


@router.get(
    "/api/projects/{project_id}/face-tracks",
    response_model=list[FaceTrackOut],
    responses=ERRORS,
    operation_id="listSetAsideFaces",
)
def list_set_aside(project_id: str, session: SessionDep) -> list[FaceTrackOut]:
    """Faces the user set aside: marked "not a face" (ignored) or "unknown person"."""
    get_project(session, project_id)
    rows = _tracks(session, project_id)
    return [_track_out(t, n, {}) for t, n in rows if t.state in ("ignored", "unknown")]


@router.post(
    "/api/projects/{project_id}/face-tracks/place",
    response_model=ActorsOut,
    responses=ERRORS,
    operation_id="placeFaceTracks",
)
def place_tracks(
    project_id: str, body: TrackPlacement, session: SessionDep, settings: SettingsDep
) -> ActorsOut:
    """Move faces to another person, set them aside, or hand them back to automatic grouping."""
    get_project(session, project_id)
    actor = _actor(session, body.actor_id) if body.state == "actor" and body.actor_id else None
    corrections.place(session, settings, project_id, body.track_ids, body.state, actor)
    session.commit()
    return _overview(session, project_id)


@router.get(
    "/api/actors/{actor_id}",
    response_model=ActorDetail,
    responses=ERRORS,
    operation_id="getActor",
)
def get_actor(actor_id: str, session: SessionDep) -> ActorDetail:
    return _detail(session, _actor(session, actor_id))


@router.patch(
    "/api/actors/{actor_id}",
    response_model=ActorDetail,
    responses=ERRORS,
    operation_id="renameActor",
)
def rename_actor(
    actor_id: str, body: ActorRename, session: SessionDep, settings: SettingsDep
) -> ActorDetail:
    actor = _actor(session, actor_id)
    corrections.rename(session, settings, actor, body.name)
    session.commit()
    return _detail(session, actor)


@router.post(
    "/api/actors/{actor_id}/merge",
    response_model=ActorDetail,
    responses=ERRORS,
    operation_id="mergeActors",
)
def merge_actors(
    actor_id: str, body: ActorMerge, session: SessionDep, settings: SettingsDep
) -> ActorDetail:
    """Merge the listed people into this one."""
    actor = _actor(session, actor_id)
    others = [_actor(session, other) for other in body.actor_ids]
    if any(other.project_id != actor.project_id for other in others):
        raise NotFoundError("Those people are not in the same project.")
    corrections.merge(session, settings, actor, others)
    session.commit()
    return _detail(session, actor)


@router.post(
    "/api/actors/{actor_id}/split",
    response_model=ActorDetail,
    responses=ERRORS,
    operation_id="splitActor",
)
def split_actor(
    actor_id: str, body: TrackSelection, session: SessionDep, settings: SettingsDep
) -> ActorDetail:
    """Move the chosen faces of this person to a new person, which is returned."""
    created = corrections.split(session, settings, _actor(session, actor_id), body.track_ids)
    session.commit()
    return _detail(session, created)


@router.get(
    "/api/media/{media_id}/faces",
    response_model=MediaFacesOut,
    responses=ERRORS,
    operation_id="getMediaFaces",
)
def get_media_faces(media_id: str, session: SessionDep) -> MediaFacesOut:
    """Faces found in one clip: counts, what the checks left out, and the tracks with the
    person each one was grouped with."""
    asset = get_asset(session, media_id)
    scan = session.get(FaceScan, media_id)
    status: FaceScanStatus = scan.status if scan else "pending"  # pyright: ignore[reportAssignmentType]
    message = {
        "pending": "Not searched for faces yet. Processing may still be running; otherwise "
        "press Reprocess.",
        "no_faces": "No usable face was found in this clip.",
        "no_video": "This item has no picture.",
        "model_missing": _MODEL_MISSING,
    }.get(status)
    names = _names(session, asset.project_id)
    return MediaFacesOut(
        media_id=media_id,
        status=status,
        message=message,
        frames_sampled=scan.frames_sampled if scan else 0,
        faces_detected=scan.faces_detected if scan else 0,
        faces_used=scan.faces_used if scan else 0,
        max_in_frame=scan.max_in_frame if scan else 0,
        details=scan.details if scan else {},
        tracks=[_track_out(t, n, names) for t, n in _tracks(session, asset.project_id, media_id)],
    )


@router.get("/api/face-tracks/{track_id}/image", responses=ERRORS, operation_id="getFaceCrop")
def get_face_crop(track_id: str, session: SessionDep, settings: SettingsDep) -> FileResponse:
    track = session.get(FaceTrack, track_id)
    if track is None:
        raise NotFoundError("That face no longer exists. Reload the page.")
    return serve_derived(settings, get_asset(session, track.media_id), track.crop_path, "face")
