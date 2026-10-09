"""Technical picture metrics and the Technical Quality Score (SPEC section 8).

Transparent measurements, not a judgement of how good a shot looks. Everything here is our own
arithmetic on OpenCV primitives; formulas and the origin of each threshold are in
docs/AI_PIPELINE.md. Thresholds live in `core/quality_config.py` and are calibrated by
`eval/calibrate_quality.py`.
"""
# OpenCV images are untyped arrays; the checks below are relaxed for this module only.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import logging
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any

import cv2
import numpy as np

from cinemind.core.errors import UnreadableMediaError
from cinemind.core.quality_config import QualityConfig

log = logging.getLogger(__name__)

METRICS_VERSION = "2"  # 2: blur ratio corrected for the rounding-noise floor
# Every frame is measured at about this many pixels, so 720p and 4K sources compare.
_PIXELS = 640 * 360
_REBLUR_SIGMA = 1.0
# Laplacian variance of pure 8-bit rounding error (kernel weights 1,1,1,1,-4: 20 x 1/12). Added
# to both sides of the blur ratio so that a frame whose only "detail" is rounding noise reads as
# blurry; without it the ratio falls again on very soft frames.
_NOISE_FLOOR = 20 / 12
_CLIPPED_AT = 250  # 8-bit luma at or above this counts as a clipped highlight
_CRUSHED_AT = 5  # at or below this counts as a crushed shadow
MAX_FRAMES_PER_SHOT = 12
MIN_FRAME_GAP_S = 0.5


@dataclass(frozen=True)
class FrameMetrics:
    sharpness: float  # variance of the Laplacian
    blur: float  # re-blur ratio in 0..1: share of detail that survives a further blur (1 = blurry)
    luma_mean: float  # 0..1
    luma_std: float
    spread: float  # 95th minus 5th luma percentile
    clipped: float  # fraction of pixels in clipped highlights
    crushed: float  # fraction of pixels in crushed shadows


def frame_metrics(image: Any) -> FrameMetrics:
    """Measure one BGR frame."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    scale = math.sqrt(_PIXELS / (width * height))
    if scale < 1:
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        gray = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    softened = cv2.GaussianBlur(gray, (0, 0), _REBLUR_SIGMA)
    resharp = float(cv2.Laplacian(softened, cv2.CV_64F).var())
    luma = gray.astype(np.float32) / 255.0
    low, high = np.percentile(luma, [5, 95])
    return FrameMetrics(
        sharpness=sharpness,
        # A frame with no detail at all (flat colour) comes out as 1: blurry.
        blur=min(1.0, (resharp + _NOISE_FLOOR) / (sharpness + _NOISE_FLOOR)),
        luma_mean=float(luma.mean()),
        luma_std=float(luma.std()),
        spread=float(high - low),
        clipped=float((gray >= _CLIPPED_AT).mean()),
        crushed=float((gray <= _CRUSHED_AT).mean()),
    )


def aggregate(frames: list[FrameMetrics]) -> dict[str, float]:
    """A shot's metrics: the median over its sampled frames (robust to a few odd frames)."""
    fields = asdict(frames[0]).keys()
    return {name: round(float(median(getattr(f, name) for f in frames)), 6) for name in fields}


def _unit(value: float) -> float:
    return min(1.0, max(0.0, value))


def _ramp(value: float, zero_at: float, one_at: float) -> float:
    """0 at `zero_at`, 1 at `one_at`, linear between (either direction). QualityConfig
    guarantees the two ends differ."""
    return _unit((value - zero_at) / (one_at - zero_at))


def focus_judged(metrics: dict[str, float], cfg: QualityConfig) -> bool:
    """Focus is only judged on a frame with tonal range: black, fog or a plain wall has no
    detail that could have been sharp."""
    return metrics["spread"] >= cfg.flat_spread


def sub_scores(metrics: dict[str, float], cfg: QualityConfig) -> dict[str, float | None]:
    """Normalised 0..1 sub-scores (1 = no technical problem measured). `sharpness` is None
    when focus cannot be judged, and 0 whenever the out-of-focus flag would be raised."""
    sharpness: float | None = None
    if focus_judged(metrics, cfg):
        sharpness = round(_ramp(metrics["blur"], cfg.out_of_focus_blur_above, cfg.sharp_blur), 4)
        if metrics["sharpness"] < cfg.out_of_focus_sharpness_below:
            sharpness = 0.0
    over = max(
        _ramp(metrics["luma_mean"], cfg.exposure_ok_high, cfg.overexposed_mean_above),
        _ramp(metrics["clipped"], 0.0, cfg.overexposed_clipped_above),
    )
    under = max(
        _ramp(metrics["luma_mean"], cfg.exposure_ok_low, cfg.underexposed_mean_below),
        _ramp(metrics["crushed"], 0.0, cfg.underexposed_crushed_above),
    )
    return {
        "sharpness": sharpness,
        "exposure": round(1.0 - max(over, under), 4),
        "contrast": round(_ramp(metrics["spread"], cfg.flat_spread, cfg.good_spread), 4),
    }


