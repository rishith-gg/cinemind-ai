"""Reading a rough cut brief with rules (SPEC section 11: "rules + optional local LLM, never
required"; the LLM provider is `none`, so rules are all there is).

From "2-minute sequence about the grandfather walking home at night" the rules take the length
(2 minutes), an order if one is named ("in order", "by scene", "best first"), and what to look
for: the brief without the length, the order and framing words ("sequence about"), which goes
to hybrid search as typed. Everything the rules took is listed in `understood`, so the page can
show how the brief was read."""

import re
from dataclasses import dataclass, field

from cinemind.core.rough_cut_config import Order

_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30,
    "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90, "half a": 0.5,
}  # fmt: skip


def _num(name: str) -> str:
    """A number of at most three digits (so "1990s" is never a length) or a number word."""
    words = "|".join(sorted(map(re.escape, _NUMBER_WORDS), key=len)[::-1])
    return rf"\b(?P<{name}>\d{{1,3}}(?:\.\d+)?|{words})(?![\d:])"


# Units are spelled out ("sec", "min" and longer): a bare "s" would read "the 90s" as 90 seconds.
_MIN = r"[\s-]*(?:minutes?|mins?)\b"
_SEC = r"[\s-]*(?:seconds?|secs?)\b"
_LENGTH = re.compile(
    rf"{_num('m')}{_MIN}(?:\s*(?:and\s+)?{_num('ms')}{_SEC})?|{_num('s')}{_SEC}", re.IGNORECASE
)
# m:ss only as the whole start of the brief or followed by "long" ("1:30 long"); "home at 9:30"
# is a time of day.
_CLOCK = re.compile(
    r"^\s*(?P<m>\d{1,2}):(?P<s>[0-5]\d)\b|\b(?P<m2>\d{1,2}):(?P<s2>[0-5]\d)\s+(?:long|runtime)\b",
    re.IGNORECASE,
)
_ORDERS: list[tuple[re.Pattern[str], Order, str]] = [
    (re.compile(r"\b(?:in )?(?:chronological|time|shooting|source) order\b|\bchronologically\b|"
                r"\bin order\b", re.IGNORECASE), "chronological", "in source order"),
    (re.compile(r"\b(?:by|per) scenes?\b|\bscene by scene\b", re.IGNORECASE), "scene",
     "grouped by scene"),
    (re.compile(r"\bbest (?:shots? )?first\b|\bby (?:score|rank(?:ing)?)\b", re.IGNORECASE),
     "score", "best first"),
]  # fmt: skip
# Words that frame the request rather than describe footage, dropped from the search text.
_FRAMING = re.compile(
    r"^\s*(?:please\s+)?(?:(?:make|create|build|cut|edit|give me|i want|i need)\b\s*)?"
    r"(?:me\s+)?(?:an?\s+)?(?:(?:long|short|quick)\s+)?"
    r"(?:(?:rough[\s-]?cuts?|sequences?|edits?|montages?|videos?|reels?|films?|cuts?|story|"
    r"stories|clips?)\b\s*)?"
    r"(?:(?:about|of|showing|with|on|that shows|where)\b\s*)?",
    re.IGNORECASE,
)
_LEFTOVER = re.compile(r"^(?:long|of|about|with|and|,|-)\s+|\s+(?:of|and|with|,|-)$", re.IGNORECASE)


@dataclass
class Brief:
    text: str
    query: str  # what is searched for; empty = no subject, every usable shot is a candidate
    target_s: float | None = None
    order: Order | None = None
    understood: list[str] = field(default_factory=lambda: [])


def _number(word: str) -> float:
    word = word.lower()
    return _NUMBER_WORDS[word] if word in _NUMBER_WORDS else float(word)


def _length(text: str) -> tuple[float | None, str]:
    """The first length named in the brief, in seconds, and the brief without it. Only the first
    is taken: in "a 2 minute cut of 3 second shots" the second is about the shots."""
    match = _LENGTH.search(text)
    if match:
        if match.group("m"):
            total = _number(match.group("m")) * 60
            total += _number(match.group("ms")) if match.group("ms") else 0
        else:
            total = _number(match.group("s"))
    else:
        match = _CLOCK.search(text)
        if not match:
            return None, text
        minutes, seconds = (
            match.group("m") or match.group("m2"),
            match.group("s") or match.group("s2"),
        )
        total = int(minutes) * 60 + int(seconds)
    rest = text[: match.start()] + " " + text[match.end() :]
    return (total if total > 0 else None), rest


def _tidy(text: str) -> str:
    text = " ".join(text.split())
    while True:
        tidied = _LEFTOVER.sub("", _FRAMING.sub("", text, count=1)).strip(" ,.-")
        if tidied == text:
            return text
        text = tidied


def parse(text: str) -> Brief:
    brief = Brief(text=text.strip(), query="")
    target, rest = _length(brief.text)
    if target is not None:
        brief.target_s = target
        brief.understood.append(f"length: {target:g} s")
    for pattern, order, label in _ORDERS:
        if pattern.search(rest):
            brief.order = order
            brief.understood.append(f"order: {label}")
            rest = pattern.sub(" ", rest)
            break
    brief.query = _tidy(rest)
    if brief.query:
        brief.understood.append(f"looking for: {brief.query}")
    else:
        brief.understood.append("no subject named: every usable shot is a candidate")
    return brief
