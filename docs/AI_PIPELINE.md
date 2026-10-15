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
| 9 | transcribe | faster-whisper (Whisper weights on CTranslate2) with its Silero voice-activity detector | model choice per hardware tier, offline model handling, stored shape, "uncertain" marking, keyword index |
| 10 | faces | OpenCV `FaceDetectorYN` (YuNet) and `FaceRecognizerSF` (SFace) | frame sampling, the four face checks, tracking inside a shot, what is stored |
| 11 | embed_visual | OpenCLIP ViT-B/32 or SigLIP picture tower via `transformers`; OpenCV `calcHist` | image preparation, model choice per tier, offline model handling, HSV histogram, storage |
| 12 | embed_text | MiniLM sentence model via `transformers` | mean pooling, storage per transcript segment |
| 13 | tags | the picture model's text tower | vocabulary, prompts, scores, evaluated thresholds, counted face and speech tags |

Every stage result is cached by (media content hash, stage, parameters, tool version) and chained to the stage
before it. Stages 7 and 8 cache MEASUREMENTS only; scores and flags are recomputed from them with the current
settings every time the job runs, so a changed weight or threshold needs no video decoding ("Process all").
Stage 9 is chained to stage 1 only (the source file), so shot or quality settings never send audio through the
speech model again.
Stage 10 is chained to stage 5 (the shots). Grouping the faces of a whole project into actors is not a stage: it
runs after a project's last queued job and after "Group again" (see "Faces and actors").
Stage 11 is chained to the keyframes, stage 12 to the transcript, stage 13 to stage 11. Stage 13 caches raw scores
only; which tags are shown is decided from `ai/tag_thresholds.json` every time the job runs. Scenes and the vector
indexes are project-wide, like actors (see "Scenes" and "Vector index").

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
- No face-region sharpness yet (needs faces, Phase 7), no noise or shake metric. The transcript (stage 9) is not
  part of the score.

## Transcription (stage 9)
**Existing parts.** The speech model is OpenAI Whisper, run by faster-whisper (CTranslate2). Speech is found first
by the Silero voice-activity detector that faster-whisper ships, so silence and noise are not sent to the model.
Word times come from the model's cross-attention alignment (`word_timestamps`). None of this is ours.

**Ours.**
- *Model choice.* `[transcribe] model = "auto"` takes the hardware tier's model: lite and balanced `small`,
  quality `large-v3` (all multilingual). Each model is pinned to a repository revision
  (`core/transcribe_config.py`); the name and revision are stored with every transcript.
- *No download while processing.* `uv run cinemind models pull` fetches the model once into `data/models/`.
  The stage only reads that folder. Without the model the clip is processed as usual, the transcript is recorded
  as `model_missing`, every transcript view says how to fix it, and the next run tries again.
- *Audio.* The original file's first audio stream, decoded by our ffmpeg call to 16 kHz mono.
- *Settings* (all part of the cache key and stored with the transcript): `language` (`auto` = detected from the
  start of the speech, one language per clip), `beam_size` 5, `vad_threshold` 0.5, `vad_min_silence_ms` 2000,
  `device`/`compute_type` (`auto` = int8 on the CPU, float16 on an NVIDIA GPU; an automatically chosen GPU that
  fails to load falls back to the CPU). The numeric values are the library's defaults, not tuned by us.
- *What is stored.* Per segment: start, end, text, the model's `avg_logprob`, `no_speech_prob` and
  `compression_ratio`, and `confidence` = mean of the word probabilities. Per word: start, end, text, probability.
  Segments made only of punctuation are dropped.
- *Uncertain.* A segment is marked uncertain when `avg_logprob < -1.0` or `compression_ratio > 2.4`. Those are
  Whisper's own acceptance limits: it retries such a segment at higher temperatures and keeps the last attempt even
  if that fails too. The language is marked a guess when its probability is under 0.5 (Whisper's own
  `language_detection_threshold`). These limits are conventions taken from the model; we have not evaluated them.
  Uncertain text is kept and stored, but hidden on the clip page until the user asks for it ("Show them") and left
  out of keyword search unless `include_uncertain` (D-084).
