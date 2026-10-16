"""Schemas of the screenplay, its lines and their takes (SPEC P1-A)."""

from datetime import datetime

from pydantic import BaseModel, Field

from cinemind.api.timeline_schemas import Name


class ScriptIn(BaseModel):
    name: Name = "Script"
    # Fountain or plain text (one line per row, optionally NAME: words).
    text: str = Field(min_length=1, max_length=1_000_000)


class TakeOut(BaseModel):
    id: str
    media_id: str
    filename: str
    rank: int
    start_s: float
    end_s: float
    text: str
    lexical: float
    semantic: float | None
    score: float


class ScriptLineOut(BaseModel):
    id: str
    index: int
    kind: str
    character: str | None
    scene: str | None
    text: str
    choice: str  # auto | take | not_filmed
    chosen_take_id: str | None
    why: str  # why that take (or none) is used
    takes: list[TakeOut]


class AlignmentOut(BaseModel):
    """How the last alignment ran (rule 6)."""

    at: str | None = None
    text_model: str | None = None  # None: words only
    semantic: bool = False
    lexical_weight: float = 1.0
    semantic_weight: float = 0.0
    limit: float = 0.0
    segments: int = 0  # transcript lines searched (those not marked uncertain)
    dialogue_lines: int = 0
    found: int = 0


class ScriptOut(BaseModel):
    id: str
    project_id: str
    name: str
    format: str
    created_at: datetime
    alignment: AlignmentOut
    min_score: float
    dialogue_lines: int
    with_take: int
    lines: list[ScriptLineOut]


class TakeChoice(BaseModel):
    # A take id; or null with not_filmed false = back to the best match.
    take_id: str | None = Field(default=None, min_length=1)
    not_filmed: bool = False


class ScriptCutCreate(BaseModel):
    name: Name | None = None
    fps: tuple[int, int] | None = None
