"""Import, library and file-serving endpoints for media assets."""

import logging
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cinemind.api.deps import SessionDep, SettingsDep
from cinemind.api.schemas import (
    ErrorResponse,
    ImportItem,
    ImportRequest,
    ImportResponse,
    JobBrief,
    JobOut,
    MediaOut,
    RelinkRequest,
)
from cinemind.core.config import Settings
from cinemind.core.errors import (
    DomainError,
    InvalidInputError,
    JobStateError,
    NotFoundError,
    PathNotAllowedError,
)
from cinemind.core.paths import resolve_in_roots, validate_project_id
from cinemind.db.models import Job, JobEvent, MediaAsset, Project, QcFlag, Transcript
from cinemind.pipeline import importer
from cinemind.pipeline.hashing import content_hash

log = logging.getLogger(__name__)
router = APIRouter(tags=["media"])
ERRORS: dict[int | str, dict[str, Any]] = {
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    413: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}
_MAX_LISTING = 1000


def get_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, validate_project_id(project_id))
    if project is None:
        raise NotFoundError("That project does not exist.")
    return project


def get_asset(session: Session, media_id: str) -> MediaAsset:
    asset = session.get(MediaAsset, media_id)
    if asset is None:
        raise NotFoundError("That media item does not exist.")
    return asset


def _latest_jobs(session: Session, media_ids: list[str]) -> dict[str, Job]:
    jobs = session.scalars(
        select(Job)
        .where(Job.media_id.in_(media_ids), Job.chain == "ingest")
        .order_by(Job.created_at, Job.id)
    )
    return {job.media_id: job for job in jobs if job.media_id}


def _encoder(asset: MediaAsset) -> str | None:
    proxy: dict[str, Any] = asset.artifacts.get("proxy") or {}
    return proxy.get("encoder")


def _flag_kinds(session: Session, media_ids: list[str]) -> dict[str, list[str]]:
    rows = session.execute(
        select(QcFlag.media_id, QcFlag.kind).where(QcFlag.media_id.in_(media_ids)).distinct()
    )
    kinds: dict[str, list[str]] = {}
    for media_id, kind in rows:
        kinds.setdefault(media_id, []).append(kind)
    return {media_id: sorted(found) for media_id, found in kinds.items()}


def _transcripts(session: Session, media_ids: list[str]) -> dict[str, Transcript]:
    rows = session.scalars(select(Transcript).where(Transcript.media_id.in_(media_ids)))
    return {row.media_id: row for row in rows}


def to_out(
    asset: MediaAsset,
    job: Job | None,
    settings: Settings,
    flags: list[str] | None = None,
    transcript: Transcript | None = None,
) -> MediaOut:
    score = asset.quality_score
    return MediaOut(
        id=asset.id,
        project_id=asset.project_id,
        filename=asset.filename,
        path=asset.path,
        import_mode=asset.import_mode,
        size_bytes=asset.size_bytes,
        content_hash=asset.content_hash,
        created_at=asset.created_at,
        source_missing=not Path(asset.path).is_file(),
        probed=asset.probed,
        container=asset.container,
        duration_s=asset.duration_s,
        width=asset.width,
        height=asset.height,
        fps_num=asset.fps_num,
        fps_den=asset.fps_den,
        is_vfr=asset.is_vfr,
        video_codec=asset.video_codec,
        audio_codec=asset.audio_codec,
        bit_rate=asset.bit_rate,
        audio_channels=asset.audio_channels,
        audio_sample_rate=asset.audio_sample_rate,
        start_timecode=asset.start_timecode,
        color=asset.color,
        has_proxy=asset.proxy_path is not None,
        has_poster=asset.poster_path is not None,
        has_strip=asset.strip_path is not None,
        has_waveform=asset.waveform_path is not None,
        proxy_encoder=_encoder(asset),
        strip_frames=int(asset.artifacts.get("strip_frames", 0)),
        quality_score=score,
        low_quality=score is not None and score < settings.quality.low_quality_below,
        qc_flags=flags or [],
        transcript_status=transcript.status if transcript else None,
        transcript_language=transcript.language if transcript else None,
        job=JobBrief.model_validate(job) if job else None,
    )


def _out(session: Session, settings: Settings, asset: MediaAsset) -> MediaOut:
    flags = _flag_kinds(session, [asset.id]).get(asset.id)
    job = _latest_jobs(session, [asset.id]).get(asset.id)
    return to_out(asset, job, settings, flags, session.get(Transcript, asset.id))