- *Spoken languages* (per project, set on the Transcripts page; D-084). When the user lists the languages of the
  footage, the language of each clip is detected among those only: faster-whisper's `detect_language` runs on the
  speech the voice-activity detector keeps, and the listed language with the highest probability wins; the stored
  probability is its share among the listed ones, and the model's top five over all languages are kept in
  `details.language_scores`. A listed language can be "detect only": its clips get the state `not_written` with the
  seconds of speech and no text, and are not sent through the model. A clip's language can also be set by hand
  (clip page), which outranks detection. The project's languages and a clip's language are part of the cache key
  only when set, so projects without them keep their caches.
- *States.* `done`, `no_speech` (the detector or the model found nothing), `no_audio`, `model_missing`,
  `audio_unreadable` (the picture results are kept), `not_written` (speech in a "detect only" language). Each has a
  plain message in the API and the UI.

**Keyword search.** Segment text is indexed in an SQLite FTS5 table (tokenizer `unicode61`, diacritics removed,
combining marks kept inside words so Hindi or Kannada words are not cut at their vowel signs).
A query is split at spaces; every term must occur and matches the beginning of a word (`walk` finds `walking`);
quotes and operators typed by the user are treated as text. Ranking is SQLite's BM25. Each hit carries `jump_s`,
the start time of the first word that begins with the first search term (the segment start if none does). With
several terms that is the first term's word, not necessarily the earliest match.
This is the keyword part of search only; semantic and visual search come in Phase 9.

### Known limits
- Whisper invents fluent text for music, crowd noise, wind and water; the voice-activity detector lets some of that
  through. On the user's own phone footage most "transcripts" of noisy clips are of this kind (EVALUATION.md).
- Results on hard audio are not repeatable: the retries sample at random, so a clip transcribed again after a cache
  miss can come out with different words or a different language. Finished results are cached and do not change.
- Hard audio is slow: every retry decodes the segment again (seconds of audio can take a minute on the CPU).
- One language per clip, detected from the beginning. Mixed-language clips are transcribed as the first language.
- The `small` model is weak on many languages other than English; a larger model needs more memory than the lite
  tier has. On the user's Kannada clips it wrote no usable Kannada at all: forced to Kannada it gave broken script or
  English sentences, forced to English it gave fluent English that was not said (checked by eye on four clips,
  2026-10-15). Kannada is therefore "detect only" in the user's project.
- Times are relative to the start of the audio stream; a stream that starts late in the file is not compensated.
- The whole audio is held in memory: about 230 MB per hour while transcribing, about 350 MB per hour for a moment
  while it is decoded (by reading the code, not measured).
- The keyword index is tested with English and with a few Hindi and Kannada words; no stemming. Scripts without
  spaces between words are not segmented.
- `audio_unreadable` and `model_missing` are tried again on every run; a GPU that fails while decoding is replaced
  by the CPU only when the device was chosen automatically (tested with a stand-in, never on a real NVIDIA GPU).

## Faces and actors (stage 10 and the project-level grouping)
**Existing parts.** YuNet finds faces and five landmarks per face; SFace turns an aligned 112 px face crop into a
128-number vector. Both are models from the OpenCV model zoo, run by OpenCV itself. Grouping uses scikit-learn's
average-linkage agglomerative clustering or HDBSCAN, and SciPy's assignment solver for tracking. None of this is
ours.

**Ours.**
- *No download while processing.* `uv run cinemind models pull` fetches both files once (37 MB) into
  `data/models/faces/` and checks each against a SHA-256. Without them a clip is processed as usual, its faces are
  recorded as `model_missing`, the Actors page and the clip page say how to fix it, and the next run tries again.
- *Sampling.* `sample_fps` (2) frames per second of the proxy, in one sequential decode.
- *Which faces are used.* Every box the detector returns with confidence >= 0.6 is counted as detected. A face is
  used only if it passes four checks, in this order; the first one failed is counted per clip:
  `low_score` (detector confidence < `min_score` 0.8), `small` (shorter box side < `min_size_px` 40 on the proxy),
  `turned` (`turn` > `max_turn` 0.6), `blurry` (variance of the Laplacian of the aligned crop < `min_sharpness` 20).
  `turn` = distance of the nose from the middle of the eyes, measured along the eye line, divided by the eye
  distance: 0 for a frontal face, larger towards a profile; a head tilted sideways stays 0.
  These four limits are conventions, not values we evaluated.
