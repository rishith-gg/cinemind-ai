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

## 4. Transcription: word error rate and speed (Phase 6)
Script: `uv run python eval/wer.py fetch`, then
`uv run python eval/wer.py run data/eval/librispeech-dev-clean-2 --models base small --minutes 10`
Output: `eval/results/wer_librispeech-dev-clean-2_2026-10-10.{txt,json}` (the json lists the utterance ids).

Sample: 82 of the 1089 utterances of Mini LibriSpeech dev-clean-2 (10.17 min, fixed random sample, seed 0): English
audiobooks read aloud in quiet rooms, with reference transcripts (CC BY 4.0). The script calls the same decode and
transcribe functions as the pipeline, with the default settings (language detection on).
Hardware: Apple M1, 8 GB RAM, CPU, int8. Engine: faster-whisper 1.2.1, CTranslate2 4.8.2.

| Model (revision) | WER | Substitutions | Deletions | Insertions | Reference words | Seconds per second of audio |
|---|---|---|---|---|---|---|
| base (`ebe41f70d5b6`) | 6.60 % | 90 | 11 | 10 | 1682 | 0.104 |
| small (`536b0662742c`) | 4.70 % | 64 | 8 | 7 | 1682 | 0.290 |

No utterance was detected as a language other than English. Scoring: lower case, punctuation removed; numbers the
model writes as digits count as errors against spelled-out references. `small` is the default of the lite tier.

**What this does and does not show.**
- It shows the pipeline (decode, voice-activity detection, model, word assembly) transcribes clean English correctly
  and what the two small models cost on this machine.
- It says nothing about the user's footage. Read audiobook speech is about the easiest input there is; phone footage
  with wind, water, music, several speakers and other languages is far harder (section 5).
- One sample of 10 minutes, one run. No confidence interval was computed.
- The memory column in the output file is the whole process after each model, including the decoded sample; it is
  not a per-model peak and is not quoted here.
- A WER on the user's own material needs hand-written transcripts: put `clip.txt` next to `clip.mov` in a folder and
  run `eval/wer.py run <folder>`. Not done yet.

## 5. Transcription run on the user's footage (not an accuracy figure)
Script: `uv run python eval/transcribe_run_summary.py data`
Output: `eval/results/transcribe_run_summary_2026-10-10.txt`. Model `small`, language detection on, M1 CPU.

21 clips (473.4 s): 8 with a transcript, 12 `no_speech`, 1 `no_audio`, no failed job. 50 segments, 22 of them marked
uncertain; in 5 of the 8 transcripts the language probability is under 0.5. Detected languages: 3 English, 3 Kannada,
2 Hindi. The transcribe stage took 491.2 s in total (1.04 s per second of footage), very unevenly: the 11 clips
where the voice-activity detector kept nothing took 0.8 to 1.6 s each, except one at 14.6 s; 7 clips took between
27.7 and 166.5 s (the longest for 73.5 s of footage, another 77.0 s for 6.2 s of footage), because the model retries
segments it does not accept.

Nobody has checked these words against what is said. Observations, not measurements:
- An earlier trial run of the same model on the same files gave different text for several noisy clips, and for one
  clip English sentences instead of Kannada script. Results on such audio are not repeatable (AI_PIPELINE.md).
- Three clips where the voice-activity detector kept 11.4 to 13.9 s as speech ended as `no_speech`: the model
  produced no text for them. Three other clips have only uncertain segments.
- The one clip recorded as dialogue ("Timeline One.mov", 12.5 s) came out as three English sentences with none
  marked uncertain. Whether they are the words spoken has to be confirmed by the user.

## 6. Face grouping: purity, ARI, NMI, B-cubed (Phase 7)
Script: `uv run python eval/face_clusters.py fetch` then `uv run python eval/face_clusters.py run data/eval/lfw`
Output: `eval/results/face_clusters_lfw_2026-10-10.txt` and `.json`. M1, 8 GB, CPU.

**What is measured.** The app's own face code (YuNet + SFace through `FaceEngine` with the `[faces]` checks, then
`face_cluster.cluster`) on Labeled Faces in the Wild, a public research set of web photos of public figures with
one name per photo (173 MB, checksum verified on download). Each photo counts as one track.

**Design.** People with at least 5 photos (the first 20 of each) are split into two halves by name order, every
other person; each half also gets 200 people who have a single photo, because most people in real footage are
seen once. The grouping distance is chosen on the tuning half (best B-cubed F1 over 0.30 to 0.90 in steps of
0.05). Every figure below is from the held-out half, which that choice never saw.

| | Tuning half | Held-out half |
|---|---|---|
| Photos | 2295 of 412 people | 2307 of 411 people |
| With a usable face | 2287 (left out: 5 turned, 3 blurry) | 2298, 409 people (left out: 7 turned, 2 blurry) |

Chosen on the tuning half: distance **0.60** (B-cubed F1 0.993; 0.55 gives 0.986, 0.65 gives 0.988, 0.70 gives 0.954).
It is the value the setting already had, taken from rounding the SFace authors' pair threshold; the sweep confirms
it rather than moving it.

