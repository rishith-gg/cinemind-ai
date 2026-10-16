"""Reading a screenplay (SPEC P1-A): Fountain (https://fountain.io) or plain text.

Fountain, the parts that matter here: scene headings (INT. / EXT. / EST. / I/E, or forced with
a leading "."), character cues (a line in capitals followed by dialogue; "@" forces one; "(V.O.)"
and "(CONT'D)" are dropped from the name), dialogue (parentheticals skipped), and action. Title
page, notes [[...]], boneyard /* ... */, sections (#), synopses (=), transitions ("CUT TO:",
"> ...") and page breaks are skipped.

Plain text, used when Fountain finds no dialogue or fewer speakers' lines than "NAME: words"
rows: "NAME: words" is a line of NAME ("Scene 1:", "Note:" and the like are not names), a scene
heading is a heading, any other non-empty line is a line without a character.
"""

import re
from dataclasses import dataclass

from cinemind.core.errors import InvalidInputError

MAX_CHARS = 1_000_000
MAX_LINES = 5000

_TITLE_KEY = re.compile(
    r"^(title|credit|authors?|source|draft date|date|contact|copyright|notes|revision)\s*:",
    re.IGNORECASE,
)
_SCENE = re.compile(r"^(?:int|ext|est|int\.?/ext|ext\.?/int|i/e)[. ]", re.IGNORECASE)
_SCENE_NUMBER = re.compile(r"\s*#[^#\s]*#\s*$")
_EXTENSION = re.compile(r"\s*\([^)]*\)\s*$")
_PLAIN_CUE = re.compile(r"^([A-Za-z][\w .'-]{0,39}):\s+(\S.*)$")
# Words before a colon that are not a character ("Scene 1: kitchen", "Note: ...").
_NOT_NAMES = {"scene", "note", "notes", "title", "credit", "author", "draft", "page", "act"}


@dataclass(frozen=True)
class ParsedLine:
    kind: str  # scene | action | dialogue
    text: str
    character: str | None = None
    scene: str | None = None


def _clean(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)  # boneyard
    text = re.sub(r"\[\[.*?\]\]", "", text, flags=re.DOTALL)  # notes
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _without_title(text: str) -> list[str]:
    """The script's lines without a title page (key: value lines up to the first blank line)."""
    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and _TITLE_KEY.match(lines[0].strip()):
        while lines and lines[0].strip():
            lines.pop(0)
    return lines


def _heading(line: str) -> str:
    return _SCENE_NUMBER.sub("", line.lstrip(".")).strip()


def _paragraphs(text: str) -> list[list[str]]:
    lines = _without_title(text)
    found: list[list[str]] = []
    current: list[str] = []
    for raw in lines:
        line = raw.strip()
        if line:
            current.append(line)
        elif current:
            found.append(current)
            current = []
    if current:
        found.append(current)
    return found


def _name(cue: str) -> str:
    """The character in a cue: without "@", the dual-dialogue "^" and "(V.O.)"-style extensions."""
    return _EXTENSION.sub("", cue.lstrip("@").rstrip("^ ").strip()).strip()


def _spoken(lines: list[str]) -> list[str]:
    """Dialogue lines without parentheticals, also those running over several lines."""
    words: list[str] = []
    inside = False
    for line in lines:
        if line.startswith("("):
            inside = True
        if not inside:
            words.append(line)
        if inside and line.endswith(")"):
            inside = False
    return words


def _is_cue(line: str) -> bool:
    if line.startswith("@"):
        return True
    name = _name(line)
    return bool(name) and any(c.isalpha() for c in name) and name == name.upper()


def _fountain(paragraphs: list[list[str]]) -> list[ParsedLine]:
    found: list[ParsedLine] = []
    scene: str | None = None
    for para in paragraphs:
        first = para[0]
        if first.startswith(("#", "=")) or first == "===":
            continue
        forced = first.startswith(".") and not first.startswith("..") and len(para) == 1
        if _SCENE.match(first) or forced:
            # A heading typed without a blank line after it still is one; the rest is action.
            scene = _heading(first)
            found.append(ParsedLine("scene", scene, scene=scene))
            if len(para) > 1:
                found.append(ParsedLine("action", " ".join(para[1:]), scene=scene))
            continue
        if (
            first.startswith(">")
            and not first.endswith("<")
            or (first == first.upper() and first.endswith("TO:"))
        ):
            continue  # transition
        if len(para) > 1 and not first.startswith("!") and _is_cue(first):
            character = _name(first)
            words = _spoken(para[1:])
            if words:
                found.append(ParsedLine("dialogue", " ".join(words), character, scene))
            continue
        text = " ".join(line.lstrip("!").strip("<> ") for line in para)
        found.append(ParsedLine("action", text, scene=scene))
    return found


def _plain(text: str) -> list[ParsedLine]:
    found: list[ParsedLine] = []
    scene: str | None = None
    for raw in _without_title(text):
        line = raw.strip()
        if not line:
            continue
        if _SCENE.match(line):
            scene = _heading(line)
            found.append(ParsedLine("scene", scene, scene=scene))
            continue
        cue = _PLAIN_CUE.match(line)
        if cue and cue.group(1).split()[0].lower() not in _NOT_NAMES:
            found.append(ParsedLine("dialogue", cue.group(2).strip(), cue.group(1).strip(), scene))
        else:
            found.append(ParsedLine("dialogue", line, scene=scene))
    return found


def parse(text: str) -> tuple[str, list[ParsedLine]]:
    """The format ("fountain" or "plain") and the lines, in script order."""
    if len(text) > MAX_CHARS:
        raise InvalidInputError("The script is too long (more than a million characters).")
    text = _clean(text)
    fountain = _fountain(_paragraphs(text))
    plain = _plain(text)
    # Fountain when it finds dialogue and at least as many speakers' lines as "NAME: words" rows
    # would give (a capitalised title above NAME: rows must not become one long speech).
    spoken = sum(1 for line in fountain if line.kind == "dialogue")
    named = sum(1 for line in plain if line.kind == "dialogue" and line.character)
    structured = any(line.kind == "scene" for line in fountain)
    if (spoken and spoken >= named) or (structured and not named):
        fmt, lines = "fountain", fountain  # a scene heading with only action has no dialogue
    else:
        fmt, lines = "plain", plain
    if not any(line.kind == "dialogue" for line in lines):
        raise InvalidInputError(
            "No dialogue was found in the script. Use Fountain (a character name in capitals "
            "above each line) or one line per row, optionally as NAME: words."
        )
    if len(lines) > MAX_LINES:
        raise InvalidInputError(f"The script has more than {MAX_LINES} lines; split it up.")
    return fmt, lines
