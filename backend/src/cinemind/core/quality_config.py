"""Thresholds and weights for technical quality (settings section `[quality]`).

Values marked CALIBRATED come from `eval/calibrate_quality.py` (see docs/EVALUATION.md for the
run and its limits). Values marked DEFAULT are stated conventions, not measured optima.
"""

import math
from typing import Self

from pydantic import BaseModel, model_validator


class QualityConfig(BaseModel):
    # --- picture: flag thresholds (CALIBRATED, eval/results/quality_calibration_2026-10-09) ---
    out_of_focus_blur_above: float = 0.55
    # Laplacian variance under anything seen on an acceptable frame: catches soft pictures whose
    # compression artefacts keep the blur ratio down (small, heavily compressed sources).
    out_of_focus_sharpness_below: float = 5.3
    overexposed_mean_above: float = 0.63
    overexposed_clipped_above: float = 0.30
    underexposed_mean_below: float = 0.25
    underexposed_crushed_above: float = 0.11
    # --- picture: where a sub-score reaches 1 (DEFAULT, read off the same run's spread of
    # original frames: median blur, 10th-75th percentile brightness, 10th percentile spread) ---
    sharp_blur: float = 0.13
    exposure_ok_low: float = 0.35
    exposure_ok_high: float = 0.55
    flat_spread: float = 0.15
    good_spread: float = 0.45
    # --- Technical Quality Score weights (DEFAULT; audio only counts when the clip has sound) ---
    weight_sharpness: float = 0.5
    weight_exposure: float = 0.3
    weight_contrast: float = 0.2
    weight_audio: float = 0.25
    low_quality_below: float = 0.5
    # --- audio (DEFAULT: broadcast conventions and ffmpeg detector settings) ---
    low_level_lufs_below: float = -35.0
    good_level_lufs: float = -27.0
    clipped_samples_pct_above: float = 0.01
    clip_sample_level: float = 0.999
    silence_noise_db: float = -50.0
    long_silence_s: float = 2.0
    # --- black and frozen picture (DEFAULT: ffmpeg detector settings) ---
    black_min_s: float = 0.5
    black_pixel_threshold: float = 0.10
    freeze_min_s: float = 2.0
    freeze_noise_db: float = -60.0

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        """Reject settings that would invert or zero every score instead of failing quietly."""
        values = self.model_dump()
        if not all(math.isfinite(v) for v in values.values()):
            raise ValueError("quality settings must be finite numbers")
        weights = (self.weight_sharpness, self.weight_exposure, self.weight_contrast)
        if min(weights) < 0 or sum(weights) <= 0:
            raise ValueError("picture weights must not be negative and must not all be zero")
        if not 0 <= self.weight_audio <= 1:
            raise ValueError("weight_audio must be between 0 and 1")
        ordered = [
            (
                self.sharp_blur < self.out_of_focus_blur_above,
                "sharp_blur < out_of_focus_blur_above",
            ),
            (
                self.underexposed_mean_below < self.exposure_ok_low < self.exposure_ok_high,
                "underexposed_mean_below < exposure_ok_low < exposure_ok_high",
            ),
            (
                self.exposure_ok_high < self.overexposed_mean_above,
                "exposure_ok_high < overexposed_mean_above",
            ),
            (self.flat_spread < self.good_spread, "flat_spread < good_spread"),
            (
                self.low_level_lufs_below < self.good_level_lufs,
                "low_level_lufs_below < good_level_lufs",
            ),
            (self.overexposed_clipped_above > 0, "overexposed_clipped_above > 0"),
            (self.underexposed_crushed_above > 0, "underexposed_crushed_above > 0"),
            (self.clipped_samples_pct_above > 0, "clipped_samples_pct_above > 0"),
            (0 < self.clip_sample_level <= 1, "0 < clip_sample_level <= 1"),
            (
                min(self.black_min_s, self.freeze_min_s, self.long_silence_s) > 0,
                "minimum durations > 0",
            ),
        ]
        broken = [rule for ok, rule in ordered if not ok]
        if broken:
            raise ValueError("quality settings must satisfy: " + "; ".join(broken))
        return self
