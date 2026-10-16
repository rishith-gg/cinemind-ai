"""The ground truth of eval/script_align.py: where a line counts as found."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from cinemind.rough_cut.script_align import Take

EVAL = Path(__file__).resolve().parents[2] / "eval" / "script_align.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("script_align_eval", EVAL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["script_align_eval"] = module
    spec.loader.exec_module(module)
    return module


def _take(start: float, end: float, score: float = 1.0) -> list[Take]:
    return [Take("film", (1,), start, end, "", score, None, score)]


SUBS = [
    ("You're a jerk, Thom.", 20.0, 22.0),
    ("Look Celia, we have to follow our passions.", 23.0, 26.0),
    ("Nothing to worry about.", 30.0, 32.0),
    ("No.", 40.0, 41.0),
    ("Look Celia.", 300.0, 301.0),
    ("We have to follow our passions.", 302.0, 304.0),
]


def test_neighbouring_subtitles_never_count_and_words_match_whole() -> None:
    e = _module()
    where = e.places(SUBS)
    # The lines just before and after never count; the same words said again later do (as two
    # neighbouring subtitles there).
    assert where[1] == [(23.0, 26.0), (300.0, 304.0)]
    # A repeat later in the film is (the second half of the break-up scene).
    assert (23.0, 26.0) in where[5] and (23.0, 26.0) in where[4]
    # "no" is not found inside "nothing".
    assert where[3] == [(40.0, 41.0)]


def test_a_take_is_right_only_when_its_middle_is_at_a_place() -> None:
    e = _module()
    where = e.places(SUBS)
    assert e.right(_take(23.2, 25.8), where[1], 0.5)
    assert not e.right(_take(20.0, 22.0), where[1], 0.5)  # the neighbouring line's take
    assert not e.right(_take(23.2, 25.8, score=0.4), where[1], 0.5)  # under the limit
    assert e.right([], None, 0.5) and not e.right(_take(0, 1), None, 0.5)


def test_wilson_interval() -> None:
    e = _module()
    low, high = e.wilson(20, 38)
    assert 0.36 < low < 0.38 and 0.67 < high < 0.69
    assert e.wilson(0, 0) == (0.0, 0.0)
