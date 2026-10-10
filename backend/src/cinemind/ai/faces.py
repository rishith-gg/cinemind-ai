"""Finding faces and turning them into vectors, with OpenCV's YuNet and SFace models.

Existing models: YuNet (detector) and SFace (128-number face vector), run by OpenCV. Ours: the
checks that decide whether a found face is good enough to use, the download that keeps models
out of processing (fetched once by `cinemind models pull`, afterwards only read from disk), and
the crop kept for the Actors page.
"""

# OpenCV images and model outputs are untyped arrays.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

import hashlib
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from cinemind.core.errors import ModelMissingError
from cinemind.core.face_config import DETECTOR, EMBEDDER, FACE_MODELS, FaceConfig, models_ready

log = logging.getLogger(__name__)

PULL_HINT = "Run `uv run cinemind models pull` once (needs internet), then press Reprocess."
# Below this detector confidence a box is not counted as a face at all (the detector's range is
# 0..1; OpenCV's own default is 0.9, we look lower so the report can say what was left out).
DETECT_FLOOR = 0.6
_NMS, _TOP_K = 0.3, 5000  # OpenCV's defaults
REJECT_REASONS = ("low_score", "small", "turned", "blurry")
CROP_SIDE = 160
_CROP_MARGIN = 0.35
_JPEG_QUALITY = 88


@dataclass
class Found:
    """One box the detector returned. `vector` is set only if every check passed (`reason` is
    then None); it has length 1."""

    box: tuple[float, float, float, float]  # x, y, w, h in pixels
    score: float
    size_px: float
    turn: float
    sharpness: float | None
    reason: str | None
    vector: Any = None


def engine_version() -> str:
    return f"opencv-{cv2.__version__}"


def pull(models_root: Path) -> None:
    """Download both pinned model files and check them (setup time only; needs internet)."""
    from huggingface_hub import hf_hub_download

    for spec in FACE_MODELS:
        target = spec.path(models_root)
        if target.is_file():
            continue
        partial = target.parent / (target.name + ".partial")
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        try:
            got = Path(
                hf_hub_download(
                    spec.repo, spec.filename, revision=spec.revision, local_dir=str(partial)
                )
            )
            digest = hashlib.sha256(got.read_bytes()).hexdigest()
            if digest != spec.sha256:
                raise ModelMissingError(
                    f"The download of '{spec.filename}' does not match its checksum. Try again."
                )
            got.replace(target)
        finally:
            shutil.rmtree(partial, ignore_errors=True)


def turn_of(landmarks: Any) -> float:
    """How far the nose sits from the middle of the eyes, measured along the eye line in eye
    distances: about 0 for a frontal face, growing as the head turns to a profile."""
    right_eye, left_eye, nose = landmarks[0:2], landmarks[2:4], landmarks[4:6]
    axis = left_eye - right_eye
    distance = float(np.linalg.norm(axis))
    if distance < 1e-6:
        return 9.0
    middle = (left_eye + right_eye) / 2
    return abs(float(np.dot(nose - middle, axis / distance))) / distance


class FaceEngine:
    """Loaded detector and embedder. Raises ModelMissingError if the files are not on disk."""

    def __init__(self, models_root: Path) -> None:
        if not models_ready(models_root):
            raise ModelMissingError(f"The face models are not downloaded. {PULL_HINT}")
        self._detector = cv2.FaceDetectorYN.create(
            str(DETECTOR.path(models_root)), "", (320, 320), DETECT_FLOOR, _NMS, _TOP_K
        )
        self._embedder = cv2.FaceRecognizerSF.create(str(EMBEDDER.path(models_root)), "")
        self._size = (0, 0)

    def find(self, image: Any, cfg: FaceConfig) -> list[Found]:
        """Every face in a BGR image, each with the first check it failed (if any)."""
        height, width = image.shape[:2]
        if (width, height) != self._size:
            self._detector.setInputSize((width, height))
            self._size = (width, height)
        _, rows = self._detector.detect(image)
        found: list[Found] = []
        for row in rows if rows is not None else []:
            x, y = max(0.0, float(row[0])), max(0.0, float(row[1]))
            w = min(float(row[0] + row[2]), width) - x
            h = min(float(row[1] + row[3]), height) - y
            if w <= 1 or h <= 1:
                continue
            face = Found((x, y, w, h), float(row[14]), min(w, h), turn_of(row[4:14]), None, None)
            if face.score < cfg.min_score:
                face.reason = "low_score"
            elif face.size_px < cfg.min_size_px:
                face.reason = "small"
            elif face.turn > cfg.max_turn:
                face.reason = "turned"
            else:
                aligned = self._embedder.alignCrop(image, row)
                gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
                face.sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                if face.sharpness < cfg.min_sharpness:
                    face.reason = "blurry"
                else:
                    vector = self._embedder.feature(aligned).reshape(-1).astype(np.float32)
                    norm = float(np.linalg.norm(vector))
                    if norm < 1e-6:
                        face.reason = "blurry"
                    else:
                        face.vector = vector / norm
            found.append(face)
        return found


def crop_jpeg(image: Any, box: tuple[float, float, float, float]) -> bytes:
    """The face with some margin around it, as a small JPEG for the Actors page."""
    height, width = image.shape[:2]
    x, y, w, h = box
    side = max(w, h) * (1 + 2 * _CROP_MARGIN)
    cx, cy = x + w / 2, y + h / 2
    left, top = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
    right, bottom = int(min(width, cx + side / 2)), int(min(height, cy + side / 2))
    part = image[top:bottom, left:right]
    scale = CROP_SIDE / max(part.shape[0], part.shape[1], 1)
    size = (max(1, round(part.shape[1] * scale)), max(1, round(part.shape[0] * scale)))
    small = cv2.resize(part, size, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    ok, data = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
    if not ok:  # pragma: no cover - encoding an in-memory BGR image does not fail in practice
        raise RuntimeError("could not encode a face crop")
    return data.tobytes()
