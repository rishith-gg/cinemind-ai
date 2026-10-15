"""Changes the editor makes to a stored timeline: rename, reorder, trim, remove (one PATCH with
the new item list) and swap a clip for a suggested alternative. Source footage is never touched;
only the timeline rows change."""

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemind.core.config import Settings
from cinemind.core.errors import InvalidInputError, NotFoundError
from cinemind.db.models import MediaAsset, Shot, Timeline, TimelineItem
from cinemind.rough_cut.trim import trim_shot
from cinemind.search.spoken import spoken_lines
from cinemind.utils.timecode import seconds_to_frames

# The editor's chosen shot may be this short (two frames at 50 fps) in a swap.
MIN_SWAP_S = 0.04


@dataclass
class ItemEdit:
    id: str
    source_in_s: float
    source_out_s: float


def _suggest_again(
    session: Session, alternatives: list[dict[str, Any]], items: list[TimelineItem]
) -> None:
    """Put clips taken off the timeline back first among the suggestions, with their reason.
    Only clips the rough cut chose (they have a search rank); shots the editor picked are not."""
    for item in reversed(items):
        if not (item.shot_id and item.reason and "rank" in item.reason):
            continue
        if any(a["shot_id"] == item.shot_id for a in alternatives):
            continue
        asset = session.get(MediaAsset, item.media_id)
        filename = asset.filename if asset else ""
        reason = {k: v for k, v in item.reason.items() if k != "auto_trim"}
        reason["trim"] = item.reason.get("auto_trim", reason.get("trim"))
        alternatives.insert(
            0,
            {"shot_id": item.shot_id, "filename": filename, "reason": reason},
        )


def _check(e: ItemEdit, rate: Fraction, length: float | None) -> None:
    if not (math.isfinite(e.source_in_s) and math.isfinite(e.source_out_s)):
        raise InvalidInputError("In and out points must be numbers of seconds.")
    if e.source_in_s < 0 or e.source_out_s <= e.source_in_s:
        raise InvalidInputError("A clip must start at 0 or later and end after it starts.")
    if seconds_to_frames(e.source_out_s, rate) - seconds_to_frames(e.source_in_s, rate) < 1:
        raise InvalidInputError("A clip must be at least one frame long.")
    if length is not None and e.source_out_s > length + 1e-3:
        raise InvalidInputError(f"A clip cannot end after its file does ({length:.2f} s).")


def edit(
    session: Session, timeline: Timeline, name: str | None, items: list[ItemEdit] | None
) -> None:
    """Apply a rename and/or the new item list: listed items in this order with these in/out
    points, items not listed removed (and offered again as suggestions). A clip whose in or out
    point changed is marked as trimmed by the editor. The caller commits."""
    if name is not None:
        timeline.name = name
    if items is None:
        return
    current = {item.id: item for item in timeline.items}
    ids = [e.id for e in items]
    kept = set(ids)
    if len(kept) != len(ids):
        raise InvalidInputError("A clip is listed twice. Reload the timeline and try again.")
    if any(i not in current for i in ids):
        raise InvalidInputError(
            "Some clips are not on this timeline any more. Reload the timeline and try again."
        )
    durations = dict(
        session.execute(
            select(MediaAsset.id, MediaAsset.duration_s).where(
                MediaAsset.id.in_({current[i].media_id for i in ids})
            )
        ).all()
    )
    rate = Fraction(timeline.fps_num, timeline.fps_den)
    for e in items:
        _check(e, rate, durations.get(current[e.id].media_id))
    removed = [item for item in timeline.items if item.id not in kept]
    alternatives: list[dict[str, Any]] = list(timeline.params.get("alternatives", []))
    _suggest_again(session, alternatives, removed)
    for item in removed:
        timeline.items.remove(item)
    for position, e in enumerate(items):
        item = current[e.id]
        item.position = position
        moved = (item.source_in_s, item.source_out_s) != (e.source_in_s, e.source_out_s)
        if moved and item.reason is not None:
            auto = item.reason.get("auto_trim", item.reason.get("trim"))
            item.reason = {
                **item.reason,
                "auto_trim": auto,
                "trim": {"how": "by you", "detail": "in and out points set by you", "lines": []},
            }
        item.source_in_s = e.source_in_s
        item.source_out_s = e.source_out_s
    timeline.items.sort(key=lambda i: i.position)
    # The "clips removed from the project" warning counts against this; the editor's own
    # removals are not that.
    timeline.params = {
        **timeline.params,
        "alternatives": alternatives,
        "built_items": len(items),
        "edited": True,
    }


def swap(
    session: Session, settings: Settings, timeline: Timeline, item_id: str, shot_id: str
) -> TimelineItem:
    """Put `shot_id` in place of the item, trimmed with the rough cut rules. The clip taken out
    becomes a suggestion in its turn. The caller commits."""
    item = next((i for i in timeline.items if i.id == item_id), None)
    if item is None:
        raise NotFoundError("That clip is not on this timeline any more. Reload the timeline.")
    shot = session.get(Shot, shot_id)
    asset = session.get(MediaAsset, shot.media_id) if shot else None
    if shot is None or asset is None or asset.project_id != timeline.project_id:
        raise NotFoundError("That shot does not exist in this project any more.")
    if any(i.shot_id == shot_id for i in timeline.items if i.id != item_id):
        raise InvalidInputError("That shot is already on the timeline.")
    alternatives: list[dict[str, Any]] = list(timeline.params.get("alternatives", []))
    entry = next((a for a in alternatives if a["shot_id"] == shot_id), None)
    reason: dict[str, Any] = dict(entry["reason"]) if entry else {"summary": "Chosen by you."}
    jump = float(reason.get("jump_s", (shot.start_s + shot.end_s) / 2))
    lines = spoken_lines(session, {asset.id}).get(asset.id, [])
    # The editor chose this shot, so the minimum length of an automatic pick does not apply.
    cfg = settings.rough_cut.model_copy(
        update={"min_clip_s": min(settings.rough_cut.min_clip_s, MIN_SWAP_S)}
    )
    trim = trim_shot(shot.start_s, shot.end_s, jump, lines, cfg)
    if trim is None:
        raise InvalidInputError("That shot is too short to use.")
    reason["trim"] = trim.as_dict()
    alternatives = [a for a in alternatives if a["shot_id"] != shot_id]
    _suggest_again(session, alternatives, [item])
    item.media_id = asset.id
    item.shot_id = shot.id
    item.source_in_s = trim.in_s
    item.source_out_s = trim.out_s
    item.reason = reason
    timeline.params = {**timeline.params, "alternatives": alternatives, "edited": True}
    return item
