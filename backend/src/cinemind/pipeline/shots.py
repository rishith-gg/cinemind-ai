"""Shot detection (PySceneDetect) and keyframe selection (OpenCV) on the analysis proxy.

PySceneDetect's detectors are an existing library; what is ours here is the wiring (progress,
cancellation, the constant-rate proxy as input) and the keyframe rule: per shot, up to three
anchor points, and at each the sharpest of a few nearby frames (variance of the Laplacian).
"""
# scenedetect ships no type stubs and OpenCV images are untyped arrays; the checks below are
# relaxed for this wrapper only.
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import cv2
import scenedetect
from scenedetect import AdaptiveDetector, ContentDetector, SceneManager, open_video

from cinemind.core.errors import InvalidInputError, UnreadableMediaError

log = logging.getLogger(__name__)
# Detection runs in chunks; without this the library logs one INFO line per chunk.
logging.getLogger("pyscenedetect").setLevel(logging.WARNING)

SCENEDETECT_VERSION: str = scenedetect.__version__
DEFAULT_THRESHOLDS = {"adaptive": 3.0, "content": 27.0}
_CHUNK_FRAMES = 240  # frames between progress/cancel checks
# Keyframes: candidates looked at around each anchor, and how far from it (seconds).
CANDIDATES_PER_ANCHOR = 5
ANCHOR_WINDOW_S = 0.25
_SHARPNESS_HEIGHT = 360
_JPEG_QUALITY = 90

Progress = Callable[[float], None]
Check = Callable[[], None]


@dataclass(frozen=True)
class Detection:
    detector: str
    threshold: float
    min_len_frames: int
    frames: int
    shots: list[tuple[int, int]]  # (start frame, end frame exclusive)


def detect_shots(
    video: Path,
    fps: Fraction,
    detector: str,
    threshold: float | None,
    min_len_s: float,
    progress: Progress,
    check_cancelled: Check,
) -> Detection:
    """Cut positions in `video` (frame numbers). A video without cuts is one shot."""
    if detector not in DEFAULT_THRESHOLDS:
        raise InvalidInputError(f"Unknown shot detector '{detector}'. Use adaptive or content.")
    value = DEFAULT_THRESHOLDS[detector] if threshold is None else threshold
    min_len = max(1, round(min_len_s * fps))
    stream = open_video(str(video))
    manager = SceneManager()
    if detector == "adaptive":
        manager.add_detector(AdaptiveDetector(adaptive_threshold=value, min_scene_len=min_len))
    else:
        manager.add_detector(ContentDetector(threshold=value, min_scene_len=min_len))
    length = stream.duration
    expected = max(1, length.frame_num if length is not None else round(fps))
    done = 0
    while True:
        check_cancelled()
        read = manager.detect_scenes(stream, duration=_CHUNK_FRAMES)
        if read == 0:
            break
        done += read
        progress(done / expected)
    if done == 0:
        raise UnreadableMediaError("No video frames could be read for shot detection.")
    scenes = manager.get_scene_list(start_in_scene=True)
    shots = [(start.frame_num, end.frame_num) for start, end in scenes]
    return Detection(detector, value, min_len, done, shots or [(0, done)])


def keyframe_plan(
    shots: list[tuple[int, int]], fps: Fraction, per_shot: int
) -> dict[tuple[int, int], list[int]]:
    """(shot index, slot) -> candidate frames. Short shots get fewer keyframes; candidates stay
    inside the shot and off its first/last frame where possible."""
    plan: dict[tuple[int, int], list[int]] = {}
    for index, (start, end) in enumerate(shots):
        frames = end - start
        if frames <= 0:
            continue
        seconds = frames / fps
        count = max(1, min(per_shot, 1 if seconds < 1.5 else 2 if seconds < 4 else 3))
        lo, hi = (start + 1, end - 2) if frames > 3 else (start, end - 1)
        # Stay inside this anchor's share of the shot so two slots never pick the same frame.
        reach = min(round(ANCHOR_WINDOW_S * fps), frames // (2 * count))
        for slot in range(count):
            anchor = start + round(frames * (slot + 0.5) / count)
            step = max(1, 2 * reach // (CANDIDATES_PER_ANCHOR - 1)) if reach else 1
            offsets = range(-reach, reach + 1, step) if reach else (0,)
            candidates = sorted({min(hi, max(lo, anchor + off)) for off in offsets})
            plan[(index, slot)] = candidates
    return plan


def _sharpness(image: Any) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    if height > _SHARPNESS_HEIGHT:
        size = (max(1, round(width * _SHARPNESS_HEIGHT / height)), _SHARPNESS_HEIGHT)
        gray = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def extract_keyframes(
    video: Path,
    shots: list[tuple[int, int]],
    fps: Fraction,
    per_shot: int,
    out_dir: Path,
    progress: Progress,
    check_cancelled: Check,
) -> list[dict[str, Any]]:
    """Write the chosen keyframes into `out_dir` (replaced atomically) in one decode pass.
    Returns one entry per keyframe: shot, slot, frame, sharpness, candidates, file."""
    plan = keyframe_plan(shots, fps, per_shot)
    wanted: dict[int, list[tuple[int, int]]] = {}
    for key, candidates in plan.items():
        for frame in candidates:
            wanted.setdefault(frame, []).append(key)
    last_frame = max(wanted, default=-1)
    tmp = out_dir.with_name(out_dir.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    best: dict[tuple[int, int], tuple[float, int, Any]] = {}
    found: list[dict[str, Any]] = []

    def flush(key: tuple[int, int]) -> None:
        if key not in best:
            return
        sharpness, frame, image = best.pop(key)
        name = f"s{key[0]:04d}_k{key[1]}.jpg"
        ok, data = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_QUALITY])
        if not ok:
            log.warning("could not encode keyframe %s of %s", name, video.name)
            return
        (tmp / name).write_bytes(data.tobytes())
        found.append(
            {
                "shot": key[0],
                "slot": key[1],
                "frame": frame,
                "sharpness": round(sharpness, 3),
                "candidates": len(plan[key]),
                "file": name,
            }
        )

    capture = cv2.VideoCapture(str(video))
    try:
        for index in range(last_frame + 1):
            if index % _CHUNK_FRAMES == 0:
                check_cancelled()
                progress(index / (last_frame + 1))
            if not capture.grab():
                break  # shorter than expected: keep what was found
            keys = wanted.get(index)
            if not keys:
                continue
            ok, image = capture.retrieve()
            if not ok:
                continue
            score = _sharpness(image)
            for key in keys:
                if key not in best or score > best[key][0]:
                    best[key] = (score, index, image)
                if plan[key][-1] == index:
                    flush(key)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    finally:
        capture.release()
    for key in list(best):
        flush(key)
    if shots and not found:
        shutil.rmtree(tmp, ignore_errors=True)
        raise UnreadableMediaError("No keyframes could be read from this clip.")
    shutil.rmtree(out_dir, ignore_errors=True)
    tmp.replace(out_dir)
    return sorted(found, key=lambda k: (k["shot"], k["slot"]))
