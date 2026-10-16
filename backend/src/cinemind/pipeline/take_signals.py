"""Take detection and best-take scoring (SPEC P1-B). Pure functions on plain data, so the app and
eval/take_groups.py run the same code.

Existing: difflib's SequenceMatcher (word similarity), the picture model's vectors (Phase 8),
scikit-learn's average-linkage clustering. Ours: the two pair rules, the pair score, the
constraints, and the best-take signals and their weights (all in `[takes]`, TakesConfig).

- Words: the shot's words from transcript lines not marked uncertain (a word belongs to the shot
  its middle falls in), lower case without punctuation. Similarity = character-level ratio of
  the two word strings, 0..1.
- Picture: cosine of the shots' mean keyframe vectors.
- Adjacent: 1 for neighbouring shots in project order, falling by 1 / `max_apart` per place,
  0 beyond `max_apart`.
- Grouping: pairs failing their rule score 0, pairs the user kept apart can never meet; average
  linkage joins groups while the mean pair score between them is at least `group_min` (so one
  strong pair cannot chain two unrelated shots together).
- Best take: weighted mean of focus, exposure, audio, and for speech groups how complete the
  line is (share of the most typical take's words said, in order) and how clean (flubs, fillers,
  uncertain lines, speech cut off at the shot's edge). The user's pick wins; a rejected shot is
  never the best.
"""

# scikit-learn and numpy are untyped.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
# pyright: reportArgumentType=false

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from cinemind.core.takes_config import TakesConfig
from cinemind.rough_cut.script_align import normalise
from cinemind.search.spoken import Word

# A pair kept apart by the user: far above any threshold times any group size.
APART = 1e9


@dataclass
class ShotInfo:
    id: str
    media_id: str
    filename: str
    position: int  # place in project order (clips by file name, then shots in source order)
    start_s: float
    end_s: float
    picture: Any = None  # unit vector or None
    words: tuple[Word, ...] = ()
    uncertain: int = 0  # transcript lines marked uncertain inside the shot
    focus: float | None = None
    exposure: float | None = None
    audio: float | None = None
    rejected: bool = False
    norm: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        self.norm = tuple(n for n in (normalise(w.text) for w in self.words) if n)

    @property
    def text(self) -> str:
        return " ".join(w.text.strip() for w in self.words)


@dataclass
class Pair:
    a: int
    b: int
    rule: str  # speech | picture | none
    text: float | None
    picture: float | None
    adjacent: float
    score: float
    why: str

    def as_dict(self, infos: Sequence[ShotInfo]) -> dict[str, Any]:
        return {
            "a": infos[self.a].id,
            "b": infos[self.b].id,
            "rule": self.rule,
            "text": self.text,
            "picture": self.picture,
            "adjacent": self.adjacent,
            "score": self.score,
            "why": self.why,
        }


@dataclass
class Ranked:
    info: ShotInfo
    score: float | None
    signals: dict[str, float | None]
    notes: list[str]


def words_in(words: Sequence[Word], start_s: float, end_s: float) -> tuple[Word, ...]:
    return tuple(w for w in words if start_s <= (w.start_s + w.end_s) / 2 < end_s)


def text_similarity(a: Sequence[str], b: Sequence[str], at_least: float = 0.0) -> float:
    """Character-level similarity of two word lists, 0..1. When a cheap upper bound already
    shows it cannot reach `at_least`, that upper bound is returned instead (shown as "at most")."""
    if not a or not b:
        return 0.0
    m = SequenceMatcher(None, " ".join(a), " ".join(b), autojunk=False)
    bound = m.real_quick_ratio()
    if bound < at_least:
        return round(bound, 4)
    bound = m.quick_ratio()
    if bound < at_least:
        return round(bound, 4)
    return round(m.ratio(), 4)


def adjacency(a: ShotInfo, b: ShotInfo, cfg: TakesConfig) -> float:
    apart = abs(a.position - b.position)
    return round(max(0.0, 1 - (apart - 1) / cfg.max_apart), 4) if apart else 1.0


