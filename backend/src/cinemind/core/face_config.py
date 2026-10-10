"""Face settings (settings section `[faces]`) and the two face models the app knows.

Existing models, from the OpenCV model zoo: YuNet finds faces (MIT licence), SFace turns a face
into a 128-number vector (Apache 2.0). Each is pinned to a repository revision and checked
against a SHA-256 after download. Repositories, revisions, sizes and checksums were read from
the Hugging Face model index on 2026-10-10.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, model_validator


@dataclass(frozen=True)
class FaceModelFile:
    repo: str
    revision: str
    filename: str
    sha256: str
    size_kb: int

    def path(self, models_root: Path) -> Path:
        """A new revision gets a new file name, so an old download is never mistaken for it."""
        stem, _, suffix = self.filename.rpartition(".")
        return models_root / "faces" / f"{stem}-{self.revision[:12]}.{suffix}"


ENGINE = "yunet-sface"
DETECTOR = FaceModelFile(
    "opencv/face_detection_yunet",
    "3cc26e7f1014a5ee5d74a42acee58bafc9d0a310",
    "face_detection_yunet_2023mar.onnx",
    "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    228,
)
EMBEDDER = FaceModelFile(
    "opencv/face_recognition_sface",
    "3d7082438a6e4551e840c9b2bb60b71e8da4b524",
    "face_recognition_sface_2021dec.onnx",
    "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    37790,
)
FACE_MODELS = (DETECTOR, EMBEDDER)
EMBEDDING_DIM = 128


def models_ready(models_root: Path) -> bool:
    return all(spec.path(models_root).is_file() for spec in FACE_MODELS)


class FaceConfig(BaseModel):
    # Frames per second of video that are searched for faces.
    sample_fps: float = 2.0
    # A found face is used only if it passes all four checks below. They are conventions, not
    # limits we evaluated: SFace reads a 112 px crop, so much smaller faces carry little detail.
    min_score: float = 0.8  # the detector's own confidence
    min_size_px: int = 40  # shorter side of the face box, on the analysis proxy
    min_sharpness: float = 20.0  # variance of the Laplacian of the aligned 112 px crop
    # How far the nose may sit from the middle of the eyes, in eye distances (0 = frontal).
    max_turn: float = 0.6
    # Tracking inside a shot. `track_similarity` is the SFace authors' cosine threshold for
    # "same person"; a box that overlaps the previous one this much needs only half of it.
    track_similarity: float = 0.363
    track_overlap: float = 0.5
    track_max_gap_s: float = 2.0
    # Grouping tracks into people: average-linkage cosine distance below which two groups merge.
    # Used by the agglomerative method only (HDBSCAN finds its own density levels). The default
    # was confirmed, not found, by eval/face_clusters.py on single photos (EVALUATION.md section 6).
    cluster_method: Literal["agglomerative", "hdbscan"] = "agglomerative"
    cluster_distance: float = 0.6

    @model_validator(mode="after")
    def _ranges(self) -> Self:
        if not 0.1 <= self.sample_fps <= 30:
            raise ValueError("faces.sample_fps must be between 0.1 and 30")
        for name in ("min_score", "track_similarity", "track_overlap"):
            if not 0 < getattr(self, name) < 1:
                raise ValueError(f"faces.{name} must be between 0 and 1")
        if not 0 < self.cluster_distance < 2:
            raise ValueError("faces.cluster_distance must be between 0 and 2")
        if self.min_size_px < 8 or self.min_sharpness < 0 or self.max_turn <= 0:
            raise ValueError("faces.min_size_px, min_sharpness and max_turn must be positive")
        if self.track_max_gap_s <= 0:
            raise ValueError("faces.track_max_gap_s must be positive")
        return self
