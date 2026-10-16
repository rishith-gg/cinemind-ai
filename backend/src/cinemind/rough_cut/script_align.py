"""Finding each dialogue line of a screenplay in the transcripts (SPEC P1-A). Pure functions on
plain data, so the app and eval/script_align.py run the same code.

Ours: the windows, the trimming to matched words, the two scores and how they combine.
Existing: difflib's SequenceMatcher (Ratcliff/Obershelp) for the word and character matching,
and the sentence-embedding model (MiniLM) for meaning.

- Windows: 1 to `max_window` neighbouring transcript segments of one clip with pauses of at most
  `max_gap_s` (an actor's line can be split over segments, or share one with other words).
- Lexical: the line's words are matched in order against the window's words; the window is
  trimmed to the first and last matched word (this also gives the take's in and out times), and
  the score is the character-level similarity of the line and that stretch, 0..1. Words are
  compared lower case without punctuation.
- Semantic: cosine of the text vectors of the line and the window (0 when negative), or None
  when the text model is not downloaded.
- Score: `(wl * lexical + ws * semantic) / (wl + ws)`, or lexical alone without the model
  (the caller then uses `words_only_min_score`).
- Takes: the 50 windows sharing the line's rarest words (summed inverse frequency), plus the 20
  most similar in meaning, are scored; with fewer than two real words in common the take is the
  whole window (a lone "the" says nothing about where the line is); overlapping takes in one clip
  keep only the best; the best `takes_kept` are returned, plus the user's pick if it fell out.
"""

# numpy arrays are untyped.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

import numpy as np

from cinemind.core.script_config import ScriptConfig
from cinemind.search.spoken import Word

SEMANTIC_TOP = 20
# At most this many windows sharing words with a line are scored in full (rarest words first).
WORD_POOL = 50
# A take's stretch is widened by at most this many words on each side.
MAX_WIDEN = 6
# Words too common to say two texts are about the same line.
_COMMON = (
    "a an and are at be but by for from i in is it me my of on or so that the this to we with you"
)
STOPWORDS = frozenset(_COMMON.split())
Embed = Callable[[Sequence[str]], Any]
Place = tuple[str, float, float]  # media id, start, end


@dataclass(frozen=True)
class Segment:
    id: int
    media_id: str
    start_s: float
    end_s: float
    text: str
    words: tuple[Word, ...] = ()


@dataclass(frozen=True)
class Window:
    media_id: str
    segment_ids: tuple[int, ...]
    words: tuple[Word, ...]
    norm: tuple[str, ...]  # normalised words, same length as `words`

    @property
    def text(self) -> str:
        return " ".join(w.text.strip() for w in self.words)


@dataclass(frozen=True)
class Take:
    media_id: str
    segment_ids: tuple[int, ...]
    start_s: float
    end_s: float
    text: str
    lexical: float
    semantic: float | None
    score: float


def normalise(word: str) -> str:
    return "".join(ch for ch in word.lower() if ch.isalnum())


def _words(seg: Segment) -> tuple[Word, ...]:
    if seg.words:
        return seg.words
    parts = seg.text.split()  # no word timings: spread the words evenly over the segment
    step = (seg.end_s - seg.start_s) / max(1, len(parts))
    return tuple(
        Word(seg.start_s + i * step, seg.start_s + (i + 1) * step, p) for i, p in enumerate(parts)
    )


def windows(segments: Sequence[Segment], cfg: ScriptConfig) -> list[Window]:
    by_clip: dict[str, list[Segment]] = {}
    for seg in segments:
        by_clip.setdefault(seg.media_id, []).append(seg)
    found: list[Window] = []
    for media_id, segs in by_clip.items():
        segs.sort(key=lambda s: s.start_s)
        for i in range(len(segs)):
            words: list[Word] = []
            for j in range(i, min(len(segs), i + cfg.max_window)):
                if j > i and segs[j].start_s - segs[j - 1].end_s > cfg.max_gap_s:
                    break
                words.extend(w for w in _words(segs[j]) if normalise(w.text))
                if words:
                    ids = tuple(s.id for s in segs[i : j + 1])
                    norm = tuple(normalise(w.text) for w in words)
                    found.append(Window(media_id, ids, tuple(words), norm))
    return found