def _mean(parts: dict[str, float | None], weights: dict[str, float]) -> float | None:
    used = [(weights[k], v) for k, v in parts.items() if v is not None and weights.get(k, 0) > 0]
    total = sum(w for w, _ in used)
    return round(sum(w * v for w, v in used) / total, 4) if total > 0 else None


def has_speech(info: ShotInfo, cfg: TakesConfig) -> bool:
    return len(info.norm) >= cfg.min_words


def pair(i: int, j: int, infos: Sequence[ShotInfo], cfg: TakesConfig) -> Pair:
    a, b = infos[i], infos[j]
    picture = None
    if a.picture is not None and b.picture is not None:
        picture = round(float(np.dot(a.picture, b.picture)), 4)
    adjacent = adjacency(a, b, cfg)
    if has_speech(a, cfg) and has_speech(b, cfg):
        text = text_similarity(a.norm, b.norm, cfg.text_min)
        if text < cfg.text_min:
            return Pair(
                i,
                j,
                "speech",
                text,
                picture,
                adjacent,
                0.0,
                f"different words (at most {text:.3f} < {cfg.text_min:g})",
            )
        if picture is not None and picture < cfg.picture_min_with_text:
            return Pair(
                i,
                j,
                "speech",
                text,
                picture,
                adjacent,
                0.0,
                f"same words, other picture ({picture:.2f} < {cfg.picture_min_with_text:g})",
            )
        parts = {"text": text, "picture": picture, "adjacent": adjacent}
        score = _mean(parts, cfg.pair_weights) or 0.0
        why = f"same words ({text:.2f})"
        if score < cfg.group_min:
            why += f" but pair score {score:.2f} < {cfg.group_min:g}"
        return Pair(i, j, "speech", text, picture, adjacent, score, why)
    if picture is None:
        return Pair(i, j, "none", None, None, adjacent, 0.0, "no picture vectors to compare")
    if picture < cfg.picture_min:
        return Pair(
            i,
            j,
            "picture",
            None,
            picture,
            adjacent,
            0.0,
            f"pictures differ ({picture:.2f} < {cfg.picture_min:g})",
        )
    if adjacent <= 0:
        return Pair(
            i, j, "picture", None, picture, adjacent, 0.0, f"more than {cfg.max_apart} shots apart"
        )
    score = _mean({"picture": picture, "adjacent": adjacent}, cfg.pair_weights_picture) or 0.0
    why = f"same picture ({picture:.2f})"
    if score < cfg.group_min:
        why += f" but pair score {score:.2f} < {cfg.group_min:g}"
    return Pair(i, j, "picture", None, picture, adjacent, score, why)


def all_pairs(infos: Sequence[ShotInfo], cfg: TakesConfig) -> dict[tuple[int, int], Pair]:
    return {
        (i, j): pair(i, j, infos, cfg) for i in range(len(infos)) for j in range(i + 1, len(infos))
    }


def group(
    infos: Sequence[ShotInfo],
    cfg: TakesConfig,
    apart: Collection[frozenset[str]] = (),
    pairs: dict[tuple[int, int], Pair] | None = None,
) -> tuple[list[list[int]], dict[tuple[int, int], Pair]]:
    """Groups of two or more shots (indexes into `infos`, in project order), and every pair."""
    pairs = all_pairs(infos, cfg) if pairs is None else pairs
    linked = [(i, j) for (i, j), p in pairs.items() if p.score >= cfg.group_min]
    # Only shots linked to another can end up in a group; group each connected part on its own.
    parent = list(range(len(infos)))

    def root(k: int) -> int:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for i, j in linked:
        parent[root(i)] = root(j)
    parts: dict[int, list[int]] = {}
    for i, j in linked:
        for k in (i, j):
            members = parts.setdefault(root(k), [])
            if k not in members:
                members.append(k)
    groups: list[list[int]] = []
    for members in parts.values():
        members.sort()
        if len(members) == 2:
            kept = frozenset((infos[members[0]].id, infos[members[1]].id)) not in apart
            groups.extend([members] if kept else [])
            continue
        distance = np.ones((len(members), len(members)))
        np.fill_diagonal(distance, 0.0)
        for x, i in enumerate(members):
            for y in range(x + 1, len(members)):
                j = members[y]
                d = (
                    APART
                    if frozenset((infos[i].id, infos[j].id)) in apart
                    else 1 - pairs[(i, j)].score
                )
                distance[x, y] = distance[y, x] = d
        labels = AgglomerativeClustering(
            n_clusters=None,
            metric="precomputed",
            linkage="average",
            distance_threshold=1 - cfg.group_min + 1e-9,
        ).fit_predict(distance)
        by_label: dict[int, list[int]] = {}
        for x, label in enumerate(labels):
            by_label.setdefault(int(label), []).append(members[x])
        groups.extend(g for g in by_label.values() if len(g) > 1)
    groups.sort(key=lambda g: g[0])
    return groups, pairs