# --- import -----------------------------------------------------------------------------------


def _item(session: Session, settings: Settings, result: importer.ImportResult) -> ImportItem:
    return ImportItem(
        path=result.path,
        media=_out(session, settings, result.asset) if result.asset else None,
        duplicate=result.duplicate,
        error_code=result.error_code,
        error_message=result.error_message,
    )


@router.post(
    "/api/projects/{project_id}/media",
    response_model=ImportResponse,
    status_code=201,
    responses=ERRORS,
    operation_id="importMedia",
)
def import_media(
    project_id: str, body: ImportRequest, session: SessionDep, settings: SettingsDep
) -> ImportResponse:
    """Register files or folders (reference in place, or copy) and queue processing."""
    get_project(session, project_id)
    files = importer.expand_paths(body.paths, settings.media_roots)
    items: list[ImportItem] = []
    for source in files:
        try:
            result = importer.import_file(session, settings, project_id, source, body.mode)
            if result.asset and not result.duplicate:
                importer.enqueue_ingest(session, settings, result.asset)
        except DomainError as exc:  # one bad file must not abort the batch
            result = importer.ImportResult(
                path=str(source), error_code=exc.code, error_message=exc.message
            )
        except OSError as exc:
            log.warning("could not import %s: %s", source, exc)
            result = importer.ImportResult(
                path=str(source),
                error_code="unreadable_file",
                error_message=f"'{source.name}' could not be read or copied ({exc.strerror}).",
            )
        items.append(_item(session, settings, result))
    return ImportResponse(items=items)


