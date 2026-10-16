"""Reading a screenplay and finding its lines in transcripts, without footage."""

from collections.abc import Sequence
from typing import Any

import numpy as np
import pytest

from cinemind.core.errors import InvalidInputError
from cinemind.core.script_config import ScriptConfig
from cinemind.rough_cut.script_align import Segment, align, windows
from cinemind.rough_cut.script_parse import parse

FOUNTAIN = """Title: Test
Author: Someone

INT. LAB - NIGHT

Thom paces. [[a note to self]]

THOM (V.O.)
(quietly)
You're a jerk,
Celia.

/* an idea we cut
CELIA
Gone.
*/

CELIA ^
Look, we have to follow our passions.

CUT TO:

.UNDER THE BRIDGE

@McCLANE
Yippee ki-yay.
"""


def test_fountain_scenes_characters_dialogue_and_skipped_parts() -> None:
    fmt, lines = parse(FOUNTAIN)
    assert fmt == "fountain"
    assert [(line.kind, line.character, line.text, line.scene) for line in lines] == [
        ("scene", None, "INT. LAB - NIGHT", "INT. LAB - NIGHT"),
        ("action", None, "Thom paces.", "INT. LAB - NIGHT"),
        ("dialogue", "THOM", "You're a jerk, Celia.", "INT. LAB - NIGHT"),
        ("dialogue", "CELIA", "Look, we have to follow our passions.", "INT. LAB - NIGHT"),
        ("scene", None, "UNDER THE BRIDGE", "UNDER THE BRIDGE"),
        ("dialogue", "McCLANE", "Yippee ki-yay.", "UNDER THE BRIDGE"),
    ]


def test_plain_text_lines_with_and_without_names() -> None:
    fmt, lines = parse("Thom: You're a jerk.\nJust a line\n\nCelia: Hi there")
    assert fmt == "plain"
    assert [(line.character, line.text) for line in lines] == [
        ("Thom", "You're a jerk."),
        (None, "Just a line"),
        ("Celia", "Hi there"),
    ]


@pytest.mark.parametrize("text", ["", "   \n\n", "INT. ROOM\n\nNobody says anything."])
def test_a_script_without_dialogue_is_refused(text: str) -> None:
    with pytest.raises(InvalidInputError, match="No dialogue"):
        parse(text)


WORDS_ONLY = ScriptConfig(lexical_weight=1.0, semantic_weight=0.0)
SEGMENTS = [
    Segment(1, "a", 0.0, 2.0, "You're a jerk, Thom."),
    Segment(2, "a", 2.5, 5.0, "Look Celia, we have to follow our passions."),
    Segment(3, "b", 10.0, 12.0, "well you are a jerk thom she said"),
    Segment(4, "b", 30.0, 33.0, "something else entirely"),
]


def test_exact_and_paraphrased_takes_best_first() -> None:
    takes = align(["You're a jerk, Thom."], SEGMENTS, WORDS_ONLY)[0]
    assert [(t.media_id, t.score) for t in takes][0] == ("a", 1.0)
    second = takes[1]
    assert second.media_id == "b" and 0.6 < second.score < 1.0
    # The take is cut to the words of the line ("you are a jerk thom"), not the whole segment.
    assert second.text == "you are a jerk thom"
    assert second.start_s > 10.0 and second.end_s < 12.0


def test_a_line_over_two_segments_is_one_take() -> None:
    line = "You're a jerk Thom. Look Celia, we have to follow our passions."
    best = align([line], SEGMENTS, WORDS_ONLY)[0][0]
    assert best.segment_ids == (1, 2) and best.score > 0.9
    assert (best.start_s, best.end_s) == (0.0, 5.0)


def test_segments_further_apart_than_the_gap_are_not_joined() -> None:
    joined = {w.segment_ids for w in windows(SEGMENTS, WORDS_ONLY)}
    assert (1, 2) in joined and (3, 4) not in joined  # 18 s pause between 3 and 4


def test_a_line_not_in_any_transcript_scores_low() -> None:
    takes = align(["The harbour lights went out an hour ago."], SEGMENTS, WORDS_ONLY)[0]
    assert not takes or takes[0].score < WORDS_ONLY.words_only_min_score


def test_meaning_counts_when_the_model_is_there() -> None:
    def embed(texts: Sequence[str]) -> Any:
        # A stand-in: "jerk" lines point one way, everything else another.
        rows = [[1.0, 0.0] if "jerk" in t.lower() else [0.0, 1.0] for t in texts]
        return np.asarray(rows, dtype=np.float32)

    both = ScriptConfig(lexical_weight=0.5, semantic_weight=0.5)
    best = align(["What a jerk you are"], SEGMENTS, both, embed)[0][0]
    assert best.semantic == 1.0 and best.score == pytest.approx((best.lexical + 1.0) / 2, abs=1e-3)
    # Without the model the lexical score is the score.
    alone = align(["What a jerk you are"], SEGMENTS, both)[0][0]
    assert alone.semantic is None and alone.score == alone.lexical


