"""Write a stored timeline to an exchange file under the project's `exports/` folder."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemind.core.config import Settings
from cinemind.core.errors import ExportWriteError, InvalidInputError
from cinemind.core.paths import sanitize_filename
from cinemind.db.models import MediaAsset, Timeline
from cinemind.export.edl import write_edl
from cinemind.export.fcp7xml import write_fcp7xml
from cinemind.export.otio_model import write_otio
from cinemind.export.sequence import Sequence, build_sequence
from cinemind.export.srt import write_srt
from cinemind.search.spoken import SpokenLine, spoken_lines

log = logging.getLogger(__name__)

ExportFormat = Literal["fcp7xml", "edl", "otio", "srt"]
EXTENSIONS: dict[str, str] = {"fcp7xml": ".xml", "edl": ".edl", "otio": ".otio", "srt": ".srt"}
MEDIA_TYPES: dict[str, str] = {
    "fcp7xml": "application/xml",
    "edl": "text/plain",
    "otio": "application/json",
    "srt": "application/x-subrip",
}
UNKNOWN_FORMAT = "Unknown export format '{}'. Use fcp7xml, edl, otio or srt."


@dataclass(frozen=True)
class ExportedFile:
    path: Path
    filename: str
    media_type: str


def load_sequence(session: Session, timeline: Timeline) -> Sequence:
    ids = {item.media_id for item in timeline.items}
    assets = session.scalars(select(MediaAsset).where(MediaAsset.id.in_(ids)))
    return build_sequence(timeline, {a.id: a for a in assets})


def render(seq: Sequence, fmt: str, lines: dict[str, list[SpokenLine]] | None = None) -> str:
    if fmt == "fcp7xml":
        return write_fcp7xml(seq)
    if fmt == "edl":
        return write_edl(seq)
    if fmt == "otio":
        return write_otio(seq)
    if fmt == "srt":
        text = write_srt(seq, lines or {})
        if not text:
            raise InvalidInputError(
                "No transcript line falls inside this timeline's clips, so there are no "
                "subtitles to write. Lines marked uncertain are never used."
            )
        return text
    raise InvalidInputError(UNKNOWN_FORMAT.format(fmt))


def export_dir(settings: Settings, timeline: Timeline) -> Path:
    return settings.project_dir(timeline.project_id) / "exports"


def file_stem(name: str) -> str:
    """A single safe path component for a timeline name (dots kept out so nothing reads as an
    extension); names without any file-safe character become 'timeline'."""
    try:
        return sanitize_filename(name.replace(".", "_"), max_length=80)
    except InvalidInputError:
        return "timeline"


def export_timeline(
    session: Session, settings: Settings, timeline: Timeline, fmt: str
) -> ExportedFile:
    seq = load_sequence(session, timeline)
    if not seq.cuts:
        if timeline.params.get("edited") and not timeline.items:
            raise InvalidInputError(
                "This timeline has no clips. Add clips back or build a new rough cut."
            )
        raise InvalidInputError("This timeline is empty; its clips were removed from the project.")
    lines = spoken_lines(session, {c.source.media_id for c in seq.cuts}) if fmt == "srt" else None
    text = render(seq, fmt, lines)
    filename = f"{file_stem(timeline.name)}_{timeline.id[:8]}{EXTENSIONS[fmt]}"
    folder = export_dir(settings, timeline)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / (filename + ".partial")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(folder / filename)
    except OSError as exc:
        log.warning("could not write %s: %s", folder / filename, exc)
        raise ExportWriteError(
            f"The export file could not be written to {folder} ({exc.strerror}). "
            "Check free disk space and folder permissions."
        ) from exc
    return ExportedFile(folder / filename, filename, MEDIA_TYPES[fmt])
