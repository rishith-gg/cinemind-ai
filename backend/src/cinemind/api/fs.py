"""Server-side folder browser, limited to the approved media roots."""

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from cinemind.api.deps import SettingsDep
from cinemind.api.schemas import ErrorResponse, FsEntry, FsListing
from cinemind.core.errors import InvalidInputError, PathNotAllowedError
from cinemind.core.paths import resolve_in_roots
from cinemind.pipeline import importer

router = APIRouter(tags=["media"])
_ERR: dict[int | str, dict[str, Any]] = {
    403: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}
_MAX_LISTING = 1000


@router.get("/api/fs/browse", response_model=FsListing, responses=_ERR, operation_id="browseFolder")
def browse(settings: SettingsDep, path: str | None = None) -> FsListing:
    """List a folder inside the approved media roots. Without `path`, lists the roots."""
    roots = [r.resolve() for r in settings.media_roots if r.is_dir()]
    root_strs = [str(r) for r in roots]
    if path is None:
        entries = [
            FsEntry(
                name=r.name or str(r),
                path=str(r),
                is_dir=True,
                size_bytes=None,
                is_media_candidate=False,
            )
            for r in roots
        ]
        return FsListing(path=None, parent=None, roots=root_strs, entries=entries)
    if not Path(path).is_absolute():
        raise InvalidInputError("Folder paths must be absolute.")
    folder = resolve_in_roots(path, roots)
    if not folder.is_dir():
        raise InvalidInputError("That is not a folder.")
    entries: list[FsEntry] = []
    with os.scandir(folder) as it:
        for entry in sorted(it, key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.name.startswith(".") or len(entries) >= _MAX_LISTING:
                continue
            try:
                real = resolve_in_roots(entry.path, roots)  # links leaving the roots are hidden
                is_dir = real.is_dir()
                size = None if is_dir else real.stat().st_size
            except (PathNotAllowedError, OSError):
                continue
            entries.append(
                FsEntry(
                    name=entry.name,
                    path=str(real),
                    is_dir=is_dir,
                    size_bytes=size,
                    is_media_candidate=not is_dir and importer.is_media_candidate(real),
                )
            )
    parent = None if folder in roots else str(folder.parent)
    return FsListing(path=str(folder), parent=parent, roots=root_strs, entries=entries)