- *Tracking.* Inside one shot, the used faces of a sampled frame are matched one to one to the open tracks so that
  the total similarity is highest. A face may continue a track when the cosine similarity of its vector to the
  track's mean vector is >= `track_similarity` (0.363, the SFace authors' same-person threshold), or >= half of
  that while its box overlaps the track's last box by >= `track_overlap` (0.5 intersection over union). A track ends
  at the end of the shot or after `track_max_gap_s` (2 s) without a match. A track's vector is the mean of its
  faces' vectors; one crop (the largest, most confident face) is kept per track for the UI.
- *Files.* Each scan writes its crops and track vectors into a folder of its own, named after its settings
  (`faces/<clip>/<settings hash>/`), so a cached result can never be paired with another scan's files. If the proxy
  ends more than 2 % (and two samples) before the frame count shot detection saw, the stage fails with a message
  instead of storing "no faces" for footage nobody looked at. If the models are missing after an earlier good
  scan, that scan's tracks and actors stay and only the state changes.
- *Grouping into actors* (two passes, SPEC section 9). Pass 1 groups the tracks of each clip; pass 2 groups across
  the project, starting from the pass-1 groups. Both use `cluster_method` (`agglomerative`, average linkage) and
  `cluster_distance` (0.6 cosine distance; confirmed in EVALUATION.md section 6). HDBSCAN has no distance setting
  and none is recorded for it. Two tracks with a face in the same
  frame are never grouped (their distance is set so large that no average falls under the threshold). HDBSCAN can
  still join such a pair through a chain of others; a group where that happened is regrouped with the
  agglomerative method.
- *Faces seen briefly.* A track with fewer faces than `min_track_faces` (2, i.e. found in a single sampled frame at
  2 frames per second) is not grouped: it gets the state `brief`, no actor, and is listed apart on the Actors page
  ("Seen briefly"), where the user can add it to a person or mark it "not a face". A convention, not an evaluated
  limit: on the user's footage every shirt, raincoat, mask and motion-blurred face that had become an actor was a
  one-frame track (checked by eye, D-082). A user correction outranks it.
- *"Same person?" questions.* The Actors page asks about the pairs of people whose faces look most alike: average
  linkage over their tracks (mean of 1 - cosine), closest first, at most 12, never two people seen in the same frame
  and never a pair already answered "different". "Same" merges them (into the named one, else the one with more
  faces; an ordinary merge correction). "Different" is stored by track (`actor_pair_answers`) and keeps those
  tracks apart in every later grouping, unless a later correction puts them with one person. Each answer stores
  the distance the pair had, which `eval/actor_pairs.py` turns into a measurement of the grouping limit (D-083).
- *Names and identity.* A new group becomes "Actor 001", "Actor 002", ... (the lowest number not in use). A group
  keeps the actor most of its faces belonged to before, also across a rescan of a clip, so numbers and names stay
  put when the project is grouped again. Actors are local to the
  project and are never matched to a real-world identity.
- *Corrections.* Rename, merge, split, move to another person, "not a face" and "unknown person" change exactly
  the chosen appearances and nothing else; the project is not grouped again. Each correction also stores a pin for
  every face of the affected tracks (clip, time, box, and the actor or "set aside"). Two kinds of actor pin are
  told apart: `actor` for tracks the user moved by hand ("placed by you"), and `kept` for tracks that were already
  with a person when the user named, merged or corrected that person ("kept with this person by your correction";
  their similarity figures stay stored). When the project is grouped again, pinned tracks of one actor are merged
  into one point before clustering, tracks pinned to different actors are kept apart, and set aside tracks are
  left out. After a clip was scanned again a pin finds its face by place: a face of the same clip within 0.5 s
  whose box overlaps the pin's by >= 0.3. A track takes the majority of its pins, but only if those pins reach
  over at least half of the time the track covers, so one stray pin does not decide a long track. Pins that find
  no face are kept and counted. "Hand back" removes the pins and groups the project again. Every correction is
  also appended to `feedback_events`.