Held-out half, 409 true people:

| Method | Groups | Purity | ARI | NMI | B-cubed precision | B-cubed recall | B-cubed F1 |
|---|---|---|---|---|---|---|---|
| agglomerative, distance 0.60 (the default) | 410 | 0.997 | 0.991 | 0.998 | 0.995 | 0.991 | 0.993 |
| HDBSCAN (min cluster size 2, unassigned points as one-person groups; it has no distance setting) | 445 | 0.985 | 0.945 | 0.984 | 0.976 | 0.935 | 0.955 |

Finding faces and vectors took 9 to 10 ms per photo; grouping about 2300 points took 0.1 s (agglomerative) and
0.2 s (HDBSCAN).

**What these numbers do not show.**
- LFW is easy next to footage: posed or press photos, one centred face, good light, 250 px images. The numbers show
  that the code path works and which method and distance to prefer, not how well the user's footage is grouped
  (section 7).
- The SFace model was trained by its authors on other photos of public figures. Whether its training data contains
  the people in LFW is not something we checked; if it does, these figures are optimistic.
- The set is known to be unbalanced in age, sex and skin tone; no per-group figures were computed.
- One photo per track: the mean over several faces of a shot and the "same frame, different people" rule, which the
  app uses, do not exist in this set and are not evaluated by it. Tracking is not evaluated at all.
- The four face checks left out 17 of 4602 photos here; on the user's footage they leave out 45 % of the detected
  faces (section 7). Their limits are conventions and were not tuned.

## 7. Faces run on the user's footage (not an accuracy figure)
Script: `uv run python eval/faces_run_summary.py data`
Output: `eval/results/faces_run_summary_2026-10-10.txt`. YuNet + SFace, 2 frames per second, M1 CPU.

21 clips (473.4 s): 16 with usable faces, 5 with none, no failed job. 957 frames sampled, 849 faces detected, 469
used; left out: 178 low detector confidence, 132 turned, 58 small, 12 blurry. The faces stage took 20.3 s in total
(0.043 s per second of footage). 72 tracks were grouped into 27 actors; 16 of the 27 consist of a single track, 13
of those of a single face. The largest group has 20 tracks in 6 clips (229 faces, 121 s).

Nobody has labelled who is who in this footage, so there is no purity or ARI for it. Observations from looking at
the crops of the 14 largest groups, not measurements:
- Five of the eight largest groups look like one person each across different clips, light and headwear.
- At least two groups (the third and fifth largest) visibly mix different people, for example faces with and
  without glasses.
- The same person also appears in several small groups, mostly from clips filmed sideways or upside down, in water,
  or with part of the face covered.
- Tracks break often: one 73.5 s clip gives 14 tracks, which end up in 7 actors.

A measured figure for this footage needs labels: correct the groups on the Actors page (the corrections are the
labels), or put face crops into one folder per person and run `eval/face_clusters.py run <folder>`. Not done yet.


## 8. Tag thresholds: precision on labelled public photos (Phase 8)
Script: `uv run python eval/tag_calibration.py fetch`, then `uv run python eval/tag_calibration.py run --install`
Output: `eval/results/tag_calibration_clip-vit-b32_2026-10-14.txt` and `.json`; thresholds installed into
`backend/src/cinemind/ai/tag_thresholds.json`. OpenCLIP ViT-B/32 (LAION-2B, revision 1a25a446712b), vocabulary v1,
the app's own scoring code. M1, MPS; embedding the 23,250 photos took 294 to 438 s (three runs on the same photos while the script was
fixed; the figures below are from the last, with the rules described here).