@router.post(
    "/api/projects/{project_id}/media/upload",
    response_model=ImportItem,
    status_code=201,
    responses=ERRORS,
    operation_id="uploadMedia",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload_media(
    project_id: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    filename: str = Query(min_length=1, max_length=255),
) -> ImportItem:
    """Upload one file as the raw request body (streamed to disk, size-limited)."""
    declared = request.headers.get("content-length")

    def prepare() -> importer.UploadTarget:
        get_project(session, project_id)
        return importer.prepare_upload(
            settings,
            project_id,
            filename,
            int(declared) if declared and declared.isdigit() else None,
        )

    target = await run_in_threadpool(prepare)
    written = 0
    try:
        with target.path.open("wb") as out:
            async for chunk in request.stream():
                written += len(chunk)
                if written > target.limit:
                    raise importer.upload_too_large(settings)
                await run_in_threadpool(out.write, chunk)  # keep the event loop free
    except BaseException:
        shutil.rmtree(target.dir, ignore_errors=True)
        raise

    def register() -> ImportItem:
        try:
            result = importer.finish_upload(session, project_id, target, written)
        except BaseException:
            shutil.rmtree(target.dir, ignore_errors=True)  # nothing was registered
            raise
        if result.asset and not result.duplicate:
            importer.enqueue_ingest(session, settings, result.asset)
        return _item(session, settings, result)

    return await run_in_threadpool(register)


# --- library ----------------------------------------------------------------------------------


@router.get(
    "/api/projects/{project_id}/media",
    response_model=list[MediaOut],
    responses=ERRORS,
    operation_id="listMedia",
)
def list_media(project_id: str, session: SessionDep, settings: SettingsDep) -> list[MediaOut]:
    get_project(session, project_id)
    assets = list(
        session.scalars(
            select(MediaAsset)
            .where(MediaAsset.project_id == project_id)
            .order_by(MediaAsset.created_at.desc(), MediaAsset.id)
        )
    )
    ids = [a.id for a in assets]
    jobs, flags, spoken = (
        _latest_jobs(session, ids),
        _flag_kinds(session, ids),
        _transcripts(session, ids),
    )
    return [to_out(a, jobs.get(a.id), settings, flags.get(a.id), spoken.get(a.id)) for a in assets]


@router.get(
    "/api/media/{media_id}", response_model=MediaOut, responses=ERRORS, operation_id="getMedia"
)
def get_media(media_id: str, session: SessionDep, settings: SettingsDep) -> MediaOut:
    return _out(session, settings, get_asset(session, media_id))


@router.delete(
    "/api/media/{media_id}", status_code=204, responses=ERRORS, operation_id="deleteMedia"
)
def delete_media(media_id: str, session: SessionDep, settings: SettingsDep) -> None:
    """Remove a media item and its derived data. Referenced source files are never touched."""
    asset = get_asset(session, media_id)
    jobs = list(session.scalars(select(Job).where(Job.media_id == media_id)))
    if any(j.status in ("queued", "running") for j in jobs):
        raise JobStateError("This item is being processed. Cancel its job before removing it.")
    session.execute(delete(JobEvent).where(JobEvent.job_id.in_([j.id for j in jobs])))
    importer.delete_asset_files(settings, asset)
    session.delete(asset)
    session.commit()


@router.post(
    "/api/media/{media_id}/process",
    response_model=JobOut,
    status_code=202,
    responses=ERRORS,
    operation_id="processMedia",
)
def process_media(media_id: str, session: SessionDep, settings: SettingsDep) -> Job:
    """(Re)run the ingest chain; finished, still-valid stages are skipped via the cache."""
    return importer.enqueue_ingest(session, settings, get_asset(session, media_id))


@router.post(
    "/api/projects/{project_id}/process",
    response_model=list[JobOut],
    status_code=202,
    responses=ERRORS,
    operation_id="processProject",
)
def process_project(project_id: str, session: SessionDep, settings: SettingsDep) -> list[Job]:
    get_project(session, project_id)
    assets = session.scalars(select(MediaAsset).where(MediaAsset.project_id == project_id))
    return [importer.enqueue_ingest(session, settings, a) for a in list(assets)]


@router.post(
    "/api/media/{media_id}/relink",
    response_model=MediaOut,
    responses=ERRORS,
    operation_id="relinkMedia",
)
def relink_media(
    media_id: str, body: RelinkRequest, session: SessionDep, settings: SettingsDep
) -> MediaOut:
    """Point a moved/missing reference at its new location. The content must be identical."""
    asset = get_asset(session, media_id)
    if asset.import_mode != "reference":
        raise InvalidInputError("Only referenced files can be relinked.")
    if not Path(body.path).is_absolute():
        raise InvalidInputError("Media paths must be absolute.")
    new_path = resolve_in_roots(body.path, settings.media_roots)
    if not new_path.is_file():
        raise InvalidInputError("That file does not exist.")
    if content_hash(new_path) != asset.content_hash:
        raise InvalidInputError(
            "That file does not match the original (different content). Import it as new media."
        )
    asset.path, asset.filename = str(new_path), new_path.name
    session.commit()
    return _out(session, settings, asset)


# --- files (derived data only; Range requests are handled by FileResponse) ---------------------

_TYPES = {
    ".mp4": "video/mp4",
    ".m4a": "audio/mp4",
    ".jpg": "image/jpeg",
    ".json": "application/json",
}


def serve_derived(
    settings: Settings, asset: MediaAsset, rel: str | None, what: str
) -> FileResponse:
    if rel is None:
        raise NotFoundError(f"The {what} for this item has not been generated yet.")
    root = settings.project_dir(asset.project_id).resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root):  # defence in depth: DB values are ours, but never trust
        raise PathNotAllowedError("That file is outside the project folder.")
    if not path.is_file():
        raise NotFoundError(f"The {what} file is missing. Reprocess the item to recreate it.")
    return FileResponse(
        path,
        media_type=_TYPES.get(path.suffix, "application/octet-stream"),
        headers={"Cache-Control": "private, max-age=0, must-revalidate"},
    )


@router.get("/api/media/{media_id}/stream", responses=ERRORS, operation_id="streamProxy")
def stream_proxy(media_id: str, session: SessionDep, settings: SettingsDep) -> FileResponse:
    asset = get_asset(session, media_id)
    return serve_derived(settings, asset, asset.proxy_path, "playback proxy")


@router.get("/api/media/{media_id}/poster", responses=ERRORS, operation_id="getPoster")
def get_poster(media_id: str, session: SessionDep, settings: SettingsDep) -> FileResponse:
    asset = get_asset(session, media_id)
    return serve_derived(settings, asset, asset.poster_path, "thumbnail")


@router.get("/api/media/{media_id}/strip", responses=ERRORS, operation_id="getStrip")
def get_strip(media_id: str, session: SessionDep, settings: SettingsDep) -> FileResponse:
    asset = get_asset(session, media_id)
    return serve_derived(settings, asset, asset.strip_path, "thumbnail strip")


@router.get("/api/media/{media_id}/waveform", responses=ERRORS, operation_id="getWaveform")
def get_waveform(media_id: str, session: SessionDep, settings: SettingsDep) -> FileResponse:
    asset = get_asset(session, media_id)
    return serve_derived(settings, asset, asset.waveform_path, "waveform")
