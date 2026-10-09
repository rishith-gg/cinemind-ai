# Pipeline and formulas

What each stage does, which part is an existing tool and which part is ours, and the exact formulas behind every
score. Settings named in `code` live in `cinemind.toml` / `.env` (`core/config.py`, section `[quality]` in
`core/quality_config.py`).

## The `ingest` chain (one job per clip)
| # | Stage | Existing tool | Ours |
|---|---|---|---|
| 1 | validate | ffprobe | which fields are kept, VFR rule, friendly errors |
| 2 | proxy | ffmpeg (H.264) | constant-rate 720p proxy, encoder fallback |
| 3 | thumbnails | ffmpeg | poster + strip layout |
| 4 | waveform | ffmpeg (PCM decode) | 1000-bin peak envelope |
| 5 | shots | PySceneDetect (`AdaptiveDetector`) | chunked run with progress/cancel on the proxy |
| 6 | keyframes | OpenCV (Laplacian) | anchor points, sharpest-of-5 rule |
| 7 | quality | OpenCV primitives; ffmpeg `blackdetect`, `freezedetect` | the metrics, sub-scores, score and flags below |
| 8 | audio_qc | ffmpeg `ebur128`, `silencedetect` | clipped-sample count, audio score, flags |

Every stage result is cached by (media content hash, stage, parameters, tool version) and chained to the stage
before it. Stages 7 and 8 cache MEASUREMENTS only; scores and flags are recomputed from them with the current
settings every time the job runs, so a changed weight or threshold needs no video decoding ("Process all").

## Technical quality (stages 7 and 8)
These are technical measurements: focus, exposure, tonal range, audio level. They say nothing about whether a shot is
good, and the app never calls them "cinematic quality".

### Picture metrics (per sampled frame)
Frames: up to 12 per shot, evenly spaced, at least 0.5 s apart, not the first or last frame of the shot. Each frame is
converted to 8-bit grey and scaled down to about 640x360 pixels (same pixel count for any source size).

| Metric | Formula |
|---|---|
| `sharpness` | variance of the Laplacian of the grey frame |
| `blur` | `(var(Laplacian(G1)) + n) / (sharpness + n)` where G1 is the frame blurred with a Gaussian of sigma 1 and `n` = 20/12 is the Laplacian variance of 8-bit rounding error. Near 0 = a further blur destroys most detail (sharp); near 1 = nothing left to lose (blurry). Capped at 1. |
| `luma_mean`, `luma_std` | mean and standard deviation of luma in 0..1 |
| `spread` | 95th minus 5th luma percentile (tonal range) |
| `clipped` | share of pixels with 8-bit luma >= 250 |
| `crushed` | share of pixels with 8-bit luma <= 5 |

A shot's value for each metric is the MEDIAN over its sampled frames.

### Sub-scores (0..1, 1 = no problem measured)
`ramp(x, a, b)` is 0 at `a`, 1 at `b`, linear between, clamped.
- focus = `ramp(blur, out_of_focus_blur_above, sharp_blur)` (0 at the flag threshold, 1 at `sharp_blur`); forced to 0
  when `sharpness < out_of_focus_sharpness_below`; NOT JUDGED (left out of the score, weights renormalised) when
  `spread < flat_spread`, because a frame without tonal range has nothing that could be sharp
- exposure = `1 - max(over, under)` with
  `over = max(ramp(luma_mean, exposure_ok_high, overexposed_mean_above), ramp(clipped, 0, overexposed_clipped_above))`
  `under = max(ramp(luma_mean, exposure_ok_low, underexposed_mean_below), ramp(crushed, 0, underexposed_crushed_above))`
- contrast = `ramp(spread, flat_spread, good_spread)`

### Technical Quality Score
- shot score = `(focus*weight_sharpness + exposure*weight_exposure + contrast*weight_contrast) / (sum of the weights
  of the sub-scores that were judged)` (defaults 0.5 / 0.3 / 0.2)
- audio score = `min(level, clipping)` with `level = ramp(LUFS, low_level_lufs_below, good_level_lufs)` and
  `clipping = 1 - ramp(clipped %, 0, clipped_samples_pct_above)`. No loudness reading: level 0 if the track is silent,
  level 1 (not penalised) if it was only too short to measure (under 1 s, or audible peaks). Ranges of silence inside a
  track are reported, not scored; an entirely silent track counts as a low level.
- clip score = shot scores weighted by shot length; when the clip has sound:
  `picture*(1 - weight_audio) + audio*weight_audio` (default 0.25). Audio-only files: the audio score.
- "low quality" = clip score below `low_quality_below` (default 0.5; a convention, not calibrated).

### Flags (each stores the measured value, the threshold and the direction, or the detector and its settings)
| Flag | Rule | Origin of the threshold |
|---|---|---|
| out_of_focus | `blur > 0.55` OR `sharpness < 5.3`, only when `spread >= flat_spread` (focus is not judged on a frame without tonal range) | calibrated, see EVALUATION.md |
| overexposed | `luma_mean > 0.63` OR `clipped > 0.30` | calibrated |
| underexposed | `luma_mean < 0.25` OR `crushed > 0.11` | calibrated |
| black_frames | ffmpeg `blackdetect`, at least `black_min_s` (0.5 s), pixel threshold 0.10 | ffmpeg defaults, shorter minimum |
| frozen_frames | ffmpeg `freezedetect`, at least `freeze_min_s` (2 s), noise -60 dB | ffmpeg defaults |
| long_silence | ffmpeg `silencedetect`, under `silence_noise_db` (-50 dB) for `long_silence_s` (2 s) | convention |
| clipped_audio | more than 0.01 % of decoded 16-bit samples at >= 99.9 % of full scale | convention |
| low_audio_level | integrated loudness (EBU R128) below -35 LUFS, or a silent track | convention |
| audio_unreadable | the audio track could not be decoded; the clip is still processed and scored on picture alone | - |

In the UI `out_of_focus` is labelled "Soft picture", because the measure cannot tell defocus from fog, water or
heavy compression. The score is shown as "Tech score".

The settings a score was computed with are stored with it and returned by the API; if the settings change later,
the clip page says so until the clip is reprocessed. Inconsistent settings (for example a "sharp" level above the
out-of-focus limit) are rejected at start-up instead of silently inverting scores.

Detector output is parsed only from the lines the ffmpeg filter itself logs, never from file metadata printed on the
same stream.

Audio is measured on the ORIGINAL file's first audio stream (the proxy's AAC re-encode would change peaks).
Picture metrics are measured on the proxy.

### Known limits
- Laplacian-based focus measures depend on content: fog, water, a plain wall or shallow depth of field read as soft.
- The median over a shot hides a few blurred frames (a whip pan inside a sharp shot is not flagged).
- Heavy compression adds block edges that look like detail; the absolute `sharpness` floor exists for that case.
- "Overexposed" is a brightness statistic: a deliberately bright scene (snow, fog, a white wall) is flagged too.
- No face-region sharpness yet (needs faces, Phase 7), no noise or shake metric, no speech-present flag (Phase 6).
