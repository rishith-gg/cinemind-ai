"""SubRip (.srt) subtitles for a timeline: the transcript words that fall inside each cut, placed
at the cut's position on the timeline. Only lines not marked uncertain are used (D-084), so a
subtitle never shows words the model was unsure it heard. Times count from the start of the
timeline (00:00:00,000), not from its 01:00:00:00 timecode."""

from fractions import Fraction

from cinemind.export.sequence import Sequence
from cinemind.search.spoken import SpokenLine

# Pieces of a line clipped by a cut shorter than this are dropped (they flash unreadably); a
# whole short line ("Yes.") is kept.
MIN_SUBTITLE_S = 0.3


def _stamp(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    hours, rest = divmod(ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def subtitles(seq: Sequence, lines: dict[str, list[SpokenLine]]) -> list[tuple[float, float, str]]:
    """(start, end, text) on the timeline for every line, or part of a line, inside a cut."""
    found: list[tuple[float, float, str]] = []
    for cut in seq.cuts:
        src_in = float(cut.src_in_s)
        src_out = float(cut.src_in_s + Fraction(cut.duration) / cut.rate)
        record = float(Fraction(cut.record) / cut.rate)
        for line in lines.get(cut.source.media_id, []):
            if line.end_s <= src_in or line.start_s >= src_out:
                continue
            dropped = False
            if line.words:  # the words whose middle lies inside the cut
                inside = [w for w in line.words if src_in <= (w.start_s + w.end_s) / 2 < src_out]
                if not inside:
                    continue
                start, end = inside[0].start_s, inside[-1].end_s
                text = " ".join(w.text.strip() for w in inside)
                dropped = len(inside) < len(line.words)
            else:
                start, end, text = line.start_s, line.end_s, line.text
            clipped = dropped or start < src_in or end > src_out
            start, end = max(start, src_in), min(end, src_out)
            if (end - start >= MIN_SUBTITLE_S or not clipped) and end > start and text.strip():
                found.append(
                    (record + start - src_in, record + end - src_in, " ".join(text.split()))
                )
    return found


def write_srt(seq: Sequence, lines: dict[str, list[SpokenLine]]) -> str:
    blocks = [
        f"{number}\n{_stamp(start)} --> {_stamp(end)}\n{text}\n"
        for number, (start, end, text) in enumerate(subtitles(seq, lines), start=1)
    ]
    return "\n".join(blocks)