def test_overlapping_takes_in_one_clip_keep_only_the_best() -> None:
    takes = align(["follow our passions"], SEGMENTS, WORDS_ONLY)[0]
    starts = [(t.media_id, t.start_s) for t in takes]
    assert len(starts) == len(set(starts))
    in_a = [t for t in takes if t.media_id == "a"]
    assert len(in_a) == 1  # windows (2,) and (1, 2) found the same words


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # A heading typed without a blank line after it stays a heading; the rest is action.
        (
            "INT. HOUSE - DAY\nJohn walks in.\n\nJOHN\nHello.",
            [("scene", None, "INT. HOUSE - DAY"), ("action", None, "John walks in."),
             ("dialogue", "JOHN", "Hello.")],
        ),
        # NAME: rows under a scene heading are dialogue, not action.
        (
            "INT. KITCHEN\n\nANNA: Hello\nBEN: Hi",
            [("scene", None, "INT. KITCHEN"), ("dialogue", "ANNA", "Hello"),
             ("dialogue", "BEN", "Hi")],
        ),
        # A title page is skipped in plain text too.
        ("Title: My film\nAuthor: Me\n\nAnna: Hello", [("dialogue", "Anna", "Hello")]),
        # Extension before the dual-dialogue caret; parenthetical over two lines.
        ("INT. X\n\nBRICK (V.O.) ^\n(softly,\nslowly)\nHey.",
         [("scene", None, "INT. X"), ("dialogue", "BRICK", "Hey.")]),
        # EXT/INT headings and scene numbers.
        ("EXT/INT CAR - NIGHT #12A#\n\nANNA\nGo.",
         [("scene", None, "EXT/INT CAR - NIGHT"), ("dialogue", "ANNA", "Go.")]),
        # "Scene 1:" is not a character; blank lines before a title page.
        ("Scene 1: kitchen\nAnna: Hi",
         [("dialogue", None, "Scene 1: kitchen"), ("dialogue", "Anna", "Hi")]),
        ("\n\nTitle: X\n\nANNA\nHi.", [("dialogue", "ANNA", "Hi.")]),
        ("ANNA\r\nHi there.\r\n", [("dialogue", "ANNA", "Hi there.")]),
    ],
)  # fmt: skip
def test_screenplay_edge_cases(text: str, expected: list[tuple[str, str | None, str]]) -> None:
    _, lines = parse(text)
    assert [(line.kind, line.character, line.text) for line in lines] == expected


def test_size_limits() -> None:
    with pytest.raises(InvalidInputError, match="too long"):
        parse("a" * 1_000_001)
    with pytest.raises(InvalidInputError, match="more than 5000"):
        parse("\n".join(f"line {n}" for n in range(5001)))


def test_meaning_only_take_with_one_shared_stopword_is_the_whole_window() -> None:
    def embed(texts: Sequence[str]) -> Any:
        return np.asarray([[1.0, 0.0] for _ in texts], dtype=np.float32)  # all alike in meaning

    cfg = ScriptConfig(lexical_weight=0.0, semantic_weight=1.0)
    segs = [Segment(1, "a", 0.0, 4.0, "well the weather is nice today")]
    take = align(["the end of everything"], segs, cfg, embed)[0][0]
    assert (take.start_s, take.end_s) == (0.0, 4.0)  # not just the word "the"


def test_a_picked_take_is_kept_when_better_ones_appear() -> None:
    segs = [Segment(n, "a", n * 10.0, n * 10.0 + 2, "you are a jerk thom") for n in range(8)]
    segs.append(Segment(99, "b", 0.0, 2.0, "you're a jerk thom"))
    cfg = ScriptConfig(lexical_weight=1.0, semantic_weight=0.0, takes_kept=3)
    pick = ("a", 70.0, 72.0)  # the last of the eight weaker takes
    takes = align(["You're a jerk, Thom."], segs, cfg, picked=[pick])[0]
    assert takes[0].media_id == "b" and len(takes) == 4
    assert takes[-1].media_id == "a" and takes[-1].start_s >= 70.0


def test_many_lines_against_many_segments_stays_fast() -> None:
    import time

    words = [f"w{n}" for n in range(400)]
    segs = [
        Segment(
            n,
            f"m{n % 20}",
            n * 3.0,
            n * 3.0 + 2,
            " ".join(words[(n * 7 + k) % 400] for k in range(8)),
        )
        for n in range(3000)
    ]
    lines = [" ".join(words[(n * 13 + k) % 400] for k in range(10)) for n in range(300)]
    began = time.perf_counter()
    found = align(lines, segs, WORDS_ONLY)
    assert len(found) == 300 and time.perf_counter() - began < 30
