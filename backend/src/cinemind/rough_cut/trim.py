"""Where a chosen shot is cut in and out (SPEC section 11, "trim in/out, speech-aware when
dialogue"). Pure functions on seconds, so the rules are tested without footage.

- A shot with transcript lines (only lines not marked uncertain) keeps whole lines: the line at
  or nearest the moment that matched, then its closest neighbours while the clip stays within
  `max_speech_clip_s`, with `speech_pad_s` of room before and after. A line is never cut in the
  middle by the trim (only by the shot's own edge, which the note says).
- A shot without speech keeps at most `max_clip_s` centred on the moment that matched (a word, a
  line, the best keyframe), so the part that answered the brief is in the cut.
- Shots shorter than `min_clip_s` are not used.
These rules are our conventions; the numbers are `[rough_cut]` settings.
"""

from dataclasses import dataclass, field
from typing import Literal

from cinemind.core.rough_cut_config import RoughCutConfig
from cinemind.search.spoken import SpokenLine as Line

How = Literal["speech", "around match", "whole shot"]


@dataclass
class Trim:
    in_s: float
    out_s: float
    how: How
    detail: str
    lines: list[str] = field(default_factory=lambda: [])

    @property
    def length(self) -> float:
        return self.out_s - self.in_s

    def as_dict(self) -> dict[str, object]:
        return {"how": self.how, "detail": self.detail, "lines": self.lines}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _window(start: float, end: float, centre: float, length: float) -> tuple[float, float]:
    """`length` seconds inside [start, end], centred on `centre` as far as the edges allow."""
    length = min(length, end - start)
    first = _clamp(centre - length / 2, start, end - length)
    return first, first + length


def _speech(
    start: float, end: float, jump: float, lines: list[Line], cfg: RoughCutConfig, cap: float
) -> Trim:
    """Whole lines around the anchor; neighbours are added while the clip stays within `cap`."""

    def span(a: int, b: int) -> float:
        return (lines[b].end_s + cfg.speech_pad_s) - (lines[a].start_s - cfg.speech_pad_s)

    anchor = min(
        range(len(lines)),
        key=lambda i: (0.0 if lines[i].start_s <= jump <= lines[i].end_s
                       else min(abs(lines[i].start_s - jump), abs(lines[i].end_s - jump)), i),
    )  # fmt: skip
    first = last = anchor
    while True:
        options: list[tuple[float, int, int]] = []
        if first > 0 and span(first - 1, last) <= cap:
            options.append((lines[first].start_s - lines[first - 1].end_s, first - 1, last))
        if last < len(lines) - 1 and span(first, last + 1) <= cap:
            options.append((lines[last + 1].start_s - lines[last].end_s, first, last + 1))
        if not options:
            break
        _, first, last = min(options)
    in_s = max(start, lines[first].start_s - cfg.speech_pad_s)
    out_s = min(end, lines[last].end_s + cfg.speech_pad_s)
    if out_s - in_s < cfg.min_clip_s:
        in_s, out_s = _window(start, end, (in_s + out_s) / 2, cfg.min_clip_s)
    kept = lines[first : last + 1]
    detail = f"keeps {len(kept)} whole spoken line(s) with {cfg.speech_pad_s:g} s of room"
    if lines[first].start_s < start or lines[last].end_s > end:
        detail += "; a line runs past the shot's edge and is cut there"
    if len(kept) < len(lines):
        detail += f"; {len(lines) - len(kept)} other line(s) in the shot left out"
    if span(first, last) > cfg.max_speech_clip_s:
        detail += f"; one line is longer than {cfg.max_speech_clip_s:g} s and is kept whole"
    return Trim(in_s, out_s, "speech", detail, [line.text for line in kept])


def trim_shot(
    start: float,
    end: float,
    jump: float,
    lines: list[Line],
    cfg: RoughCutConfig,
    limit: float | None = None,
) -> Trim | None:
    """The clip to use from the shot [start, end), or None when the shot is too short or
    cannot fit in `limit` seconds. A clip with speech fits by keeping fewer whole lines, never
    by cutting one; when even the line that matched is too long, None."""
    if end - start < cfg.min_clip_s:
        return None
    jump = _clamp(jump, start, end)
    inside = sorted(
        (line for line in lines if line.end_s > start and line.start_s < end),
        key=lambda line: line.start_s,
    )
    if inside:
        cap = cfg.max_speech_clip_s if limit is None else min(cfg.max_speech_clip_s, limit)
        trim = _speech(start, end, jump, inside, cfg, cap)
        return trim if limit is None or trim.length <= limit + 1e-6 else None
    length = cfg.max_clip_s if limit is None else min(cfg.max_clip_s, limit)
    if length < cfg.min_clip_s:
        return None
    if end - start <= length:
        return Trim(start, end, "whole shot", "the whole shot (no speech)")
    in_s, out_s = _window(start, end, jump, length)
    return Trim(
        in_s, out_s, "around match", f"{length:g} s around the moment that matched (no speech)"
    )
