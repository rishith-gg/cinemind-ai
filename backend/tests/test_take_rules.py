"""Take detection rules (pure functions): pair rules, grouping with constraints, best take."""

from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from cinemind.core.takes_config import TakesConfig
from cinemind.pipeline.take_signals import (
    ShotInfo,
    adjacency,
    group,
    pair,
    rank_takes,
    text_similarity,
    words_in,
)
from cinemind.search.spoken import Word

CFG = TakesConfig()


def _vec(*values: float) -> Any:
    v = np.asarray(values, dtype=np.float32)
    return v / np.linalg.norm(v)


def _words(text: str, start: float = 1.0, step: float = 0.4) -> tuple[Word, ...]:
    return tuple(
        Word(start + i * step, start + (i + 1) * step - 0.05, w) for i, w in enumerate(text.split())
    )


def _shot(n: int, text: str = "", picture: Any = None, **kw: Any) -> ShotInfo:
    end = kw.pop("end_s", 10.0)
    return ShotInfo(
        id=f"s{n}", media_id=f"m{n}", filename=f"IMG_{n}.MOV", position=n, start_s=0.0,
        end_s=end, picture=picture, words=_words(text) if text else (), **kw,
    )  # fmt: skip


LINE = "we have to follow our passions celia"


def test_same_words_link_two_takes_even_far_apart() -> None:
    a = _shot(0, LINE, _vec(1, 0, 0))
    b = _shot(9, "we have to follow our passions celia", _vec(0.8, 0.6, 0))
    p = pair(0, 1, [a, b], CFG)
    assert p.rule == "speech" and p.text == 1.0 and p.adjacent == 0.0
    assert p.picture == pytest.approx(0.8, abs=1e-3)
    # 0.6 * 1.0 + 0.25 * 0.8 + 0.15 * 0 = 0.8
    assert p.score == pytest.approx(0.8, abs=1e-3) and p.score >= CFG.group_min


def test_different_words_in_the_same_picture_are_not_takes() -> None:
    """A static interview camera: the picture never changes, the answers do."""
    same = _vec(1, 0, 0)
    a = _shot(0, "i grew up in a small town by the river", same)
    b = _shot(1, "my first film was shot on a borrowed phone", same)
    p = pair(0, 1, [a, b], CFG)
    assert p.score == 0 and p.why.startswith("different words")


def test_same_words_in_another_picture_are_not_takes() -> None:
    a = _shot(0, LINE, _vec(1, 0, 0))
    b = _shot(1, LINE, _vec(0, 1, 0))
    p = pair(0, 1, [a, b], CFG)
    assert p.score == 0 and "other picture" in p.why


def test_shots_without_speech_need_the_same_picture_and_to_be_close() -> None:
    a, b = _shot(0, picture=_vec(1, 0.05, 0)), _shot(1, picture=_vec(1, 0.0, 0))
    near = pair(0, 1, [a, b], CFG)
    assert near.rule == "picture" and near.score >= CFG.group_min
    far = pair(0, 1, [a, _shot(9, picture=_vec(1, 0, 0))], CFG)
    assert far.score == 0 and "apart" in far.why
    other = pair(0, 1, [a, _shot(1, picture=_vec(1, 1, 0))], CFG)
    assert other.score == 0 and other.why.startswith("pictures differ")
    blind = pair(0, 1, [_shot(0), _shot(1)], CFG)
    assert blind.rule == "none" and blind.score == 0


def test_adjacency_falls_with_distance() -> None:
    values = [adjacency(_shot(0), _shot(d), CFG) for d in (1, 2, 3, 4)]
    assert values == [1.0, pytest.approx(0.6667, abs=1e-4), pytest.approx(0.3333, abs=1e-4), 0.0]


def test_text_similarity_handles_flubs_and_empty() -> None:
    assert text_similarity(["a", "b"], []) == 0.0
    flub = text_similarity(
        ["we", "we", "have", "to", "follow", "our", "passions", "celia"], LINE.split()
    )
    assert 0.85 < flub < 1.0
    assert text_similarity(["hello"], ["goodbye", "now"], at_least=0.99) < 0.99  # an upper bound


def test_words_belong_to_the_shot_their_middle_falls_in() -> None:
    words = (Word(1.8, 2.4, "edge"), Word(0.2, 0.6, "in"), Word(2.6, 3.0, "out"))
    assert [w.text for w in words_in(words, 0.0, 2.0)] == ["in"]
    assert [w.text for w in words_in(words, 2.0, 4.0)] == ["edge", "out"]


def test_one_strong_pair_does_not_chain_unrelated_shots() -> None:
    """A~B and B~C by picture, A and C too different: average linkage keeps one pair only."""
    infos = [
        _shot(0, picture=_vec(1, 0.0, 0)),
        _shot(1, picture=_vec(1, 0.36, 0)),
        _shot(2, picture=_vec(1, 0.8, 0)),
    ]
    groups, pairs = group(infos, CFG)
    assert pairs[(0, 1)].score >= CFG.group_min and pairs[(1, 2)].score >= CFG.group_min
    assert pairs[(0, 2)].score == 0
    assert len(groups) == 1 and len(groups[0]) == 2


