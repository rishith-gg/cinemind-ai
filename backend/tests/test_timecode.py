from fractions import Fraction as F

import pytest

from cinemind.core.errors import InvalidInputError
from cinemind.utils.timecode import (
    frames_to_tc,
    rescale,
    seconds_to_frames,
    snap_rate,
    tc_to_frames,
    timebase,
)

NTSC30, NTSC60 = F(30000, 1001), F(60000, 1001)


@pytest.mark.parametrize(
    ("measured", "expected"),
    [
        (F(30000, 1001), NTSC30),
        (F(25), F(25)),
        # average rates ffprobe reports for variable-rate phone clips
        (F(96000, 1601), NTSC60),
        (F(76950, 1283), F(60)),
        (F(67575, 566), F(120000, 1001)),  # 119.39 average: see export_rate for the fix
        (F(89200, 3717), F(24)),
        (F(50, 3), F(17)),  # nothing standard within 1 %: nearest whole rate
    ],
)
def test_snap_rate(measured: F, expected: F) -> None:
    assert snap_rate(measured) == expected


def test_timebase_marks_ntsc_rates() -> None:
    assert timebase(NTSC30) == (30, True)
    assert timebase(F(24000, 1001)) == (24, True)
    assert timebase(F(60)) == (60, False)


@pytest.mark.parametrize(
    ("frames", "rate", "drop", "text"),
    [
        (107892, NTSC30, True, "01:00:00;00"),  # one hour of real time at 29.97
        (107892, NTSC30, False, "00:59:56:12"),
        (1800, NTSC30, True, "00:01:00;02"),  # frames ;00 and ;01 are skipped
        (17982, NTSC30, True, "00:10:00;00"),  # every tenth minute keeps them
        (215999, NTSC60, True, "01:00:03;35"),
        (90001, F(25), False, "01:00:00:01"),
        (86400, F(24000, 1001), False, "01:00:00:00"),
    ],
)
def test_timecode_known_values(frames: int, rate: F, drop: bool, text: str) -> None:
    assert frames_to_tc(frames, rate, drop) == text
    assert tc_to_frames(text, rate) == frames


@pytest.mark.parametrize("rate", [NTSC30, NTSC60])
def test_drop_frame_round_trips_every_frame_across_minute_boundaries(rate: F) -> None:
    base = round(rate)
    for frame in list(range(0, base * 700)) + list(range(base * 3590, base * 3610)):
        assert tc_to_frames(frames_to_tc(frame, rate, drop=True), rate) == frame


def test_drop_frame_is_ignored_for_rates_that_cannot_drop() -> None:
    assert frames_to_tc(90000, F(25), drop=True) == "01:00:00:00"


def test_bad_timecode_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        tc_to_frames("not a timecode", F(25))


def test_rescale_and_seconds_use_exact_rationals() -> None:
    assert seconds_to_frames(3603.6, NTSC30) == 108000
    assert rescale(48, F(24), F(60)) == 120
    assert rescale(100, NTSC60, NTSC60) == 100
