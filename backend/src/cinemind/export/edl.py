"""CMX3600 EDL writer: cuts only, one video track with its audio. The simplest hand-off format.

File-based footage has no tape reel, so events use the conventional reel `AX` and carry the
clip name in a `* FROM CLIP NAME:` comment, which NLEs use to find the media. All timecodes are
on the timeline's rate; an EDL cannot describe sources at another rate.
"""

from cinemind.core.errors import InvalidInputError
from cinemind.export.sequence import Sequence, source_start
from cinemind.utils.timecode import frames_to_tc

REEL = "AX"
MAX_EVENTS = 999  # three-digit event numbers
MAX_TIMEBASE = 60  # two-digit frame field


def write_edl(seq: Sequence) -> str:
    if round(seq.rate) > MAX_TIMEBASE:
        raise InvalidInputError(
            "An EDL cannot describe timelines above 60 fps. Use FCP7 XML or OTIO for this one."
        )
    if len(seq.cuts) > MAX_EVENTS:
        raise InvalidInputError(
            f"An EDL holds at most {MAX_EVENTS} cuts; this timeline has {len(seq.cuts)}. "
            "Use FCP7 XML or OTIO."
        )
    lines = [f"TITLE: {' '.join(seq.name.split())[:70]}", "FCM: NON-DROP FRAME", ""]
    for number, cut in enumerate(seq.cuts, start=1):
        src = cut.source
        drop = src.drop and not cut.mixed_rate
        start = source_start(cut)
        src_in = frames_to_tc(start, seq.rate, drop)
        src_out = frames_to_tc(start + cut.duration, seq.rate, drop)
        rec_in = frames_to_tc(seq.start_frame + cut.record, seq.rate)
        rec_out = frames_to_tc(seq.start_frame + cut.record + cut.duration, seq.rate)
        # CMX3600 channel codes: AA/V = video + audio 1 and 2, B = video + audio 1, V = video only
        channels = "AA/V" if src.channels >= 2 else "B" if src.channels == 1 else "V"
        lines.append(
            f"{number:03d}  {REEL:<8} {channels:<5} C        {src_in} {src_out} {rec_in} {rec_out}"
        )
        lines.append(f"* FROM CLIP NAME: {src.name}")
        lines.append(f"* SOURCE FILE: {src.path}")
        # Comments follow an event: a comment before the first event breaks some readers
        # (OpenTimelineIO's included), so the banner goes under event 001.
        if seq.banner and number == 1:
            lines.append(f"* {seq.banner}")
        if cut.note:
            lines.append(f"* WHY: {' '.join(cut.note.split())}")
    return "\n".join(lines) + "\n"