def _flubs(info: ShotInfo, cfg: TakesConfig) -> tuple[float, list[str]]:
    """How clean the take is (1 = no problem found) and what was found."""
    notes: list[str] = []
    fillers = sum(1 for w in info.norm if w in cfg.fillers)
    repeats = sum(
        1 for x, y in zip(info.norm, info.norm[1:], strict=False) if x == y and x not in cfg.fillers
    )
    if repeats:
        notes.append(f"{repeats} repeated word(s)")
    if fillers:
        notes.append(f"{fillers} filler word(s)")
    if info.uncertain:
        notes.append(f"{info.uncertain} unclear transcript line(s)")
    cut = 0
    if info.words and info.words[0].start_s - info.start_s < cfg.edge_s:
        cut += 1
        notes.append("speech starts at the first frame (cut off?)")
    if info.words and info.end_s - info.words[-1].end_s < cfg.edge_s:
        cut += 1
        notes.append("speech runs to the last frame (cut off?)")
    clean = 1 - 0.25 * (repeats + fillers + info.uncertain) - 0.5 * cut
    return round(max(0.0, clean), 4), notes


def _complete(take: Sequence[str], reference: Sequence[str]) -> float:
    if not reference:
        return 0.0
    blocks = SequenceMatcher(
        None, list(reference), list(take), autojunk=False
    ).get_matching_blocks()
    return round(sum(b.size for b in blocks) / len(reference), 4)


def rank_takes(
    members: Sequence[int],
    infos: Sequence[ShotInfo],
    pairs: dict[tuple[int, int], Pair],
    cfg: TakesConfig,
    user_best: str | None = None,
) -> tuple[str, list[Ranked], str]:
    """(kind, members best first, how the best was chosen: auto | you | none)."""
    speaking = [i for i in members if has_speech(infos[i], cfg)]
    kind = "speech" if len(speaking) >= 2 else "picture"
    reference: tuple[str, ...] = ()
    if kind == "speech":
        # The most typical take: the highest mean word similarity to the others who speak.
        def typical(i: int) -> float:
            sims = [pairs[(min(i, j), max(i, j))].text or 0.0 for j in speaking if j != i]
            return sum(sims) / len(sims)

        reference = infos[max(speaking, key=lambda i: (typical(i), -i))].norm
    ranked: list[Ranked] = []
    for i in members:
        info = infos[i]
        signals: dict[str, float | None] = {
            "focus": info.focus,
            "exposure": info.exposure,
            "audio": info.audio,
        }
        notes: list[str] = []
        if kind == "speech":
            signals["complete"] = _complete(info.norm, reference) if info.norm else 0.0
            if not info.norm:
                signals["clean"] = None
                notes.append("no clear speech found")
            else:
                signals["clean"], found = _flubs(info, cfg)
                notes.extend(found)
            weights = cfg.best_weights
        else:
            weights = cfg.best_weights_picture
        if info.focus is None:
            notes.append("focus not measured")
        if info.rejected:
            notes.append("rejected by you")
        ranked.append(Ranked(info, _mean(signals, weights), signals, notes))

    def order(r: Ranked) -> tuple[Any, ...]:
        return (
            r.info.rejected,
            r.info.id != user_best,
            r.score is None,
            -(r.score or 0.0),
            r.info.position,
        )

    ranked.sort(key=order)
    top = ranked[0]
    if top.info.rejected:
        best_by = "none"
    elif top.info.id == user_best:
        best_by = "you"
    else:
        best_by = "auto"
    return kind, ranked, best_by