- *When grouping runs.* After an ingest job once no job of the project is queued or running, when the last queued
  job is cancelled, when a clip is removed, on "Group again", and on "hand back". It is skipped when nothing it
  depends on changed (scans, pins, method, distance). A correction made while scans still wait to be grouped does
  not mark the project as up to date. Grouping and corrections take SQLite's write lock before they read, so the
  API and the worker cannot overwrite each other.
- *What is stored* (rule 6). Per clip: status, frames sampled, faces detected and used, the most faces in one
  frame, the count per failed check, models, revisions and settings. Per face: frame, time, box (fractions of the
  frame), detector confidence, size, sharpness, turn. Per track: time range, mean vector, crop, actor, state, and
  why it sits there (by similarity with its similarity to the group's mean, the method and distance; or placed by
  the user). Per grouping run: engine, method, distance, counts.

### Known limits
- The grouping is a suggestion. On the user's own footage several groups visibly mix different people and the same
  person appears in several groups (EVALUATION.md section 7); the public test set in section 6 is far easier.
- Small, turned, blurred, covered or badly lit faces are left out, so a person seen only that way is not found, and
  "seconds seen" counts only the time a usable face was tracked.
- YuNet and SFace are the lite-tier pair of SPEC section 6. InsightFace (the stack's first choice for the larger
  tiers) is not implemented; every tier uses YuNet + SFace for now (DECISIONS D-061).
- Faces are searched on the 720p proxy; a face that is small in a wide 4K shot is lost.
- Two people who never share a frame and look alike to the model are merged; twins and children are known weak
  spots of face models in general (not measured here).
- A pin is found again by place and time. If a clip is replaced by a different edit of itself, its pins stay
  unmatched.
- Tracking at 2 frames per second relies on the face vector far more than on position; a face that leaves and
  returns within 2 s continues its track.
- Grouping builds a full distance table of all tracks in memory (about 0.4 GB at 7000 tracks) and is not capped;
  this project has 72. A job created before this phase and retried after a `[faces]` change can reuse a stale
  cached scan (its cache key has no face settings); "Process all" creates a new job and does not have that problem.

## Embeddings (stages 11 and 12)
Existing models (D-070), each pinned to a revision with a SHA-256 and fetched only by `cinemind models pull`:

| Tier | Picture model (`[embed] visual_model`) | Text model (`[embed] text_model`) |
|---|---|---|
| lite | OpenCLIP ViT-B/32, LAION-2B (`clip-vit-b32`, 512 numbers) | all-MiniLM-L6-v2 (`minilm-l6`, 384, English) |
| balanced | SigLIP base 224 (`siglip-base`, 768) | same |
| quality | SigLIP so400m 384 (`siglip-so400m`, 1152) | same |

`multilingual-minilm-l12` (50+ languages) is a setting. Device: an NVIDIA GPU if present, else Apple's GPU (MPS),
else the CPU; an automatically chosen GPU that fails falls back to the CPU once.

Ours:
- Image preparation with OpenCV from each model's `preprocessor_config.json`: resize (shortest side, or to a fixed
  size), centre crop, scale, normalise (D-071). Every keyframe of the clip (1 to 3 per shot, D-038) is embedded.
- A colour histogram per keyframe: HSV, 8 x 4 x 4 bins, on the frame shrunk to 180 px high, summing to 1.
- MiniLM: mean of the token vectors over the attention mask, then unit length.
- Every vector is stored in `embeddings` (picture vectors and histograms per keyframe, text vectors per segment), with
  the model name. A clip whose model is missing records `model_missing`, keeps whatever an earlier run stored, and
  is tried again on the next run; when the model is back, the cached result restores the state. Text vectors wait
  for a transcript (`no_transcript`) when there is none yet.

## Tags (stage 13)
Not facts: suggestions with a score, shown only when the score passes a threshold that was set and checked on
labelled photos. Existing model: the picture model's text tower. Ours: everything below (D-073 to D-076).

