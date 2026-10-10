"""Import footage into a project: reference in place, copy, or upload. Never touches sources."""

import logging
import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cinemind.core.config import Settings
from cinemind.core.errors import (
    InvalidInputError,
    LowDiskSpaceError,
    PathNotAllowedError,
    PayloadTooLargeError,
)
from cinemind.core.paths import resolve_in_roots, sanitize_filename
from cinemind.db.base import new_id
from cinemind.db.models import Job, MediaAsset
from cinemind.jobs import queue
from cinemind.pipeline import transcribe_stages
from cinemind.pipeline.hashing import content_hash
from cinemind.pipeline.qc import detector_params

log = logging.getLogger(__name__)

# Hint used only to pick candidates when expanding a folder; every file is validated by ffprobe.
_EXTENSIONS = (
    ".mp4 .m4v .mov .mkv .avi .webm .mxf .mts .m2ts .ts .mpg .mpeg .wmv .flv .3gp .ogv "
    ".wav .mp3 .m4a .aac .flac .aiff .aif .ogg .opus"
)
MEDIA_EXTENSIONS = frozenset(_EXTENSIONS.split())
MAX_FOLDER_FILES = 2000
_MIN_FREE_BYTES = 500 * 1024 * 1024


@dataclass
class ImportResult:
    path: str
    asset: MediaAsset | None = None
    duplicate: bool = False
    error_code: str | None = None
    error_message: str | None = None


def is_media_candidate(path: Path) -> bool:
    return path.suffix.lower() in MEDIA_EXTENSIONS


def expand_paths(paths: Iterable[str], roots: list[Path]) -> list[Path]:
    """Files to import: explicit files as given, folders expanded recursively (media-like names
    only, hidden entries and links leaving the approved roots skipped)."""
    found: list[Path] = []
    for raw in paths:
        if not Path(raw).is_absolute():
            raise InvalidInputError("Media paths must be absolute.")
        resolved = resolve_in_roots(raw, roots)
        if resolved.is_dir():
            for dirpath, dirnames, filenames in os.walk(resolved, followlinks=False):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                for name in sorted(filenames):
                    candidate = Path(dirpath) / name
                    if name.startswith(".") or not is_media_candidate(candidate):
                        continue
                    try:
                        found.append(resolve_in_roots(candidate, roots))
                    except PathNotAllowedError:
                        continue
                    if len(found) > MAX_FOLDER_FILES:
                        raise InvalidInputError(
                            f"That folder has more than {MAX_FOLDER_FILES} media files. "
                            "Import a smaller folder."
                        )
        elif resolved.is_file():
            found.append(resolved)
        else:
            raise InvalidInputError(f"'{resolved.name}' does not exist.")
    return list(dict.fromkeys(found))


def media_dir(settings: Settings, project_id: str, asset_id: str) -> Path:
    return settings.project_dir(project_id) / "media" / asset_id


def _check_space(target: Path, needed: int) -> None:
    probe_dir = target
    while not probe_dir.exists():
        probe_dir = probe_dir.parent
    if shutil.disk_usage(probe_dir).free < needed + _MIN_FREE_BYTES:
        raise LowDiskSpaceError("There is not enough free disk space to import this file.")


def _existing(session: Session, project_id: str, digest: str) -> MediaAsset | None:
    return session.scalars(
        select(MediaAsset).where(
            MediaAsset.project_id == project_id, MediaAsset.content_hash == digest
        )
    ).first()


def _create_asset(
    session: Session,
    project_id: str,
    stored: Path,
    mode: str,
    asset_id: str | None = None,
    digest: str | None = None,
) -> tuple[MediaAsset, bool]:
    """Create the asset row for `stored` (or return the existing duplicate, by content hash)."""
    digest = digest or content_hash(stored)
    if (dup := _existing(session, project_id, digest)) is not None:
        return dup, True
    asset = MediaAsset(
        project_id=project_id,
        path=str(stored),
        filename=stored.name,
        content_hash=digest,
        import_mode=mode,
        size_bytes=stored.stat().st_size,
    )
    if asset_id:
        asset.id = asset_id
    session.add(asset)
    try:
        session.commit()
    except IntegrityError:  # lost a race with a concurrent import of the same file
        session.rollback()
        dup = _existing(session, project_id, digest)
        if dup is None:
            raise
        return dup, True
    return asset, False


