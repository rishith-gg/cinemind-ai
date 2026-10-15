"""API schemas for scenes, tags and vector indexes (Phase 8)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EmbedStatus = Literal["pending", "done", "no_video", "no_speech", "no_transcript", "model_missing"]
TagStatus = Literal["shown", "below", "disabled", "not_evaluated"]
TagDecision = Literal["approved", "rejected"]
TagSource = Literal["model", "faces", "transcript"]
BoundaryDecision = Literal["split", "join", "auto"]


class SceneShotOut(BaseModel):
    shot_id: str
    media_id: str
    filename: str
    index: int
    start_s: float
    end_s: float
    keyframe_id: str | None
    # Compared with the shot before it (None for the first shot of the project, or a signal
    # missing on either side): cosine of the picture vectors, colour histogram intersection,
    # and their weighted mean.
    visual: float | None
    color: float | None
    combined: float | None
    # Why this shot starts a scene or stays with the one before, in plain words.
    decision: str
    # The user's edit before this shot, if any.
    edit: Literal["split", "join"] | None
    # The user's verdict on the shot: select / reject / none, and 0..5 stars.
    mark: Literal["select", "reject"] | None = None
    stars: int = 0


class SceneOut(BaseModel):
    id: str
    index: int
    name: str
    named: bool
    shot_count: int
    duration_s: float
    shots: list[SceneShotOut]


class SceneSettingsOut(BaseModel):
    join_similarity: float
    visual_weight: float
    color_weight: float


class ScenesOut(BaseModel):
    scenes: list[SceneOut]
    # Shots that arrived after the last grouping (grouping runs when processing is done).
    ungrouped: list[SceneShotOut]
    grouped_at: datetime | None
    # Model, settings, order, counts of the last grouping (rule 6).
    details: dict[str, Any]
    settings: SceneSettingsOut
    # True when the picture model is not downloaded: scenes then cannot be compared.
    model_missing: bool
    message: str | None


class BoundaryIn(BaseModel):
    shot_id: str = Field(min_length=1, max_length=32)
    decision: BoundaryDecision


class SceneRename(BaseModel):
    name: str = Field(max_length=200)


class TagOut(BaseModel):
    name: str
    label: str
    group: str
    group_label: str
    source: TagSource
    score: float | None
    threshold: float | None
    status: TagStatus
    review: TagDecision | None
    # What the user sees as a tag: approved, or shown by its threshold and not rejected.
    visible: bool
    # Model, revision, per-keyframe scores, the evaluation behind the threshold, top places.
    details: dict[str, Any]


class ShotTagsOut(BaseModel):
    shot_id: str
    index: int
    start_s: float
    end_s: float
    tags: list[TagOut]


class MediaTagsOut(BaseModel):
    status: EmbedStatus
    model: str | None
    message: str | None
    # When the thresholds in use were set, and the results file they came from.
    calibrated: str | None
    calibration_source: str | None
    shots: list[ShotTagsOut]


class TagReviewIn(BaseModel):
    shot_id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    decision: TagDecision | Literal["none"]


class TagCountOut(BaseModel):
    name: str
    label: str
    group: str
    shots: int


class VectorIndexOut(BaseModel):
    kind: str
    model: str
    backend: str
    dim: int
    count: int
    built_at: datetime
    up_to_date: bool


class EmbeddingStatusOut(BaseModel):
    kind: Literal["visual", "text"]
    status: EmbedStatus
    model: str | None
    count: int
    message: str | None