def video_score(scores: dict[str, float | None], cfg: QualityConfig) -> float:
    """Weighted mean of the sub-scores that could be measured (weights renormalised)."""
    weights = {
        "sharpness": cfg.weight_sharpness,
        "exposure": cfg.weight_exposure,
        "contrast": cfg.weight_contrast,
    }
    used = {k: w for k, w in weights.items() if scores[k] is not None}
    total = sum(used.values())
    if total <= 0:
        return 0.0
    return round(sum((scores[k] or 0.0) * w for k, w in used.items()) / total, 4)


def picture_flags(metrics: dict[str, float], cfg: QualityConfig) -> list[dict[str, Any]]:
    """Flags for one shot, each with the measured value and the threshold it crossed.
    Focus is not judged on a frame without tonal range (see `focus_judged`)."""
    judgeable = focus_judged(metrics, cfg)
    soft = judgeable and metrics["blur"] > cfg.out_of_focus_blur_above
    no_detail = judgeable and metrics["sharpness"] < cfg.out_of_focus_sharpness_below
    checks = [
        ("out_of_focus", "blur", soft, "above"),
        ("out_of_focus", "sharpness", no_detail, "below"),
        (
            "overexposed",
            "luma_mean",
            metrics["luma_mean"] > cfg.overexposed_mean_above,
            "above",
        ),
        ("overexposed", "clipped", metrics["clipped"] > cfg.overexposed_clipped_above, "above"),
        (
            "underexposed",
            "luma_mean",
            metrics["luma_mean"] < cfg.underexposed_mean_below,
            "below",
        ),
        ("underexposed", "crushed", metrics["crushed"] > cfg.underexposed_crushed_above, "above"),
    ]
    thresholds = {
        ("out_of_focus", "blur"): cfg.out_of_focus_blur_above,
        ("out_of_focus", "sharpness"): cfg.out_of_focus_sharpness_below,
        ("overexposed", "luma_mean"): cfg.overexposed_mean_above,
        ("overexposed", "clipped"): cfg.overexposed_clipped_above,
        ("underexposed", "luma_mean"): cfg.underexposed_mean_below,
        ("underexposed", "crushed"): cfg.underexposed_crushed_above,
    }
    found: dict[str, dict[str, Any]] = {}
    for kind, metric, hit, direction in checks:
        if hit and kind not in found:  # one flag per kind; the first reason is reported
            found[kind] = {
                "kind": kind,
                "metric": metric,
                "value": round(metrics[metric], 4),
                "threshold": thresholds[(kind, metric)],
                "direction": direction,
            }
    return list(found.values())


def sample_frames(start: int, end: int, fps: float) -> list[int]:
    """Evenly spaced frame numbers inside a shot: at most MAX_FRAMES_PER_SHOT, no closer than
    MIN_FRAME_GAP_S, never the first or last frame of the shot when it can be avoided."""
    frames = end - start
    if frames <= 0:
        return []
    count = max(1, min(MAX_FRAMES_PER_SHOT, int(frames / fps / MIN_FRAME_GAP_S)))
    lo, hi = (start + 1, end - 2) if frames > 3 else (start, end - 1)
    picked = {min(hi, max(lo, start + round(frames * (i + 0.5) / count))) for i in range(count)}
    return sorted(picked)


def measure_shots(
    video: Path,
    shots: list[tuple[int, int]],
    fps: float,
    progress: Callable[[float], None],
    check_cancelled: Callable[[], None],
) -> list[dict[str, Any]]:
    """Per shot: {"frames": n, "metrics": {...}} from one sequential decode of `video`."""
    wanted: dict[int, int] = {}
    for index, (start, end) in enumerate(shots):
        for frame in sample_frames(start, end, fps):
            wanted[frame] = index
    last = max(wanted, default=-1)
    seen: list[list[FrameMetrics]] = [[] for _ in shots]
    capture = cv2.VideoCapture(str(video))
    try:
        for index in range(last + 1):
            if index % 240 == 0:
                check_cancelled()
                progress(index / (last + 1))
            if not capture.grab():
                break
            shot = wanted.get(index)
            if shot is None:
                continue
            ok, image = capture.retrieve()
            if ok:
                seen[shot].append(frame_metrics(image))
    finally:
        capture.release()
    if shots and not any(seen):
        raise UnreadableMediaError("No frames could be read to measure picture quality.")
    missing = sum(1 for frames in seen if not frames)
    if missing:
        log.warning("%s: %d of %d shots had no readable frame", video.name, missing, len(shots))
    return [
        {"frames": len(frames), "metrics": aggregate(frames) if frames else None} for frames in seen
    ]