def import_file(
    session: Session, settings: Settings, project_id: str, source: Path, mode: str
) -> ImportResult:
    """Register one already-validated path. `mode` is 'reference' or 'copy'."""
    result = ImportResult(path=str(source))
    digest = content_hash(source)
    if (dup := _existing(session, project_id, digest)) is not None:  # before any copying
        result.asset, result.duplicate = dup, True
        return result
    if mode == "reference":
        stored, asset_id = source, None
    else:
        asset_id = new_id()
        dest_dir = media_dir(settings, project_id, asset_id)
        try:
            _check_space(dest_dir, source.stat().st_size)
            stored = dest_dir / sanitize_filename(source.name)
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, stored)
        except BaseException:
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise
    asset, duplicate = _create_asset(session, project_id, stored, mode, asset_id, digest)
    if duplicate and mode == "copy":
        shutil.rmtree(stored.parent, ignore_errors=True)
    result.asset, result.duplicate = asset, duplicate
    return result


@dataclass
class UploadTarget:
    asset_id: str
    dir: Path
    path: Path
    limit: int


def prepare_upload(
    settings: Settings, project_id: str, filename: str, declared_size: int | None
) -> UploadTarget:
    """Validate an upload before any bytes are read: size limit, safe name, free space."""
    limit = settings.max_upload_mb * 1024 * 1024
    if declared_size is not None and declared_size > limit:
        raise upload_too_large(settings)
    safe = sanitize_filename(filename)
    asset_id = new_id()
    dest_dir = media_dir(settings, project_id, asset_id)
    _check_space(dest_dir, declared_size or 0)
    dest_dir.mkdir(parents=True, exist_ok=True)
    return UploadTarget(asset_id, dest_dir, dest_dir / safe, limit)


def upload_too_large(settings: Settings) -> PayloadTooLargeError:
    return PayloadTooLargeError(
        f"That file is larger than the {settings.max_upload_mb} MB upload limit. "
        "Use a media folder (reference import) for large footage."
    )


def finish_upload(
    session: Session, project_id: str, target: UploadTarget, written: int
) -> ImportResult:
    """Register a fully written upload; the caller removes `target.dir` if this raises."""
    if written == 0:
        raise InvalidInputError("The uploaded file is empty.")
    asset, duplicate = _create_asset(session, project_id, target.path, "upload", target.asset_id)
    if duplicate:
        shutil.rmtree(target.dir, ignore_errors=True)
    return ImportResult(path=target.path.name, asset=asset, duplicate=duplicate)


def enqueue_ingest(session: Session, settings: Settings, asset: MediaAsset) -> Job:
    """Queue the ingest chain for an asset unless one is already queued or running."""
    active = session.scalars(
        select(Job).where(
            Job.media_id == asset.id, Job.chain == "ingest", Job.status.in_(("queued", "running"))
        )
    ).first()
    if active is not None:
        return active
    return queue.enqueue(
        session,
        "ingest",
        project_id=asset.project_id,
        media_id=asset.id,
        params={
            "source": asset.path,
            "import_mode": asset.import_mode,
            "proxy_max_height": settings.proxy_max_height,
            "shot_detector": settings.shot_detector,
            "shot_threshold": settings.shot_threshold,
            "shot_min_len_s": settings.shot_min_len_s,
            "keyframes_per_shot": settings.keyframes_per_shot,
            "qc_detect": detector_params(settings.quality),
            "transcribe": transcribe_stages.job_params(settings),
        },
    )


def delete_asset_files(settings: Settings, asset: MediaAsset) -> None:
    """Remove derived data (and our own copy/upload). A referenced source is never touched."""
    root = settings.project_dir(asset.project_id)
    for rel in (asset.proxy_path, asset.poster_path, asset.strip_path, asset.waveform_path):
        if rel:
            (root / rel).unlink(missing_ok=True)
    shutil.rmtree(root / "keyframes" / asset.id, ignore_errors=True)
    if asset.import_mode != "reference":
        shutil.rmtree(media_dir(settings, asset.project_id, asset.id), ignore_errors=True)
