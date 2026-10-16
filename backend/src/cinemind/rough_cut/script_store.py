"""Storing a screenplay, aligning its dialogue with the project's transcripts, and the user's
choice of take per line (SPEC P1-A). The matching itself is `script_align.py`."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from cinemind.ai import embedder
from cinemind.core.config import Settings
from cinemind.core.errors import InvalidInputError, NotFoundError
from cinemind.core.transcribe_config import is_uncertain
from cinemind.db.models import MediaAsset, TranscriptSegment
from cinemind.db.script import ScriptDoc, ScriptLine, ScriptTake
from cinemind.rough_cut import script_align, script_parse
from cinemind.rough_cut.script_align import Embed, Place, Segment, Take
from cinemind.search.spoken import Word


def project_segments(session: Session, project_id: str) -> list[Segment]:
    """The project's transcript segments not marked uncertain, with their words."""
    query = (
        select(TranscriptSegment)
        .join(MediaAsset, MediaAsset.id == TranscriptSegment.media_id)
        .where(MediaAsset.project_id == project_id)
        .options(selectinload(TranscriptSegment.words))
    )
    found: list[Segment] = []
    for seg in session.scalars(query):
        if is_uncertain(seg.avg_logprob, seg.compression_ratio):
            continue
        words = tuple(Word(w.start_s, w.end_s, w.word) for w in seg.words)
        found.append(Segment(seg.id, seg.media_id, seg.start_s, seg.end_s, seg.text, words))
    return found


def text_embedder(settings: Settings) -> tuple[Embed | None, str | None]:
    """The meaning model when it is used (downloaded and given weight), else (None, None):
    words alone are compared."""
    spec = embedder.choose_text(settings)
    if settings.script.semantic_weight <= 0 or not spec.ready(settings.models_path):
        return None, None
    return (lambda texts: embedder.embed_texts(spec, settings, texts)), spec.key


def get_doc(session: Session, project_id: str) -> ScriptDoc:
    doc = session.scalar(select(ScriptDoc).where(ScriptDoc.project_id == project_id))
    if doc is None:
        raise NotFoundError("This project has no script yet. Paste or upload one first.")
    return doc


@dataclass
class _Alignment:
    takes: list[list[Take]]
    info: dict[str, Any]


def _align(
    session: Session,
    settings: Settings,
    project_id: str,
    texts: list[str],
    picked: list[Place | None],
) -> _Alignment:
    """All the slow work (reading transcripts, text vectors, matching), done before anything is
    written, so the database is not held while it runs."""
    cfg = settings.script
    segments = project_segments(session, project_id)
    embed, model = text_embedder(settings)
    takes = script_align.align(texts, segments, cfg, embed, picked)
    limit = cfg.limit(model is not None)
    return _Alignment(
        takes,
        {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "text_model": model,
            "semantic": model is not None,
            "settings": cfg.model_dump(),
            "limit": limit,
            "segments": len(segments),
            "dialogue_lines": len(texts),
            "found": sum(1 for t in takes if t and t[0].score >= limit),
        },
    )


def _key(character: str | None, text: str) -> tuple[str, str]:
    words = " ".join(w for w in (script_align.normalise(p) for p in text.split()) if w)
    return ((character or "").upper(), words)


def _picked(line: ScriptLine) -> Place | None:
    if line.choice != "take" or not line.picked_media_id:
        return None
    return (line.picked_media_id, line.picked_start_s or 0.0, line.picked_end_s or 0.0)


def _store_takes(line: ScriptLine, takes: list[Take]) -> None:
    line.takes = [  # the old rows go with delete-orphan
        ScriptTake(
            media_id=t.media_id,
            rank=rank,
            start_s=t.start_s,
            end_s=t.end_s,
            text=t.text,
            lexical=t.lexical,
            semantic=t.semantic,
            score=t.score,
            segment_ids=list(t.segment_ids),
        )
        for rank, t in enumerate(takes, start=1)
    ]


