"""Re-read exported files with OpenTimelineIO's own adapters (an independent parser)."""
# opentimelineio ships no type stubs.
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import opentimelineio as otio

ADAPTERS = {"fcp7xml": "fcp_xml", "edl": "cmx_3600", "otio": "otio_json"}


@dataclass(frozen=True)
class ReadClip:
    name: str
    source_start: int  # frames, including the file's start timecode
    duration: int
    record: int
    url: str | None
    exact: bool  # every time above was read as a whole number of frames


@dataclass(frozen=True)
class ReadTimeline:
    name: str
    start: int
    video: list[ReadClip]
    audio: list[list[ReadClip]]


def _value(time: Any, rate: Fraction) -> float:
    return float(time.rescaled_to(float(rate)).value)


def _on_grid(*values: float) -> bool:
    return all(abs(v - round(v)) < 1e-6 for v in values)


def _clips(track: Any, rate: Fraction) -> list[ReadClip]:
    found: list[ReadClip] = []
    for child in track:
        if not isinstance(child, otio.schema.Clip):
            continue
        start = _value(child.source_range.start_time, rate)
        duration = _value(child.source_range.duration, rate)
        record = _value(child.range_in_parent().start_time, rate)
        found.append(
            ReadClip(
                name=child.name,
                source_start=round(start),
                duration=round(duration),
                record=round(record),
                url=getattr(child.media_reference, "target_url", None),
                exact=_on_grid(start, duration, record),
            )
        )
    return found


def read(text: str, fmt: str, rate: Fraction) -> ReadTimeline:
    if fmt == "edl":
        timeline = otio.adapters.read_from_string(text, ADAPTERS[fmt], rate=float(rate))
    else:
        timeline = otio.adapters.read_from_string(text, ADAPTERS[fmt])
    start = timeline.global_start_time
    return ReadTimeline(
        name=timeline.name,
        start=round(_value(start, rate)) if start is not None else 0,
        video=[c for t in timeline.video_tracks() for c in _clips(t, rate)],
        audio=[_clips(t, rate) for t in timeline.audio_tracks()],
    )