Vocabulary (`ai/tagger.py`, version 1):
- `setting`: indoor, outdoor. `time`: daylight, night / low light. `shot_size`: close-up, medium, wide.
  Each tag has two descriptions, each in three phrasings ("a photo of ...", "a video frame of ...", "a film still
  of ..."); their vectors are averaged.
- `place`: 20 tags (beach or coast, open sea, underwater, waterfall, river or lake, swimming pool, forest, mountain,
  field, street, highway, inside a vehicle, temple, kitchen, bedroom, living room, restaurant or café, office,
  classroom, stage), each standing for one to five of the 365 Places365 scene categories.

Score of a tag for one keyframe, with `s(t)` = cosine between the keyframe vector and the tag's text vector and `T`
the model's learned temperature (100 for CLIP):
- prompt groups: `score(t) = exp(T s(t)) / sum over the tags u of its group of exp(T s(u))`
- places: `p(c)` = the same softmax over all 365 categories; `score(tag) = sum of p(c) over the tag's categories`
A shot's displayed score is the mean over its keyframes; the three best Places365 categories of each keyframe are
kept for the "why". Scores are shares inside a group (0 to 1), not probabilities.

Shown or not (`tags.status`): thresholds were set on single photos, so they are applied per keyframe: `shown` when
more than half of the shot's keyframes (on a tie, their mean score) reach the threshold and the tag type is enabled in
`ai/tag_thresholds.json`; `below` under it; `disabled` when the evaluation switched the tag type off; `not_evaluated`
when no labelled data exists for it (shot size). Thresholds belong to one model revision and vocabulary version
(`clip-vit-b32@1a25a446712b+v1`); another model has none until `eval/tag_calibration.py run --model ... --install`
was run for it, so all its tags are `not_evaluated`. How the thresholds were set and how often a shown tag was right
on the held-out photos: EVALUATION.md section 8.

The user's decision outranks the threshold: approved tags are shown, rejected tags never are; decisions are kept
by shot id when the clip is processed again and logged with the suggested score (`eval/tag_feedback.py` turns them
into precision on the user's own footage).

Counted tags (no model, no threshold; the rule is stored with the tag): "N clear faces" = most usable faces found in
one sampled frame of the shot (faces left out by the face checks are not counted); "Speech" = transcript segments
not marked uncertain cover at least 1 s of the shot.

## Scenes (project-wide, after the last queued job)
Ours, no model of its own (D-077). Shots in the order clips sort by file name, then source order. Each shot is
compared with the one before it:

```
visual   = cosine(mean picture vector of shot A, of shot B)      (both unit length)
colour   = sum over bins of min(mean histogram A, mean histogram B)
combined = (0.7 visual + 0.3 colour) / (sum of the weights of the signals both shots have)
           only when both shots have picture vectors (colour alone is on another scale)
same scene  <=>  combined >= 0.8        ([scenes] visual_weight, color_weight, join_similarity)
```

The weights and 0.8 are conventions, set before running on real footage and not tuned: no labelled scenes exist. A
shot without picture vectors starts a new scene ("no picture vectors to compare"). The user's edits outrank the
rule: `split` (a scene starts at this shot), `join` (this shot stays with the one before), and a name kept on the
scene's shots. Grouping runs after the last queued job, after a clip is removed, and on "Group again"; it is skipped
when shots, picture vectors, edits and settings are unchanged. Every boundary stores both signals, the combined value
and the decision in words; the Shots and scenes page shows them.

## Vector index
Existing library: FAISS `IndexFlatIP` (exact inner product = cosine on unit vectors), or an exact numpy search with
the same results, behind `search/vector_index.py`'s `VectorIndex`. `[embed] index_backend = "auto"` uses numpy on
macOS, where FAISS and torch load clashing OpenMP runtimes into one process and it aborts (D-079), and FAISS
elsewhere. One file per project, kind (`keyframe`, `segment`) and model under
`data/projects/<id>/index/`, plus a `.ids.json` mapping positions to keyframe or segment ids. Files are derived from
the `embeddings` rows: rebuilt after the last queued job, when asked (`POST /api/projects/{id}/index/rebuild`), or
before a search when the rows' digest differs from the one the file was built from.

## Hybrid search (Phase 9)
Existing pieces: SQLite FTS5 with BM25, MiniLM (sentences), CLIP / SigLIP (pictures and their text side), and
Reciprocal Rank Fusion (Cormack, Clarke and Buettcher 2009). Ours: what each list covers, how a line or keyframe
becomes a shot, the label matching rule, the filters and the explanation. Code: `search/retrievers.py`,
`search/hybrid.py`. The unit of a result is a shot.
- *Four lists*, each a ranking of shots with one entry per shot (its best line or keyframe) and its own score:
  `keyword` (FTS5 / BM25 over transcript lines; every word must occur, matched from the start of a word; uncertain
  lines left out), `labels` (the query's words against the shot's shown or approved tags, actor names, scene name and
  file name; people only once the user named them; a label word matches a query word when equal, or when the query
  word has 4+ letters and starts it, so "walk" finds "walking"; small words such as "a", "of", "in" are ignored;
  ranked by how many query words matched), `text` (the query through MiniLM against
  transcript-line vectors; lines under cosine `text_min_similarity` 0.35 are left out, chosen on a development set
  of queries, D-086), and
  `visual` (the query in the CLIP prompt "a photo of {query}." against keyframe vectors; best keyframe per shot).
- *A line or keyframe becomes a shot* by time: the shot of that clip whose start is the last one at or before the
  spoken word (keyword), the line's start (text), or the keyframe's own shot (visual).
- *Fusion*: each list gives a shot `weight / (k + rank)`; the fused score is the sum (`[search] rrf_k` 60, weights
  1, depth 100 per list, 50 results). RRF needs no calibration between a BM25 value and a cosine. The fused score
  orders results only; it is not a probability. Equal scores in a list share a rank. With a filter set every list
  is searched in full and cut after filtering. The jump time is the best evidence: a spoken word, then a line, then
  a keyframe, then the shot start (D-085).
- *By picture*: "More like this" uses the mean picture vector of a shot's keyframes (the shot itself is left out);
  a dropped picture (JPEG / PNG / WebP, up to 15 MB, read in memory only) goes through the picture model. Both use
  the visual list only.
- *Filters* (clip, person, scene, minimum Technical Quality Score of the shot, "with speech" = the shot's speech tag
  is shown) remove shots from every list before fusion.
- *Explanation*: every result carries, per list it is in, its rank, the list's own score, what it added to the
  fused score, the matched line with the matched words marked, and the labels that matched.
- *Models in the API process*: the query is embedded in the API process (observed once on the M1, not measured:
  the first search after a start took about 26 s while the models loaded, later ones 0.05 to 0.8 s). A list whose
  model is not downloaded, or whose vectors were made with another model, is reported as off with how to fix it;
  the others still answer. Nothing is downloaded (`HF_HUB_OFFLINE` and `TRANSFORMERS_OFFLINE` are forced on).
- *Index and locks*: a search compares a cheap fingerprint of the rows (count and id range, no vectors read) with
  the one the index file was built from, and searches the file as it is when they match, without any lock. Only a
  changed index is rebuilt, and that rebuild is committed at once, after the query was embedded, so the write lock
  is held for the build alone. Loaded index files are kept in memory, by file (each build has its own file name).
- *Pictures sent by the user* must be JPEG, PNG or WebP (checked from the first bytes) and at most 40 megapixels
  (read from the header before decoding).
- *Judgments*: on a text search the user can mark a result good or not (✓ / ✕). These marks do not change the
  order; they are the labels `eval/search_eval.py` measures against (EVALUATION.md section 10).

### Known limits
- Thresholds were set on web photos (Places365) and object crops in low light (CODaN), not on video frames; precision
  on a user's footage depends on how common each tag is there. Shot size is never shown (no labelled data).
- A keyframe that is sideways in the source (phone held sideways with rotation locked) is embedded sideways.
- Scenes: neighbour comparison only (a shot is never compared with the one two places back); montages that cut
  between places every second give almost one scene per shot. Clips are ordered by file name, not capture time.
- The English text model gives poor vectors for Hindi or Kannada transcripts; the multilingual model is a setting.
- The models stay loaded in the worker next to Whisper (weight files: 0.6 GB for CLIP B/32, 0.09 GB for MiniLM); peak memory was not measured.
- Search: the API process holds the picture and text models after the first search (about 0.7 GB of weights more;
  not measured). On the user's footage the fused ranking scored below the picture list alone, because a transcript
  line above the text floor, or a partly wrong tag, can lift a shot above better picture matches (EVALUATION.md
  section 10). Spoken-word
  search needs every word in one line. Labels depend on the tags, which have known errors. No selects / rejects yet
  (Phase 10).