def save(session: Session, settings: Settings, project_id: str, name: str, text: str) -> ScriptDoc:
    """Replace the project's script with this one and align it. Choices made for lines that
    are unchanged in the new script (same character, same words) are kept. The caller commits."""
    fmt, parsed = script_parse.parse(text)
    old = session.scalar(select(ScriptDoc).where(ScriptDoc.project_id == project_id))
    previous: dict[tuple[str, str], ScriptLine] = {}
    if old is not None:
        for line in old.lines:
            if line.kind == "dialogue" and line.choice != "auto":
                previous.setdefault(_key(line.character, line.text), line)
    lines = [
        ScriptLine(
            index=index,
            kind=p.kind,
            character=p.character[:100] if p.character else None,
            scene=p.scene[:300] if p.scene else None,
            text=p.text,
            choice="auto",
        )
        for index, p in enumerate(parsed)
    ]
    dialogue = [line for line in lines if line.kind == "dialogue"]
    for line in dialogue:
        kept = previous.get(_key(line.character, line.text))
        if kept is not None:
            line.choice = kept.choice
            line.picked_media_id = kept.picked_media_id
            line.picked_start_s, line.picked_end_s = kept.picked_start_s, kept.picked_end_s
    found = _align(
        session,
        settings,
        project_id,
        [ln.text for ln in dialogue],
        [_picked(ln) for ln in dialogue],
    )
    # Writing starts here: one short transaction, committed by the caller.
    if old is not None:
        session.delete(old)
        session.flush()
    doc = ScriptDoc(project_id=project_id, name=name, format=fmt, text=text, alignment=found.info)
    doc.lines = lines
    for line, takes in zip(dialogue, found.takes, strict=True):
        _store_takes(line, takes)
    session.add(doc)
    return doc


def align_doc(session: Session, settings: Settings, doc: ScriptDoc) -> None:
    """Find every dialogue line in the transcripts again (after new footage was processed).
    The user's choices stay: a picked take is kept by its place in the footage."""
    dialogue = [line for line in doc.lines if line.kind == "dialogue"]
    found = _align(
        session,
        settings,
        doc.project_id,
        [line.text for line in dialogue],
        [_picked(line) for line in dialogue],
    )
    for line, takes in zip(dialogue, found.takes, strict=True):
        _store_takes(line, takes)
    doc.alignment = found.info


def limit_of(settings: Settings, doc: ScriptDoc) -> float:
    """The match limit for this script's last alignment (with or without the text model)."""
    return settings.script.limit(bool(doc.alignment.get("semantic")))


def chosen(line: ScriptLine, min_score: float) -> tuple[ScriptTake | None, str]:
    """The take used for the line and why: the user's pick, the best take at or above the limit,
    or none (not filmed, nothing found, the picked take no longer found)."""
    if line.choice == "not_filmed":
        return None, "marked not filmed by you"
    if line.choice == "take":
        for take in line.takes:
            if take.media_id == line.picked_media_id and _overlap(take, line):
                return take, "chosen by you"
        return None, "the take you chose is no longer found; choose again"
    if line.takes and line.takes[0].score >= min_score:
        return line.takes[0], "best match"
    if line.takes:
        return None, f"no take reached the match limit {min_score:g}"
    return None, "not found in any transcript"


def _overlap(take: ScriptTake, line: ScriptLine) -> bool:
    start, end = line.picked_start_s or 0.0, line.picked_end_s or 0.0
    return min(take.end_s, end) - max(take.start_s, start) > 0


def choose(session: Session, line_id: str, take_id: str | None, not_filmed: bool) -> ScriptLine:
    """Set a line's take: a take id, "not filmed", or neither (back to the best match)."""
    line = session.get(ScriptLine, line_id)
    if line is None or line.kind != "dialogue":
        raise NotFoundError("That script line does not exist any more. Reload the script.")
    if take_id and not_filmed:
        raise InvalidInputError("Choose a take or mark the line as not filmed, not both.")
    if take_id:
        take = next((t for t in line.takes if t.id == take_id), None)
        if take is None:
            raise NotFoundError("That take is not one of this line's takes. Reload the script.")
        line.choice = "take"
        line.picked_media_id, line.picked_start_s, line.picked_end_s = (
            take.media_id,
            take.start_s,
            take.end_s,
        )
    else:
        line.choice = "not_filmed" if not_filmed else "auto"
        line.picked_media_id = line.picked_start_s = line.picked_end_s = None
    return line


def summary(doc: ScriptDoc, min_score: float) -> dict[str, Any]:
    dialogue = [line for line in doc.lines if line.kind == "dialogue"]
    used = sum(1 for line in dialogue if chosen(line, min_score)[0] is not None)
    return {"dialogue_lines": len(dialogue), "with_take": used}
