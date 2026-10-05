"""Path safety: media must live inside user-approved roots; filenames are sanitized."""

import re
import unicodedata
from collections.abc import Sequence
from pathlib import Path

from cinemind.core.errors import InvalidInputError, PathNotAllowedError

_PROJECT_ID = re.compile(r"^[0-9a-f]{32}$")
_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def sanitize_filename(name: str, max_length: int = 120) -> str:
    """Return a safe single path component (no separators, no leading dots, never empty)."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    base = _UNSAFE.sub("_", base).strip(" .")
    if not base:
        raise InvalidInputError("The file name is empty or has no usable characters.")
    if len(base) > max_length:
        stem, dot, ext = base.rpartition(".")
        if dot and len(ext) < 16:
            base = stem[: max_length - len(ext) - 1] + "." + ext
        else:
            base = base[:max_length]
    return base


def validate_project_id(project_id: str) -> str:
    """Project ids are 32 hex chars; anything else must never reach the filesystem."""
    if not _PROJECT_ID.fullmatch(project_id):
        raise InvalidInputError("Invalid project id.")
    return project_id


def resolve_in_roots(path: str | Path, roots: Sequence[Path]) -> Path:
    """Resolve `path` (following symlinks) and require it to be inside an approved root."""
    raw = Path(path)
    if ".." in raw.parts:
        raise PathNotAllowedError("Paths containing '..' are not allowed.")
    if not roots:
        raise PathNotAllowedError(
            "No media folders are approved yet. Add one to media_roots in cinemind.toml."
        )
    try:
        resolved = raw.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise PathNotAllowedError("That path could not be resolved.") from exc
    for root in roots:
        if resolved.is_relative_to(root.resolve()):
            return resolved
    raise PathNotAllowedError("That path is outside the approved media folders.")
