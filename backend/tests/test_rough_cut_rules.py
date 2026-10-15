"""The rough cut's rules without footage: reading a brief and trimming a shot."""

from types import SimpleNamespace
from typing import Any, cast

import pytest

from cinemind.core.rough_cut_config import RoughCutConfig
from cinemind.rough_cut.assembly import frame_size
from cinemind.rough_cut.brief import parse
from cinemind.rough_cut.trim import trim_shot
from cinemind.search.spoken import SpokenLine as Line

CFG = RoughCutConfig()


@pytest.mark.parametrize(
    ("text", "target", "order", "query"),
    [
        (
            "2-minute sequence about the grandfather walking home at night",
            120,
            None,
            "the grandfather walking home at night",
        ),
        (
            "A 90 second montage of people at the beach, best first",
            90,
            "score",
            "people at the beach",
        ),
        ("1:30 forest walk by scene", 90, "scene", "forest walk"),
        ("one minute of the city in order", 60, "chronological", "the city"),
        ("1 minute 30 seconds of dogs", 90, None, "dogs"),
        ("half a minute of rain", 30, None, "rain"),
        ("make a short video of the temple", None, None, "the temple"),
        ("person walking", None, None, "person walking"),
        ("30 sec", 30, None, ""),
        # Not lengths: a decade, a year, a time of day, a single letter unit.
        ("footage from the 90s", None, None, "footage from the 90s"),
        ("the 1990s family", None, None, "the 1990s family"),
        ("walking home at 9:30", None, None, "walking home at 9:30"),
        ("30s", None, None, "30s"),
        ("1:30 long forest", 90, None, "forest"),
        # Only the first length counts; the second describes the shots.
        ("a 2 minute cut of 3 second shots", 120, None, "3 second shots"),
        ("clips of a dog", None, None, "dog"),
        ("a sunset", None, None, "sunset"),  # "a" alone is not a length
    ],
)
def test_brief_is_read_into_length_order_and_subject(
    text: str, target: float | None, order: str | None, query: str
) -> None:
    brief = parse(text)
    assert (brief.target_s, brief.order, brief.query) == (target, order, query)
    assert brief.understood  # the page always says how the brief was read


def test_brief_without_subject_says_so() -> None:
    assert parse("2 minutes").understood[-1].startswith("no subject named")


def test_shot_too_short_is_not_used() -> None:
    assert trim_shot(0.0, 1.0, 0.5, [], CFG) is None


def test_shot_without_speech_is_cut_around_the_match() -> None:
    trim = trim_shot(10.0, 30.0, 25.0, [], CFG)
    assert trim is not None and trim.how == "around match"
    assert (trim.in_s, trim.out_s) == (22.0, 28.0)  # max_clip_s 6 centred on the match
    edge = trim_shot(10.0, 30.0, 29.5, [], CFG)  # near the end: the window stays inside
    assert edge is not None and (edge.in_s, edge.out_s) == (24.0, 30.0)
    whole = trim_shot(10.0, 14.0, 12.0, [], CFG)
    assert whole is not None and whole.how == "whole shot" and (whole.in_s, whole.out_s) == (10, 14)


def test_a_limit_shortens_a_shot_without_speech() -> None:
    trim = trim_shot(10.0, 30.0, 20.0, [], CFG, limit=3.0)
    assert trim is not None and trim.length == pytest.approx(3.0)
    assert trim_shot(10.0, 30.0, 20.0, [], CFG, limit=1.0) is None  # under min_clip_s


def test_speech_keeps_whole_lines_and_the_closest_neighbours() -> None:
    lines = [
        Line(1.0, 4.0, "first"),
        Line(5.0, 9.0, "second"),
        Line(9.5, 13.0, "third"),
        Line(20.0, 28.0, "far away"),
    ]
    trim = trim_shot(0.0, 40.0, 6.0, lines, CFG)
    assert trim is not None and trim.how == "speech"
    # Anchor "second", then its closest neighbour "third", then "first"; "far away" would make
    # the clip longer than 15 s.
    assert trim.lines == ["first", "second", "third"]
    assert (trim.in_s, trim.out_s) == (0.75, 13.25)
    assert "1 other line(s) in the shot left out" in trim.detail


def test_speech_fits_a_limit_by_keeping_fewer_whole_lines() -> None:
    lines = [Line(0.0, 4.0, "one"), Line(4.5, 8.0, "two"), Line(8.5, 13.0, "three")]
    # Two lines with room take 8.5 s; with 6 s left only the matched line fits, whole.
    trim = trim_shot(0.0, 20.0, 6.0, lines, CFG, limit=6.0)
    assert trim is not None and trim.lines == ["two"]
    assert (trim.in_s, trim.out_s) == (4.25, 8.25)
    assert trim_shot(0.0, 20.0, 6.0, lines, CFG, limit=3.0) is None  # the line alone is longer


def test_speech_is_never_shortened_to_fit() -> None:
    lines = [Line(1.0, 6.0, "a long sentence")]
    assert trim_shot(0.0, 10.0, 2.0, lines, CFG, limit=3.0) is None
    fits = trim_shot(0.0, 10.0, 2.0, lines, CFG, limit=6.0)
    assert fits is not None and (fits.in_s, fits.out_s) == (0.75, 6.25)


def test_a_line_running_past_the_shot_edge_is_cut_there_and_noted() -> None:
    trim = trim_shot(2.0, 6.0, 3.0, [Line(1.0, 4.0, "started earlier")], CFG)
    assert trim is not None and trim.in_s == 2.0
    assert "runs past the shot's edge" in trim.detail


def test_a_very_short_line_still_gives_a_usable_clip() -> None:
    trim = trim_shot(0.0, 10.0, 5.0, [Line(5.0, 5.3, "hi")], CFG)
    assert trim is not None and trim.length == pytest.approx(CFG.min_clip_s)
    assert trim.in_s <= 5.0 and trim.out_s >= 5.3


def test_uncertain_lines_never_reach_the_trim() -> None:
    """Callers pass only certain lines (`export.service.spoken_lines`); a shot whose lines were
    all dropped is trimmed as a shot without speech."""
    trim = trim_shot(0.0, 20.0, 10.0, [], CFG)
    assert trim is not None and trim.how == "around match"


def test_timeline_size_follows_the_orientation_most_cuts_have() -> None:
    def clips(*sizes: tuple[int | None, int | None]) -> Any:
        return [cast(Any, SimpleNamespace(width=w, height=h)) for w, h in sizes]

    reel = (1080, 1920)
    # 5 portrait cuts against 8 landscape cuts of two sizes: landscape, its most common size.
    assert frame_size(clips(*[reel] * 5, *[(3840, 2160)] * 5, *[(1920, 1080)] * 3)) == (3840, 2160)
    assert frame_size(clips(*[reel] * 3, (1920, 1080))) == reel
    assert frame_size(clips(reel, (1920, 1080))) == (1920, 1080)  # a tie goes to landscape
    assert frame_size(clips((None, None))) == (1920, 1080)
