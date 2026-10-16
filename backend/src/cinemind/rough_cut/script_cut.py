"""The script-ordered assembly (SPEC P1-A): every dialogue line's chosen take, in script order,
as a timeline the editor opens like any rough cut. A take is cut to its words plus the rough
cut's `speech_pad_s`; consecutive lines taken from one continuous stretch of a clip become one
clip (no cut in the middle of a running take)."""

import time
from collections import Counter
from fractions import Fraction
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemind.core.config import Settings
from cinemind.core.errors import InvalidInputError
from cinemind.db.models import MediaAsset, Timeline, TimelineItem
from cinemind.export.sequence import export_rate
from cinemind.rough_cut import BANNER
from cinemind.rough_cut.assembly import check_rate, frame_size
from cinemind.rough_cut.script_store import chosen, get_doc, limit_of
from cinemind.search.retrievers import Shots

# Lines whose takes are this close in one clip play as one clip.
JOIN_GAP_S = 0.5


def _score_text(take: Any) -> str:
    parts = f"words {take.lexical:.2f}"
    if take.semantic is not None:
        parts += f", meaning {take.semantic:.2f}"
    return f"match {take.score:.2f} ({parts})"


def build_script_cut(
    session: Session,
    settings: Settings,
    project_id: str,
    name: str | None = None,
    fps: Fraction | None = None,
) -> Timeline:
    began = time.perf_counter()
    check_rate(fps)
    doc = get_doc(session, project_id)
    limit = limit_of(settings, doc)
    pad = settings.rough_cut.speech_pad_s
    dialogue = [line for line in doc.lines if line.kind == "dialogue"]
    ids = {t.media_id for line in dialogue for t in line.takes}
    assets = {a.id: a for a in session.scalars(select(MediaAsset).where(MediaAsset.id.in_(ids)))}
    clips: list[dict[str, Any]] = []
    left_out: list[dict[str, Any]] = []
    for number, line in enumerate(dialogue, start=1):
        take, why = chosen(line, limit)
        asset = assets.get(take.media_id) if take else None
        label = f"{line.character}: " if line.character else ""
        if take is None or asset is None:
            left_out.append({"line": number, "text": f"{label}{line.text}", "why": why})
            continue
        in_s = max(0.0, take.start_s - pad)
        out_s = min(asset.duration_s or take.end_s + pad, take.end_s + pad)
        entry = {
            "line": number,
            "character": line.character,
            "text": line.text,
            "heard": take.text,
            "take": take.rank,
            "takes": len(line.takes),
            "score": take.score,
            "lexical": take.lexical,
            "semantic": take.semantic,
            "why": why,
        }
        last = clips[-1] if clips else None
        if (
            last
            and last["asset"].id == asset.id
            and last["in_s"] <= in_s <= last["out_s"] + JOIN_GAP_S
        ):
            last["out_s"] = max(last["out_s"], out_s)
            last["lines"].append(entry)
            continue
        summary = (
            f"Script line {number}{f' ({line.character})' if line.character else ''}: take "
            f"{take.rank} of {len(line.takes)}, {_score_text(take)}; {why}."
        )
        clips.append(
            {
                "asset": asset,
                "in_s": in_s,
                "out_s": out_s,
                "take_start_s": take.start_s,
                "lines": [entry],
                "summary": summary,
            }
        )
    if not clips:
        raise InvalidInputError(
            "No script line has a take yet. Process the footage with speech first, or choose "
            "takes on the Script page."
        )
    votes = Counter(export_rate(c["asset"]) for c in clips)
    rate = fps or max(votes, key=lambda r: (votes[r], r))
    width, height = frame_size([c["asset"] for c in clips])
    timeline = Timeline(
        project_id=project_id,
        name=(name or "").strip() or f"Script assembly: {doc.name}"[:200],
        kind="script_cut",
        fps_num=rate.numerator,
        fps_den=rate.denominator,
        width=width,
        height=height,
        params={
            "banner": BANNER,
            "script": doc.name,
            "order": "script",
            "dialogue_lines": len(dialogue),
            "lines_used": len(dialogue) - len(left_out),
            "left_out_lines": left_out,
            "alignment": doc.alignment,
            "pad_s": pad,
            "rate_chosen_by": "user" if fps else "most common rate among the chosen takes",
            "built_items": len(clips),
            "built_s": round(time.perf_counter() - began, 3),
        },
    )
    shots = Shots(session, project_id)  # the shot a take starts in: its keyframe and scene
    for position, c in enumerate(clips):
        lines = c["lines"]
        timeline.items.append(
            TimelineItem(
                position=position,
                media_id=c["asset"].id,
                shot_id=shots.at(c["asset"].id, c["take_start_s"]),
                source_in_s=c["in_s"],
                source_out_s=c["out_s"],
                reason={
                    "summary": c["summary"]
                    + (f" Plays {len(lines)} lines." if len(lines) > 1 else ""),
                    "script_lines": lines,
                    "matched_line": lines[0]["heard"],
                    "trim": {
                        "how": "script",
                        "detail": f"the words of the take with {pad:g} s of room",
                        "lines": [entry["heard"] for entry in lines],
                    },
                },
            )
        )
    session.add(timeline)
    session.commit()
    return timeline
