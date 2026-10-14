"""API schemas for faces and actors."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

FaceScanStatus = Literal["pending", "done", "no_faces", "no_video", "model_missing"]
TrackState = Literal["auto", "pinned", "ignored", "unknown", "brief"]


class FaceTrackOut(BaseModel):
    id: str
    media_id: str
    filename: str
    start_s: float
    end_s: float
    face_count: int
    crop_url: str
    actor_id: str | None
    actor_name: str | None
    # auto = grouped by similarity; pinned = placed by the user; ignored = "not a face";
    # unknown = a person the user does not want to name; brief = seen in too few sampled frames
    # to group (set aside automatically, `[faces] min_track_faces`).
    state: TrackState
    # Why it sits where it does: `how` (similar faces / placed by you / kept with this person by
    # your correction / set aside by you) and, when grouped by similarity, the similarity to the
    # group, the method and (agglomerative only) the distance used.
    assignment: dict[str, Any]


class ActorOut(BaseModel):
    id: str
    project_id: str
    number: int
    name: str
    # True once the user chose the name ("Actor 001" style names are automatic).
    named: bool
    tracks: int
    faces: int
    clips: int
    # Seconds the person's tracks cover (tracks of one person in one clip can overlap in time
    # only by mistake, so this is a plain sum).
    seen_s: float
    crop_url: str | None


class ActorDetail(ActorOut):
    track_list: list[FaceTrackOut]


class ActorsOut(BaseModel):
    actors: list[ActorOut]
    ignored: int
    unknown: int
    # Faces set aside automatically because they were on screen too briefly.
    brief: int
    # Clips per face-scan state, e.g. {"done": 12, "no_faces": 5, "model_missing": 0}.
    scans: dict[str, int]
    # Plain-language note when faces are missing for a reason the user can fix.
    message: str | None
    # The last grouping: engine, method, distance, counts (None before the first one).
    run: dict[str, Any] | None
    clustered_at: datetime | None


class MediaFacesOut(BaseModel):
    media_id: str
    status: FaceScanStatus
    message: str | None
    frames_sampled: int
    faces_detected: int
    faces_used: int
    max_in_frame: int
    # Models, settings and how many faces each check left out.
    details: dict[str, Any]
    tracks: list[FaceTrackOut]


class ActorRename(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ActorMerge(BaseModel):
    # The people merged into the actor in the URL.
    actor_ids: list[str] = Field(min_length=1, max_length=200)


class TrackSelection(BaseModel):
    track_ids: list[str] = Field(min_length=1, max_length=2000)


class TrackPlacement(TrackSelection):
    # actor = move to `actor_id`; ignored = not a face; unknown = a person not worth naming;
    # auto = hand back to automatic grouping.
    state: Literal["actor", "ignored", "unknown", "auto"]
    actor_id: str | None = None


class ActorPairOut(BaseModel):
    """Two people the grouping kept apart although their faces look alike."""

    first: ActorOut
    second: ActorOut
    # Average-linkage distance of their tracks (mean of 1 - cosine similarity); the grouping
    # joins two groups below `[faces] cluster_distance`.
    distance: float


class ActorPairsOut(BaseModel):
    pairs: list[ActorPairOut]
    # The limit the grouping uses now (None with HDBSCAN, which has no fixed limit).
    cluster_distance: float | None
    # How many questions the user answered so far, and how many of them were "same person".
    answered: int
    answered_same: int


class ActorPairAnswerIn(BaseModel):
    first_id: str
    second_id: str
    same: bool
