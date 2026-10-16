# Progress

_Last updated: 2026-10-16_

## Project context
- Deadline / demo date: TBD (not provided)
- DaVinci Resolve: **free edition, 21.1.0** (read from `/Applications/DaVinci Resolve.app` Info.plist on 2026-10-09). Free edition: plan on a manual import test, do not rely on external scripting.
- Footage: `/Volumes/externalssd/CineMind-Footage` (set as `CINEMIND_MEDIA_ROOTS` in the gitignored `.env`), 21 clips since 2026-10-10 (the figures that follow describe the first 17), 1.9 GB, phone footage: 11 HEVC + 6 H.264, mostly 4K, 24/25/30/59.94/60 fps, average and base frame rate differ slightly on 10 clips, 1 is flagged variable frame rate by the 0.5 % rule, one 1080p 120 fps, one clip without audio. Languages: not stated by the user; the model detected English, Kannada and Hindi (unconfirmed)
- Machine: macOS (Darwin 25.5), Apple M1 8 cores, 8 GB RAM, Apple GPU (MPS), ~480 GB free on external SSD
- Recommended model tier: **lite** (see DECISIONS.md D-006)

## Phases
- [x] Phase 0: Environment, repo, docs, tooling
- [x] Phase 1: Backend core + DB + job system
- [x] Phase 2: Frontend shell
- [x] Phase 3: Ingest, metadata, proxies, thumbnails
- [x] Phase 4: Shots, keyframes + first timeline export (Resolve test). Confirmed by the user in DaVinci Resolve 21.1 free on 2026-10-09 (FCP7 XML)
- [x] Phase 5: Quality + audio QC (thresholds calibrated on synthetic degradations of real frames, see EVALUATION.md)
- [x] Phase 6: Transcription (WER measured on a public English sample; the user's own clips are not labelled yet)
- [x] Phase 7: Faces and actors (purity/ARI measured on a public face set; the user's own footage has no identity labels yet)
- [x] Phase 8: Embeddings, tags, scenes (tag thresholds evaluated on public labelled photos; scene limit is a convention, not evaluated)
- [x] Phase 9: Hybrid search (ablation measured on the user's footage with judgments by Claude; the user's own judgments pending)
- [x] Phase 10: Ranking, selects, explainability (learned re-weighting P1-D deferred to Phase 12)
- [ ] Phase 11: Rough cut engine + timeline UI (built and tested; **waiting for the user's DaVinci Resolve import of a rough cut**, the last acceptance item)
- [x] Phase 12: P1 differentiators: A script-to-footage alignment, B take detection / best take, D explainable ranking with what-if sliders (Phase 10), E search by reference image (Phase 9). C speech-aware word-level trimming not built (whole transcript lines are kept).
- [ ] Phase 13: Evaluation
- [ ] Phase 14: Polish, packaging, demo

## Current state
Phase 12B (take detection and best take) is done. Shots are grouped into takes by words (both with speech: words
agree at least 0.6, pictures at least 0.5) or by picture (at least 0.9 and at most 3 shots apart), average linkage
at a mean pair score of 0.75; the best take is the weighted mean of focus, exposure, audio, line completeness and
cleanliness (flubs, fillers, cut-off speech), every number shown on the Takes page. The editor picks another best
take or takes a shot out of a group; answers survive regrouping. The rough cut keeps one take per group. Measured
on the user's footage with Claude's labels (EVALUATION.md section 13): one real repeat found, one false pair (a
continuous shot split by a false cut); the footage has almost no retakes, so this is a sanity check only. Code review
fixes: clearing a reject re-ranks, score order keeps the replaced place, filters run before take choice, honest
"at most" word scores, pair notes when the score misses the limit.

Phase 12A (script-to-footage alignment) is done. The Script page reads a screenplay (Fountain or plain text), finds
every dialogue line in the transcripts (windows of up to 3 segments, lines marked uncertain never used), lists up to 5
takes per line with word and meaning scores, lets the editor pick a take or mark "not filmed" (kept through
re-alignment and through a replaced script for unchanged lines), and builds a script-ordered assembly that opens in
the timeline editor and exports like any rough cut. Measured on the Blender film Tears of Steel with its subtitles as
the script (EVALUATION.md section 12, test half): 29 to 30 of 48 lines right for all three variants (intervals
overlap); of the lines Whisper wrote down 19 to 20 of 24 found; 14 of 38 film lines were never transcribed; 8 to 9 of
10 invented lines rejected. Defaults chosen on the development half: meaning only, limit 0.3 (words only 0.45
without the text model); a weak preference. Code review found that the first evaluation counted the neighbouring
subtitle as right (0.71 reported, replaced), that uploading held the write lock during alignment, and several parser
and take-choice issues; all fixed with tests. Checked in the real app on the user's footage with a four-line test
script made from their English transcripts (both takes of the two repeated lines found, the invented line rejected,
assembly built), then deleted.

Phase 11 is built; its last acceptance item, the user's Resolve import of a rough cut, is open. The Timeline page
takes a one-sentence brief (plus optional length, order, person, scene) and builds an AI-assisted rough cut: rules read
the length and order (no language model), hybrid search + ranking give 50 candidates (rejected shots out), shots under
quality 0.5 or shorter than 1.5 s are left out with the reason, each shot is trimmed (whole certain transcript lines
with 0.25 s room, else 6 s around the matched moment), clips are added until the length is within 10 % of the target,
then ordered by source, scene or rank. Every clip stores why (rank, list ranks, score breakdown, matched line, trim
rule). The editor reorders by drag and drop (dnd-kit, also by keyboard), trims with frame-step sliders, removes,
swaps with suggestions (same scene first), plays the cut through the proxies clip after clip (next clip pre-seeked)
and exports FCP7 XML / EDL / OTIO with one marker per clip and the banner, plus SRT subtitles from certain lines.
Measured on the user's footage (eval/results/rough_cut_timing_2026-10-16.txt, M1 8 GB): 28.7 s for the first brief
(model loading), 0.2 s or less after; lengths within 10 % of the target. Time only; whether the clips suit the brief
has not been judged. Code review fixed: NaN in an edit (500), proxies ending early looping the file, brief phrases
read as lengths ("the 90s"), speech shots dropped instead of shortened by lines, edits racing, trims and removals not
reflected in the "why" and the suggestions.

Phase 10 is complete. Search results are ranked after fusion by a weighted sum of relevance, technical quality, the
user's selects / stars, named person and scene matches, minus a penalty for near-identical pictures (MMR, cosine
above 0.85); every card shows the breakdown (value × weight = contribution) and which shot it duplicates. What-if
sliders change the weights for one search and the order changes deterministically. Select / Reject / 1-5 stars on
search cards and the Shots page; rejected shots leave every result list unless "Show rejected"; "Selects only".
Marks are logged as feedback for a later learned re-weighting (P1-D, Phase 12). Measured with the same judgments as
Phase 9 (EVALUATION.md section 11): the default weights lower nDCG@10 slightly (test 0.907 to 0.881, dev 0.833 to
0.820); binary judgments cannot credit the variety the duplicate penalty adds. Not tuned on the test set.

Phase 9 is complete. The Search page finds shots by a typed query from four lists fused with Reciprocal Rank Fusion
(k = 60): spoken words (FTS5 / BM25), labels (shown tags, people, scene, file name), meaning of speech (MiniLM) and
picture (CLIP text side against keyframes); "more like this" and a dropped picture search by picture. Filters: clip,
person, scene, minimum technical score, with speech. Every card shows the matched line and, per list, the rank and
score that put it there; ✓ / ✕ judgments feed `eval/search_eval.py`. Measured on the user's 71 shots with 17
test queries judged by Claude from keyframes (EVALUATION.md section 10): the picture list alone reached nDCG@10
0.925, MRR 1.0; the fusion of all four 0.907 / 0.971 ("person walking": relevant first result). The text floor
(0.35) was chosen on 12 separate development queries; with the first floor (0.25) the fusion gives 0.817 / 0.814.
Code review fixed: searches no longer take the write lock, filters reach beyond each list's depth, uploaded
pictures are checked by header, tied scores share a rank. Details: AI_PIPELINE.md "Hybrid search".

Phase 8 is complete. Every keyframe gets a picture vector (OpenCLIP ViT-B/32 on this lite machine; SigLIP on the
larger tiers) and a colour histogram, every transcript segment a text vector (MiniLM, English); all vectors live in
the database and the per-project vector index files are rebuilt from them (exact numpy search on macOS, FAISS
elsewhere, D-079). Shots get tag suggestions: indoor/outdoor, day/night (low light), shot size and 20 place tags from
a zero-shot vocabulary, plus counted "clear faces" and "speech" tags. A model tag is shown only above a threshold set
and checked on labelled public photos (EVALUATION.md section 8): indoor, outdoor, day, night, forest, field, temple
and office are on; 14 place tags were switched off as too often wrong; shot size has no labelled data and is never
shown. The user can approve or reject any tag. Neighbouring shots are grouped into scenes by picture and colour
similarity (a convention: 0.8); the Shots and scenes page shows why every boundary is where it is and lets the user
split, join and rename scenes; edits survive regrouping. Models: `uv run cinemind models pull` (done here:
clip-vit-b32 578 MB, minilm-l6 87 MB, siglip-base 779 MB for testing). Details: AI_PIPELINE.md "Embeddings", "Tags",
"Scenes", "Vector index". Numbers: EVALUATION.md sections 8 and 9.

Phase 7 (faces and actors) is described in AI_PIPELINE.md "Faces and actors" and EVALUATION.md sections 6 and 7.
Phase 6 (transcription) is described in AI_PIPELINE.md "Transcription" and EVALUATION.md sections 4 and 5.

Fixes after Phase 8, from the user's feedback (2026-10-15):
- Clip page: Previous / Next and the P / N keys, in the library's current filter and sort.
- Actors: faces found in a single sampled frame are set aside as "seen briefly" (D-082; 27 actors became 14 on the
  user's project, the shirt, raincoat, mask and blurred faces among the 25 set aside). "Same person?" questions on
  the Actors page merge or keep apart look-alike people; the answers are labels for `eval/actor_pairs.py` (D-083).
- Transcripts: per-project spoken languages, "detect only" languages, a clip's language set by hand, and uncertain
  lines hidden by default (D-084). The user's project is English + Kannada (detect only): 6 English transcripts,
  5 Kannada clips marked as speech without text (EVALUATION.md section 5).
- Deleted `data/phase4-verify/` (the Resolve test it served is confirmed).

Next step: Phase 13/14 (evaluation summary, packaging, demo) and the course report. Still open from Phase 11: the user's Resolve import of a rough cut (TESTING.md, "rough cut import checklist"). The earlier reviews (✓ / ✕ on search results, selects / rejects) are still welcome: they also steer the rough cut.

Export path for the rest of the project (decided in Phase 4): FCP7 XML into DaVinci Resolve.

### Phase 4 run on the user's real footage (2026-10-09, M1 8 GB, `data/phase4-verify` (deleted 2026-10-15), not an evaluation)
Numbers from `eval/phase4_run_summary.py data/phase4-verify` (output kept in
`eval/results/phase4_run_summary_2026-10-09.txt`); one run, not a benchmark and not an accuracy figure:
- 17 clips, 352.7 s, 0 failed jobs. Stage wall time summed over the clips: proxy 200.4 s, shots 16.1 s, keyframes 7.3 s.
- 20 shots (3 detected cuts in 2 clips), 55 keyframes.

Observation by eye, not a metric: every clip is one continuous take, and the 3 detected cuts are not edits (camera
going under water and surfacing in `A3DE29FB…mov` at 2.08 s and 5.18 s; `IMG_0850.MOV` at 52.79 s). No precision or
recall is claimed; this footage has no real cuts, so recall cannot be measured on it.

Two timelines were exported from this run for the Resolve test (A: the ten 60 fps clips; B: all 17 clips, 10 at
another rate) in all three formats, in `data/phase4-verify/projects/5be0ca7ef72a4dc991a04bbad682f352/exports/`. Each
file was re-read with OTIO: same cuts, gapless.

## DEVELOPMENT PLACEHOLDERs
None.

## Open issues / notes
- Phase 12A, needs the user: if any of their footage was shot from a script, paste it on the Script page (English
  lines only can be matched; Kannada has no text, D-084) and say whether the suggested takes are right; that would be
  the first measurement on real takes instead of subtitles.
- Phase 12A limitations: only as good as the transcript (short shouts and speech under music are missed); meaning-only
  scoring lists short unrelated lines as weak takes; numbers compared as written; window vectors are re-embedded on
  every alignment (fine for tens of segments, untimed for thousands); the evaluation's script is subtitles (an upper
  bound) and its invented negatives are easy; no best-take judgement between takes (that is 12B).
- Phase 11, needs the user: (1) build a rough cut on the Timeline page, export the FCP7 XML and the SRT, import both
  into Resolve 21.1 and fill in TESTING.md "Results (Phase 11)" (are the markers there? where does the SRT land?);
  (2) say whether the chosen clips suit the briefs, so the selection can be judged instead of only timed.
- Phase 11 limitations: the cut is only as good as search (one query per brief, no beats); shots under 1.5 s are left
  out, so edited reels lose most shots; trimming keeps whole Whisper lines (word / pause level is P1-C); source order is
  file name, not capture time; cuts only (no transitions, music or levels); the preview's cut is checked about 60
  times a second (can run a frame or two late; exports are frame-exact); Resolve's handling of FCP7 sequence markers
  and of the SRT start is unconfirmed. Left open from review: a swap accepts a shot rejected after the cut was built;
  the Timeline list has no delete button (the Export page has one); `/favicon.ico` 404s.
- Verification runs on the user's project created and then deleted their rough cuts; the app's own data was not
  otherwise changed (migration 0014 adds one nullable column).
- Phase 10, needs the user: select and reject shots while browsing (Shots page or Search), and judge a few searches;
  then the ranking can be measured with selects and with the user's own sense of relevance.
- Phase 10 limitations: default weights are conventions and cost a little nDCG on Claude's picture-only judgments;
  the duplicate threshold 0.85 is a convention placed from the similarity spread of this footage; quality is the
  shot's Technical Quality Score only (no aesthetic score); no learned re-weighting yet (P1-D, Phase 12); MMR is
  quadratic in the number of results (fine at 50).
- Phase 9, needs the user: search for a few things you would look for when editing and mark results ✓ / ✕; then
  `uv run python eval/search_eval.py run data --judge user --out` gives figures from your own judgments (the current
  ones are Claude's, from still keyframes, on queries that favour pictures).
- Phase 9 limitations: the fused order is slightly below the picture list alone on these picture-only queries (a
  transcript line or a partly wrong tag can still lift an unrelated shot); weights are fixed until Phase 10's
  weights panel. The first search after a start loads the models in the API process (observed: about 26 s once;
  memory not measured; the worker holds its own copies). Judgments are Claude's, from still keyframes. Spoken-word search needs
  every word in one line. Labels are matched by a scan, fine for hundreds of shots, untested for many thousands. No
  selects / rejects, no MMR, no quality term in the order (Phase 10). Picture search sees one to three keyframes per
  shot, not motion ("walking" is judged from a still).
- Phase 8, needs the user: (1) review tags on a few clips (approve / reject); `eval/tag_feedback.py` turns that into
  precision on this footage; (2) correct the scenes of one edited reel on the Shots and scenes page, so the scene
  limit (0.8, a convention) can be measured instead of guessed. Spoken languages: answered (English and Kannada;
  Kannada has no transcripts, so the English text model is enough for now).
- Phase 8 limitations: tag thresholds come from web photos (Places365) and low-light object crops (CODaN), not video;
  precision depends on how common a tag is. The shot rule (more than half of the keyframes) is not evaluated. Shot
  size is never shown (no open labelled set; CineScale is by request). On this footage 71 shots became 68 scenes:
  the two edited reels are montages, and same-place shots score about 0.75 to 0.80 on pictures but 0.1 to 0.4 on
  colour. Scenes compare neighbours only, in file-name order, not capture time. Sideways phone clips are embedded
  sideways. SigLIP so400m (quality tier, 3.4 GB) was never downloaded or run here; siglip-base was smoke-tested only
  (no thresholds for it, so its model tags stay hidden until `eval/tag_calibration.py run --model siglip-base
  --install`). Peak memory with Whisper, CLIP and MiniLM loaded in one worker was not measured. Left open from review:
  `api/media.py` is still 406 lines; the doctor repeats the model choice of `embedder`; a truncated model file shows
  a generic error instead of "download again"; deleting old embedding folders happens before the commit.
- Phase 7, needs the user: (1) answer the "Same person?" questions on the Actors page and fix mixed groups with
  Split (seen 2026-10-15: one group still holds the blue-cap person and the person with glasses); the answers and
  corrections are the labels a figure for this footage needs (`eval/actor_pairs.py`); (2) say whether keeping
  YuNet + SFace on every tier is acceptable or InsightFace should be added (D-061).
- Phase 7 limitations: the grouping is a suggestion; on the user's footage some groups mix different people and one
  person is spread over several groups (seen by eye, not measured). Small, turned, blurred or covered faces are
  left out (45 % of detected faces here). Only YuNet + SFace is implemented, on the 720p proxy. The face-check
  limits and the tracking limits are conventions, not evaluated. Tracking is not evaluated. Evaluation is on a
  public photo set that is far easier than footage. No face boxes are drawn on the player, no "speaking time per
  actor", no actor filter in the library, actor names are not in the keyword index yet (Phase 9). The Actors page
  loads every person and crop at once (fine for tens of people, untested for thousands of tracks). Left open from
  review: grouping memory is not capped (full distance table); a pre-Phase-7 job retried after a `[faces]` change
  can reuse a stale scan; the reasons behind a face's placement are tooltips only (not reachable by keyboard or
  touch); merging two named people keeps one name without asking; `api/media.py` is 406 lines.
- Phase 6, needs the user: (1) languages answered (English, Kannada); (2) read the transcripts of
  "Timeline One.mov" and "5A9A…mov" in the app and say whether the words are right; (3) for a WER on own material, write the true
  words of one or two clips into `clip.txt` files (EVALUATION.md section 4).
- Phase 6 limitations: on noisy clips without clear speech (water, music, crowds) Whisper writes fluent text that was
  never said; it is marked uncertain in most but not all cases (uncertain lines are hidden by default since
  2026-10-15; fluent text that passes the model's own limits is still shown). Results on such audio differ
  from run to run, and those clips are slow (up to 166 s for one clip here). One language per clip. `small` is weak
  outside English; `medium` (1.5 GB) was not tried on this 8 GB machine. The keyword index has no stemming and is
  tested with English plus a few Hindi and Kannada words. The GPU path has never run on a real NVIDIA card. No speaker labels, no subtitle (SRT) export, no transcript editing, no "speech present" quality flag. The
  whole audio of a clip is held in memory. The transcript list re-renders on every time update (fine for short
  clips, untested on hour-long ones). Search results are capped at 50 without paging. `models pull` cannot repair a damaged model folder (delete
  the folder under `data/models/whisper/` and pull again). The evaluation download has no checksum.
- E2E: `T e2e` (Playwright, real built app, throwaway `data/e2e`). Needs a one-time `pnpm exec playwright install chromium`; here only full Chrome for Testing downloaded (headless shell stalled), so `playwright.config.ts` uses `channel: "chromium"`.
- shadcn/ui is deferred until a screen needs a dialog/table (D-021); delete confirmation uses `window.confirm` for now. Wavesurfer, Recharts and dnd-kit arrive with their screens.
- Phase 5 limitations: the flag thresholds were calibrated on synthetically degraded frames from 17 phone clips, not
  on human labels; held-out numbers are an upper bound (EVALUATION.md). Focus measures depend on content (fog, water,
  plain walls read as soft); a few blurred frames inside a sharp shot are not flagged (median per shot); bright scenes
  are flagged overexposed. Left open from review: the source audio is decoded twice (loudness pass, clipping pass);
  the quality stages' cache keys chain through keyframes, so changing keyframe settings re-measures audio; each
  metric row stores a full copy of the settings. Weights, the low-quality limit (0.5) and all audio thresholds are conventions. No
  face-region sharpness, noise, shake or speech-present measure yet. No dashboard charts yet. Existing projects need
  "Process all" once to get scores (earlier stages come from the cache).
- Resolve: confirmed by hand for FCP7 XML only (Resolve 21.1 free, the user's 17 phone clips). Not individually confirmed: frame-exact in/out on mixed-rate and variable-rate clips, EDL import, OTIO import.
- The built UI was served without `Cache-Control`, so a browser could keep showing the previous build after an update (the user saw the Phase 3 placeholder on the Shots page). The page is now sent with `no-cache`.
- Footage with real cuts is still needed: the user's folder is all single-take phone clips, so shot detection has only
  been checked against synthetic cuts (exact) and for false positives on real footage (3 in 352 s). An edited video with
  hand-marked cuts is needed before thresholds are tuned (Phase 13). Also still missing: a clip with embedded timecode
  and one with dialogue (Phase 6).
- Phase 4 limitations: mixed frame rates in one timeline are converted to the timeline rate and can be one frame off;
  an EDL cannot express them. Variable-frame-rate sources are addressed by time, so a cut can land on a neighbouring
  frame in the editor (the timeline warns). A source whose first frame is not at time 0 is not compensated. Timelines cannot be edited yet
  (Phase 11). No markers or SRT export yet. Shots cannot be split or merged by hand. The project shot list is not
  paginated. Portrait clips (rotation metadata) are exported with their display size; untested in Resolve.
- Review items left open on purpose: export is a GET that writes a file; a timecode track counted on a different base
  than the video rate (some 50/59.94p cameras) is not handled and needs a real timecoded clip to check; illegal
  drop-frame labels are accepted; the EDL header says non-drop while a drop-frame source keeps `;` (Resolve test decides).
- Phase 1 known limitations (from review, deferred): single worker assumed (D-016, no lease/lock file); SSE uses a sync polling generator (no async disconnect detection, `job_events` never pruned); `cancel`/`retry` are not atomic conditional updates; `resolve_in_roots` accepts relative paths (Phase 3 callers reject them before calling); 
- Phase 3 limitations: `media_roots` must be set by hand in `cinemind.toml` (no UI to add roots); the Library has no sort/filter/bulk actions yet (later phases add the data they sort by); no job cancel/retry buttons in the UI yet (API exists); proxy hardware encoders other than VideoToolbox/libx264 are untested here (no NVENC/QSV on this machine); HEVC/ProRes decoding speed on the 8 GB M1 not benchmarked (no numbers claimed).
- Phase 2 limitations: `e2e/` is linted but not type-checked by `T check`; the SSE hook is unit-tested with a fake EventSource and only the connected indicator uses it (no job UI yet, so no E2E for live progress); the Playwright port 8765 is fixed.