def test_three_takes_form_one_group_and_apart_answers_split_it() -> None:
    infos = [_shot(i, LINE, _vec(1, 0.02 * i, 0)) for i in range(3)] + [
        _shot(3, "other words here")
    ]
    groups, _ = group(infos, CFG)
    assert groups == [[0, 1, 2]]
    groups, _ = group(infos, CFG, apart={frozenset(("s2", "s0")), frozenset(("s2", "s1"))})
    assert groups == [[0, 1]]
    groups, _ = group(infos[:2], CFG, apart={frozenset(("s0", "s1"))})
    assert groups == []


def test_best_take_is_the_clean_complete_sharp_one_with_reasons() -> None:
    pic = _vec(1, 0, 0)
    infos = [
        _shot(
            0, "we have to uh follow our passions celia", pic, focus=0.9, exposure=0.9, audio=0.8
        ),
        _shot(1, LINE, pic, focus=0.9, exposure=0.9, audio=0.8),
        _shot(2, "we have to follow", pic, focus=0.9, exposure=0.9, audio=0.8),
        _shot(3, LINE, pic, focus=0.2, exposure=0.9, audio=0.8),
    ]
    groups, pairs = group(infos, CFG)
    assert groups == [[0, 1, 2, 3]]  # the short take still says most of the line
    kind, ranked, best_by = rank_takes([0, 1, 2, 3], infos, pairs, CFG)
    assert kind == "speech" and best_by == "auto"
    assert ranked[0].info.id == "s1"
    by_id = {r.info.id: r for r in ranked}
    assert by_id["s0"].notes == ["1 filler word(s)"] and by_id["s0"].signals["clean"] == 0.75
    assert by_id["s2"].signals["complete"] == pytest.approx(4 / 7, abs=1e-3)
    assert by_id["s3"].signals["focus"] == 0.2
    assert all(r.score is not None and 0 <= r.score <= 1 for r in ranked)


def test_cut_off_speech_and_repeats_are_flubs() -> None:
    pic = _vec(1, 0, 0)
    cut = ShotInfo(
        "c", "m", "c.mov", 0, 1.0, 3.0, pic, _words("we we have to", start=1.0, step=0.5)
    )
    ok = _shot(1, "we have to follow", pic)
    _, ranked, _ = rank_takes([0, 1], [cut, ok], {(0, 1): pair(0, 1, [cut, ok], CFG)}, CFG)
    notes = next(r.notes for r in ranked if r.info.id == "c")
    assert "1 repeated word(s)" in notes
    assert "speech starts at the first frame (cut off?)" in notes
    assert "speech runs to the last frame (cut off?)" in notes


def test_user_pick_wins_and_rejected_takes_are_never_best() -> None:
    pic = _vec(1, 0, 0)
    infos = [_shot(0, picture=pic, focus=0.9), _shot(1, picture=pic, focus=0.3)]
    pairs = {(0, 1): pair(0, 1, infos, CFG)}
    kind, ranked, best_by = rank_takes([0, 1], infos, pairs, CFG, user_best="s1")
    assert kind == "picture" and ranked[0].info.id == "s1" and best_by == "you"
    infos[0].rejected = True
    _, ranked, best_by = rank_takes([0, 1], infos, pairs, CFG)
    assert ranked[0].info.id == "s1" and "rejected by you" in ranked[1].notes
    infos[1].rejected = True
    _, ranked, best_by = rank_takes([0, 1], infos, pairs, CFG, user_best="s1")
    assert best_by == "none"


def test_missing_signals_leave_the_mean_of_the_others() -> None:
    pic = _vec(1, 0, 0)
    infos = [_shot(0, picture=pic, focus=None, exposure=0.6), _shot(1, picture=pic)]
    _, ranked, _ = rank_takes([0, 1], infos, {(0, 1): pair(0, 1, infos, CFG)}, CFG)
    first = next(r for r in ranked if r.info.id == "s0")
    assert first.score == 0.6 and "focus not measured" in first.notes
    assert next(r for r in ranked if r.info.id == "s1").score is None


def test_settings_are_checked() -> None:
    with pytest.raises(ValidationError):
        TakesConfig(text_min=1.5)
    with pytest.raises(ValidationError):
        TakesConfig(best_weights={"focus": 1, "sparkle": 1})
    with pytest.raises(ValidationError):
        TakesConfig(pair_weights={"text": 0, "picture": 0, "adjacent": 0})


def test_a_far_apart_flubbed_take_says_why_it_is_not_grouped() -> None:
    pic = _vec(1, 0, 0)
    a = _shot(0, "we have to leave the city tonight", pic)
    b = _shot(10, "uh we we have to go leave the city now tonight", _vec(0.9, 0.43589, 0))
    p = pair(0, 1, [a, b], CFG)
    assert p.text is not None and CFG.text_min <= p.text
    assert p.score < CFG.group_min and "but pair score" in p.why


def test_a_pre_filtered_word_score_is_an_upper_bound() -> None:
    a = _shot(0, "the quick brown fox jumps over", _vec(1, 0, 0))
    b = _shot(1, "zzz yyy xxx www vvv uuu ttt", _vec(1, 0, 0))
    p = pair(0, 1, [a, b], CFG)
    assert p.score == 0 and p.why.startswith("different words (at most")