Data: Places365 validation set, all 50 photos of each of the 365 categories (18,250; indoor/outdoor label per
category from the authors), and the CODaN test sets (2,500 day photos from COCO/ImageNet, 2,500 low-light photos
from ExDark). Each set is split in two halves (every other photo per category); the threshold is the lowest score at
which the tuning half reaches 0.9 precision, but never under 0.5 for a two-way tag (indoor/outdoor, day/night: the
shares add up to 1, so a lower threshold could show both tags on one picture; the first run did exactly that on at
least 3 of the user's shots). Every figure below is from the other half. A tag is switched off below
0.85 held-out precision or with fewer than 10 held-out photos above the threshold.

| Tag | Set | Threshold | Shown (held-out) | Precision | 95% CI | Recall | Positives | State |
|---|---|---|---|---|---|---|---|---|
| indoor | Places365 | 0.588 | 3878 | 0.903 | 0.89–0.91 | 0.870 | 4025 | on |
| outdoor | Places365 | 0.500 | 5124 | 0.905 | 0.90–0.91 | 0.910 | 5100 | on |
| day | CODaN | 0.500 | 1254 | 0.920 | 0.90–0.93 | 0.923 | 1250 | on |
| night / low light | CODaN | 0.500 | 1246 | 0.923 | 0.91–0.94 | 0.920 | 1250 | on |
| forest | Places365 | 0.837 | 55 | 0.927 | 0.83–0.97 | 0.408 | 125 | on |
| field | Places365 | 0.983 | 16 | 1.000 | 0.81–1.00 | 0.128 | 125 | on |
| temple | Places365 | 0.988 | 18 | 0.944 | 0.74–0.99 | 0.340 | 50 | on |
| office | Places365 | 0.896 | 29 | 0.966 | 0.83–0.99 | 0.373 | 75 | on |
| street | Places365 | 0.991 | 13 | 0.846 | 0.58–0.96 | 0.110 | 100 | off (precision under 0.85) |
| inside a vehicle | Places365 | 0.655 | 103 | 0.825 | 0.74–0.89 | 0.850 | 100 | off (precision under 0.85) |

Off because the tuning half never reached 0.9 precision at any threshold (held-out average precision in brackets):
beach or coast (0.31), open sea (0.15), underwater (0.78), waterfall (0.73), river or lake (0.38), swimming pool
(0.69), mountain (0.53), highway (0.46), kitchen (0.59), bedroom (0.34), living room (0.28), restaurant or café
(0.38), classroom (0.59), stage (0.31). Not evaluated (no open labelled set, never shown): close-up, medium, wide.
For reference, the same model's 365-way Places365 top-1 accuracy on the held-out half was 0.424.

What this does and does not say:
- Precision depends on how common a tag is. A place tag is true for 1 to 5 of 365 categories here (a few photos in a
  thousand); on footage shot at such a place it is far more common and precision would be higher, on footage with
  none of it lower. Indoor/outdoor and day/night are close to balanced here.
- In the app a shot shows a tag when more than half of its keyframes pass the threshold (on a tie, when their mean does); each keyframe decision is the
  one measured here, the shot-level rule itself is not evaluated.
- Places365 are web photos with per-category indoor/outdoor labels (some debatable); CODaN "night" photos are
  low-light crops of objects, indoor ones included, so the tag is named "night / low light". Neither is phone video.
- High thresholds on the small place tags (0.98 for field and temple) mean few shots will ever show them (recall
  0.13 and 0.34 here).
- Precision on the user's own footage can be measured from their approve/reject reviews with
  `eval/tag_feedback.py`; there are no reviews yet.

## 9. Embeddings, tags and scenes run on the user's footage (not an accuracy figure)
Script: `uv run python eval/embed_run_summary.py data`
Output: `eval/results/embed_run_summary_2026-10-14.txt`. OpenCLIP ViT-B/32 and MiniLM-L6 on the M1's GPU (MPS).
Figures below are from the first run, before the tag thresholds were installed; the tags shown after installing
them are listed at the end of this section.

21 clips (473.4 s), no failed job. Since the Phase 7 run, two of the clips turned out to be edited reels with real
cuts (17 and 29 shots), so there are 71 shots. 145 keyframes got a picture vector and a colour histogram; 50
transcript segments in 8 clips got a text vector (13 clips have no speech).
- Time: `embed_visual` 34.6 s in total, of which 30.5 s for the first clip (loading the model from the external SSD
  and the first GPU run); every later clip took 0.07 to 0.25 s. `embed_text` 5.8 s (4.7 s for the first clip with
  speech, model loading). `tags` 2.2 s (1.9 s for the first clip: the 1,137 vocabulary texts (42 tag descriptions and 365 categories, each in 3 phrasings) are encoded once per
  worker process). One run each; not a benchmark.
- Counted tags shown: "1 clear face" on 25 shots, "Speech" on 5.
- Scenes: 68 scenes from 71 shots. The combined similarity of neighbouring shots ranged from 0.27 to 0.92 (median
  about 0.55); 3 of 70 pairs reached the 0.8 convention. By eye, not measured: the two edited reels are travel
  montages that cut between waterfalls, a jeep, forest paths and faces every one or two seconds, so most
  boundaries there are real changes of place; shots of the same place often had a picture similarity of 0.75 to
  0.80 but a colour similarity of only 0.1 to 0.4, which keeps the combined value under 0.8. The single-take phone
  clips are mostly different places. Whether 0.8 is too strict cannot be said without labelled scenes.

A measured figure needs labels: correct the scenes on the Shots and scenes page (splits and joins are the labels).

After installing the thresholds of section 8 and processing again (cached results only, no model run; output
`eval/results/embed_run_summary_2026-10-14_thresholds.txt`): tags shown on the 71 shots: Daylight 68, Outdoor 54,
Indoor 15, Night / low light 3, Forest 3, plus the counted "1 clear face" 25 and "Speech" 5; no shot shows both tags
of a two-way group. Observation from looking at the keyframes of the night, indoor and forest shots, not a
measurement: the three forest shots are forest tracks and trees; most indoor shots are rooms or close-ups of puja
decorations, a few are debatable (decorations in a doorway, two people by a plant); two of the three "night / low
light" shots are dark scenes, the third (a jeep on a forest track in overcast light) looks wrong. Precision on this
footage needs the user's approve/reject reviews (`eval/tag_feedback.py`).