def lexical(line: Sequence[str], window: Window) -> tuple[float, int, int, int]:
    """Similarity of the line to the stretch of the window that holds it (from its first to its
    last matched word, widened as below), that stretch (start index, end index exclusive), and
    how many of the line's words that are not stopwords were matched word for word."""
    blocks = [
        b
        for b in SequenceMatcher(
            None, list(line), list(window.norm), autojunk=False
        ).get_matching_blocks()
        if b.size
    ]
    if not blocks or not line:
        return 0.0, 0, 0, 0
    content = sum(1 for b in blocks for w in line[b.a : b.a + b.size] if w not in STOPWORDS)
    # Line words before the first match and after the last ("you're" against "you are") may be
    # said with more or fewer words: the stretch is widened by up to that many words plus two
    # (at most MAX_WIDEN) on each side, keeping the widening whose characters match the line best
    # (the shorter on a tie). Cheap upper bounds skip widenings that cannot win.
    start, stop = blocks[0].b, blocks[-1].b + blocks[-1].size
    before, after = blocks[0].a, len(line) - blocks[-1].a - blocks[-1].size
    text = " ".join(line)
    best = (-1.0, start, stop)
    for extra_before in range(min(start, before + 2, MAX_WIDEN) + 1):
        for extra_after in range(min(len(window.norm) - stop, after + 2, MAX_WIDEN) + 1):
            first, last = start - extra_before, stop + extra_after
            matcher = SequenceMatcher(None, text, " ".join(window.norm[first:last]), autojunk=False)
            if (
                matcher.real_quick_ratio() <= best[0] + 1e-9
                or matcher.quick_ratio() <= best[0] + 1e-9
            ):
                continue
            ratio = matcher.ratio()
            if ratio > best[0] + 1e-9:
                best = (ratio, first, last)
    return max(0.0, best[0]), best[1], best[2], content


def _overlaps(a: Take, b: Take) -> bool:
    if a.media_id != b.media_id:
        return False
    shared = min(a.end_s, b.end_s) - max(a.start_s, b.start_s)
    return shared > 0.5 * min(a.end_s - a.start_s, b.end_s - b.start_s)


def _at(take: Take, place: Place) -> bool:
    media_id, start, end = place
    return take.media_id == media_id and min(take.end_s, end) - max(take.start_s, start) > 0


def align(
    lines: Sequence[str],
    segments: Sequence[Segment],
    cfg: ScriptConfig,
    embed: Embed | None = None,
    picked: Sequence[Place | None] | None = None,
) -> list[list[Take]]:
    """For each line, its best takes (best first, at most `takes_kept`; possibly below the
    limit, which the caller compares with). `picked[i]`, a take the user chose for line i, is
    kept even when it is no longer among the best (it is added last)."""
    wins = windows(segments, cfg)
    if not wins or not lines:
        return [[] for _ in lines]
    index: dict[str, set[int]] = {}
    for n, win in enumerate(wins):
        for word in set(win.norm):
            if word not in STOPWORDS:
                index.setdefault(word, set()).add(n)
    rarity = {word: math.log(len(wins) / len(found)) + 1 for word, found in index.items()}
    use_meaning = embed is not None and cfg.semantic_weight > 0
    line_vecs = win_vecs = None
    if use_meaning and embed is not None:
        line_vecs = np.asarray(embed(list(lines)), dtype=np.float32)
        win_vecs = np.asarray(embed([w.text for w in wins]), dtype=np.float32)
    # Without the text model the lexical score is the score.
    wl = cfg.lexical_weight if use_meaning else 1.0
    weights = wl + (cfg.semantic_weight if use_meaning else 0.0)
    result: list[list[Take]] = []
    for li, line in enumerate(lines):
        norm = [w for w in (normalise(p) for p in line.split()) if w]
        content_words = [w for w in norm if w not in STOPWORDS]
        # The windows sharing the rarest of the line's words, then the closest in meaning.
        shared: dict[int, float] = {}
        for word in set(content_words):
            for n in index.get(word, ()):
                shared[n] = shared.get(n, 0.0) + rarity[word]
        pool = set(sorted(shared, key=lambda n: (-shared[n], n))[:WORD_POOL])
        sims = None
        if line_vecs is not None and win_vecs is not None:
            sims = win_vecs @ line_vecs[li]
            top = min(SEMANTIC_TOP, len(wins))
            pool |= {int(i) for i in np.argpartition(-sims, top - 1)[:top]}
        scored: list[Take] = []
        for n in pool:
            win = wins[n]
            lex, first, last, content = lexical(norm, win)
            # Too few real words in common to say where in the window the line is (one shared
            # "the"): the take is the whole window.
            if last <= first or content < min(2, len(content_words)) or not content_words:
                first, last = 0, len(win.words)
            sem = None if sims is None else max(0.0, float(sims[n]))
            total = wl * lex + (cfg.semantic_weight * sem if sem is not None else 0)
            kept = win.words[first:last]
            scored.append(
                Take(
                    media_id=win.media_id,
                    segment_ids=win.segment_ids,
                    start_s=kept[0].start_s,
                    end_s=kept[-1].end_s,
                    text=" ".join(w.text.strip() for w in kept),
                    lexical=round(lex, 4),
                    semantic=None if sem is None else round(sem, 4),
                    score=round(total / weights, 4),
                )
            )
        scored.sort(key=lambda t: (-t.score, t.media_id, t.start_s))
        best: list[Take] = []
        for take in scored:
            if not any(_overlaps(take, other) for other in best):
                best.append(take)
            if len(best) >= cfg.takes_kept:
                break
        place = picked[li] if picked and li < len(picked) else None
        if place and not any(_at(t, place) for t in best):
            kept_pick = next((t for t in scored if _at(t, place)), None)
            if kept_pick is not None:
                best.append(kept_pick)
        result.append(best)
    return result
