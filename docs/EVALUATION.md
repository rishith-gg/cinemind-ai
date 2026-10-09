# Evaluation

Every number here was printed by a script in `eval/`; the raw output is kept in `eval/results/`. Nothing is
estimated or carried over from other people's papers. Small samples are stated as such.

## 1. Quality flag thresholds (Phase 5)
Script: `uv run python eval/calibrate_quality.py data/phase4-verify --out eval/results/quality_calibration_2026-10-09`
Output: `eval/results/quality_calibration_2026-10-09.{txt,json}` (metrics version 2).

**Data.** 55 keyframes from 17 of the user's own phone clips (the pipeline's keyframes, i.e. the sharpest frames of
each shot) are the "acceptable" pool. Each was degraded on purpose: Gaussian blur sigma 1.5 / 3 / 6 / 12 px, exposure
+1.5 / +3 stops, -2 / -4 stops (in linear light). 495 images in total.

**Method.** Each threshold is chosen on 4/5 of the clips and tested on the remaining 1/5 (5 folds grouped by clip, so
frames of one clip are never on both sides). The primary threshold maximises balanced accuracy; the secondary one is
set just beyond anything seen on an acceptable training frame. The value written into the settings is the fit on all
clips. Targets: blur sigma >= 3, +3 stops, -4 stops. The milder levels are reported but not targeted.

**Held-out results** (positives = targeted degradations, negatives = the 55 originals). Precision, F1 and accuracy
hold only for this constructed mix (165 or 55 degraded frames against 55 originals); in real footage degraded frames
are rarer, so read recall and the number of flagged originals. With 55 frames, a third decimal means nothing.

| Flag | Rule fitted on all clips | Precision | Recall | F1 | Accuracy | TP / FP / FN / TN |
|---|---|---|---|---|---|---|
| out_of_focus (used) | blur > 0.547 OR sharpness < 5.32 | 0.994 | 1.000 | 0.997 | 0.995 | 165 / 1 / 0 / 54 |
| out_of_focus, Laplacian variance alone (not used) | sharpness < 19.49 | 0.976 | 0.994 | 0.985 | 0.977 | 164 / 4 / 1 / 51 |
| overexposed | luma_mean > 0.634 OR clipped > 0.299 | 0.963 | 0.945 | 0.954 | 0.955 | 52 / 2 / 3 / 53 |
| underexposed | luma_mean < 0.254 OR crushed > 0.101 | 0.965 | 1.000 | 0.982 | 0.982 | 55 / 2 / 0 / 53 |

**The settings that ship** are those thresholds rounded (0.55 / 5.3 / 0.63 / 0.30 / 0.25 / 0.11; the secondary ones
rounded away from the acceptable frames) plus one rule the fit above does not have: focus is not judged on a frame
without tonal range. Flagged by the app's own `picture_flags` with default settings, all frames, in-sample:

| Flag | Originals flagged | Mild level | Targeted levels |
|---|---|---|---|
| out_of_focus | 0 / 55 | sigma 1.5: 24 / 55 | sigma 3: 54 / 55, sigma 6: 54 / 55, sigma 12: 54 / 55 |
| overexposed | 2 / 55 | +1.5 stops: 39 / 55 | +3 stops: 53 / 55 |
| underexposed | 2 / 55 | -2 stops: 22 / 55 | -4 stops: 55 / 55 |

The one frame missed at every blur level is a frame whose tonal range is below `flat_spread`, where focus is
deliberately not judged.

**What this does and does not show.**
- It shows the metrics can tell a known, strong degradation from the untouched frame on this footage.
- The labels are synthetic. Gaussian blur is not lens defocus or motion blur, and the re-blur ratio is by construction
  good at detecting Gaussian blur, so the focus numbers are an upper bound, not field accuracy.
- The "acceptable" pool is not hand-checked: it contains naturally soft frames (under water, fog) and one dark indoor
  clip. Those are where the false positives come from.
- 55 frames from 17 clips of one phone are a small, narrow sample. No claim is made for other cameras.
- Mild degradations (sigma 1.5, +1.5 and -2 stops) are caught about half the time; they were not the target.
- A real test needs human labels on naturally bad footage (SPEC section 17 asks for about 200 labelled clips). The
  script can be re-run on any processed data directory; a label file is future work (Phase 13).

**Two findings that changed the design** (both seen while testing, before any threshold was fixed):
1. The plain re-blur ratio fell again on extremely soft frames, because 8-bit rounding noise counted as detail. A
   noise-floor term fixed it (metrics version 2); sigma 12 was added to the calibration to check it.
2. A small, heavily compressed synthetic clip blurred with sigma 8 stayed under the ratio threshold (0.50) because
   block edges count as detail. Hence the second condition `sharpness < 5.3`.

## 2. Quality run on the user's footage (not an accuracy figure)
Script: `uv run python eval/quality_run_summary.py data/phase4-verify`
Output: `eval/results/quality_run_summary_2026-10-09.txt`.

17 clips, 20 shots measured, clip scores 0.14 to 1.00 (median 0.93). 3 clips carry a flag: 2 low_audio_level,
1 underexposed, 1 overexposed. No black frames, frozen picture, long silence, clipping or out-of-focus shot was
reported. Stage wall time: the file records two full passes over the 17 clips (352.7 s of footage, M1, 8 GB):
quality 31.4 s and audio_qc 13.9 s over 34 stage runs, so about 16 s and 7 s per pass. Not a benchmark. Whether these flags are right was only looked at informally (the underexposed clip is a dark indoor
shot; the overexposed shot is bright fog); nobody labelled the footage.

## 3. Phase 4 run summary
`eval/phase4_run_summary.py`, output `eval/results/phase4_run_summary_2026-10-09.txt`; discussed in PROGRESS.md.
