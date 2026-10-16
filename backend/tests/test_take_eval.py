"""The figures of eval/take_groups.py: pairwise and B-cubed scores, and shot labels."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from cinemind.pipeline.take_signals import ShotInfo

EVAL = Path(__file__).resolve().parents[2] / "eval" / "take_groups.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("take_groups_eval", EVAL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["take_groups_eval"] = module
    spec.loader.exec_module(module)
    return module


def test_perfect_grouping_scores_one() -> None:
    m = _module()
    r = m.score([["a", "b"], ["c", "d", "e"]], [["b", "a"], ["e", "d", "c"]], list("abcdef"))
    assert r["pairwise"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert r["bcubed"]["f1"] == pytest.approx(1.0)
    assert r["wrong_pairs"] == [] and r["missed_pairs"] == []


def test_one_wrong_and_one_missed_pair() -> None:
    m = _module()
    # truth: {a,b,c}; predicted {a,b} and a wrong {c,d}
    r = m.score([["a", "b"], ["c", "d"]], [["a", "b", "c"]], list("abcd"))
    assert r["pairs"] == {"predicted": 2, "true": 3, "right": 1}
    assert r["pairwise"]["precision"] == 0.5 and r["pairwise"]["recall"] == pytest.approx(1 / 3)
    assert r["wrong_pairs"] == [["c", "d"]] and r["missed_pairs"] == [["a", "c"], ["b", "c"]]
    # B-cubed precision: a 1, b 1, c 1/2, d 1/2 -> 0.75; recall: a 2/3, b 2/3, c 1/3, d 1 -> 2/3
    assert r["bcubed"]["precision"] == pytest.approx(0.75)
    assert r["bcubed"]["recall"] == pytest.approx(2 / 3)


def test_nothing_predicted_has_no_pairwise_precision() -> None:
    r = _module().score([], [["a", "b"]], ["a", "b"])
    assert r["pairwise"]["precision"] is None and r["pairwise"]["recall"] == 0.0


def test_labels_count_shots_from_one_within_each_clip() -> None:
    infos = [
        ShotInfo("x", "m1", "A.MOV", 0, 0, 1),
        ShotInfo("y", "m1", "A.MOV", 1, 1, 2),
        ShotInfo("z", "m2", "B.MOV", 2, 0, 1),
    ]
    m = _module()
    assert [m.label_of(i, infos) for i in infos] == ["A.MOV#1", "A.MOV#2", "B.MOV#1"]
