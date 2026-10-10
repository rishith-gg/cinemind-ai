"""Faces in one clip: sample frames of the analysis proxy, find and check faces, and follow each
face through its shot (a "track"). Ours: the sampling, the tracking rule and what is kept.

Tracking rule: inside one shot, a face in the next sampled frame continues a track when its
vector is similar enough to the track's mean vector (the SFace authors' same-person threshold),
or half as similar while its box still overlaps the track's last box. Each frame's faces are
matched to the open tracks one to one (best total similarity), so two faces in one frame never
share a track. A track ends at the shot's end or after `track_max_gap_s` without a match.
"""

# OpenCV images are untyped arrays.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

import shutil
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

from cinemind.ai.faces import REJECT_REASONS, FaceEngine, Found, crop_jpeg
from cinemind.core.errors import UnreadableMediaError
from cinemind.core.face_config import EMBEDDING_DIM, FaceConfig

TRACKS_FILE = "tracks.npy"
_CHUNK_FRAMES = 240  # frames between progress/cancel checks
_REFERENCE_FACE_PX = 112  # the size SFace reads; a larger face adds no detail
_MISSING_FRAMES = 0.02  # share of frames the proxy may fall short of what shot detection counted


def overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Intersection over union of two (x, y, w, h) boxes."""
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    inter = max(0.0, right - left) * max(0.0, bottom - top)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


@dataclass(eq=False)
class _Track:
    shot: int
    total: Any  # sum of the face vectors
    box: tuple[float, float, float, float]
    last_frame: int
    faces: list[int] = field(default_factory=lambda: [])
    best: int = -1
    best_quality: float = -1.0
    crop: bytes = b""

    @property
    def mean(self) -> Any:
        return self.total / max(float(np.linalg.norm(self.total)), 1e-9)


def match(tracks: list[_Track], faces: list[Found], cfg: FaceConfig) -> dict[int, int]:
    """Face index -> track index for the faces that continue an open track."""
    if not tracks or not faces:
        return {}
    similarity = np.stack([f.vector for f in faces]) @ np.stack([t.mean for t in tracks]).T
    allowed = similarity >= cfg.track_similarity
    for i, face in enumerate(faces):
        for j, track in enumerate(tracks):
            if not allowed[i, j] and similarity[i, j] >= cfg.track_similarity / 2:
                allowed[i, j] = overlap(face.box, track.box) >= cfg.track_overlap
    # Pairs that may not be linked cost nothing, so the solver gains only from allowed ones:
    # the highest total similarity wins, not the largest number of links.
    rows, cols = linear_sum_assignment(np.where(allowed, -similarity, 0.0))
    return {int(i): int(j) for i, j in zip(rows, cols, strict=True) if allowed[i, j]}


def scan(
    video: Path,
    fps: Fraction,
    shots: list[tuple[int, int]],
    cfg: FaceConfig,
    engine: FaceEngine,
    out_dir: Path,
    progress: Callable[[float], None],
    check_cancelled: Callable[[], None],
) -> dict[str, Any]:
    """Scan `video` and write one crop per track plus the track vectors into `out_dir`
    (replaced atomically). Returns counts, the used faces and the tracks."""
    step = max(1, round(float(fps) / cfg.sample_fps))
    gap_frames = round(cfg.track_max_gap_s * float(fps))
    starts = [start for start, _ in shots]
    last_frame = shots[-1][1] if shots else 0
    rejected: dict[str, int] = dict.fromkeys(REJECT_REASONS, 0)
    rows: list[list[float]] = []  # frame, x, y, w, h, score, size, sharpness, turn, track
    closed: list[_Track] = []
    open_tracks: list[_Track] = []
    sampled = detected = most = read = 0
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            raise UnreadableMediaError("The analysis proxy could not be opened to look for faces.")
        for index in range(last_frame):
            if index % _CHUNK_FRAMES == 0:
                check_cancelled()
                progress(index / last_frame)
            if not capture.grab():
                break
            read = index + 1
            if index % step:
                continue
            ok, image = capture.retrieve()
            if not ok:
                read = index
                break
            sampled += 1
            shot = bisect_right(starts, index) - 1
            keep = [t for t in open_tracks if t.shot == shot and index - t.last_frame <= gap_frames]
            closed += [t for t in open_tracks if t not in keep]
            open_tracks = keep
            found = engine.find(image, cfg)
            detected += len(found)
            most = max(most, len(found))
            for face in found:
                if face.reason:
                    rejected[face.reason] += 1
            used = [face for face in found if face.reason is None]
            links = match(open_tracks, used, cfg)
            height, width = image.shape[:2]
            for i, face in enumerate(used):
                if i in links:
                    track = open_tracks[links[i]]
                    track.total = track.total + face.vector
                else:
                    track = _Track(shot, face.vector.copy(), face.box, index)
                    open_tracks.append(track)
                track.box, track.last_frame = face.box, index
                track.faces.append(len(rows))
                quality = face.score * min(1.0, face.size_px / _REFERENCE_FACE_PX)
                if quality > track.best_quality:
                    track.best, track.best_quality = len(rows), quality
                    track.crop = crop_jpeg(image, face.box)
                x, y, w, h = face.box
                rows.append(
                    [
                        index,
                        round(x / width, 4),
                        round(y / height, 4),
                        round(w / width, 4),
                        round(h / height, 4),
                        round(face.score, 4),
                        round(face.size_px, 1),
                        round(face.sharpness or 0.0, 1),
                        round(face.turn, 3),
                        -1,
                    ]
                )
    finally:
        capture.release()
    if last_frame - read > max(2 * step, last_frame * _MISSING_FRAMES):
        # Stopping early would store "no faces" for footage nobody looked at.
        raise UnreadableMediaError(
            f"The analysis proxy could only be read up to frame {read} of {last_frame} while "
            "looking for faces. Reprocess the clip to rebuild the proxy."
        )
    tracks = sorted(closed + open_tracks, key=lambda t: (t.faces[0], t.box))
    tmp = out_dir.with_name(out_dir.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    vectors = np.zeros((len(tracks), EMBEDDING_DIM), dtype=np.float32)
    described: list[dict[str, Any]] = []
    for number, track in enumerate(tracks):
        for row in track.faces:
            rows[row][9] = number
        vectors[number] = track.mean
        name = f"t{number:04d}.jpg"
        (tmp / name).write_bytes(track.crop)
        described.append(
            {"shot": track.shot, "faces": len(track.faces), "best": track.best, "crop": name}
        )
    np.save(tmp / TRACKS_FILE, vectors)
    shutil.rmtree(out_dir, ignore_errors=True)
    tmp.rename(out_dir)  # `out_dir` belongs to one parameter set, so nothing else points into it
    progress(1.0)
    return {
        "step_frames": step,
        "frames_sampled": sampled,
        "faces_detected": detected,
        "max_in_frame": most,
        "rejected": rejected,
        "faces": rows,
        "tracks": described,
    }
