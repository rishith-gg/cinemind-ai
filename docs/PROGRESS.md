# Progress

_Last updated: 2026-10-10_

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
- [ ] Phase 8: Embeddings, tags, scenes
- [ ] Phase 9: Hybrid search
- [ ] Phase 10: Ranking, selects, explainability
- [ ] Phase 11: Rough cut engine + timeline UI
- [ ] Phase 12: P1 differentiators
- [ ] Phase 13: Evaluation
- [ ] Phase 14: Polish, packaging, demo

## Current state
Phase 7 is complete. Each clip is searched for faces on this machine (OpenCV YuNet + SFace, 2 frames per second);
usable faces are followed through their shot and the tracks of the whole project are grouped into actors
("Actor 001", ...). The Actors page shows the people; a person can be renamed, merged, split, and single appearances
moved, marked "not a face" or "unknown person". Corrections change only what was chosen, are stored as pins, and
come back when the project is grouped or scanned again. The clip page lists the people in the clip. The face models
are downloaded once with `uv run cinemind models pull` (done here: 37 MB in `data/models/faces/`); processing never
downloads. Details: AI_PIPELINE.md "Faces and actors". Numbers: EVALUATION.md sections 6 and 7.

Phase 6 (transcription) is described in AI_PIPELINE.md "Transcription" and EVALUATION.md sections 4 and 5.

Next step: Phase 8 (embeddings, tags, scenes). It needs model downloads (ask above 2 GB).

Export path for the rest of the project (decided in Phase 4): FCP7 XML into DaVinci Resolve.

### Phase 4 run on the user's real footage (2026-10-09, M1 8 GB, `data/phase4-verify`, not an evaluation)
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
- Phase 7, needs the user: (1) look at the Actors page and say whether the groups are usable; correcting them there
  (merge, split, move) also produces the labels a purity figure for this footage needs; (2) say whether keeping
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
- Phase 6, needs the user: (1) say which languages are spoken in the footage; (2) read the transcript of
  "Timeline One.mov" in the app and say whether the words are right; (3) for a WER on own material, write the true
  words of one or two clips into `clip.txt` files (EVALUATION.md section 4).
- Phase 6 limitations: on noisy clips without clear speech (water, music, crowds) Whisper writes fluent text that was
  never said; it is marked uncertain in most but not all cases, and nothing is hidden. Results on such audio differ
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
- `data/phase4-verify/` (141 MB of proxies) is only the Phase 4 check run; delete the folder when the Resolve test is done.
- Phase 1 known limitations (from review, deferred): single worker assumed (D-016, no lease/lock file); SSE uses a sync polling generator (no async disconnect detection, `job_events` never pruned); `cancel`/`retry` are not atomic conditional updates; `resolve_in_roots` accepts relative paths (Phase 3 callers reject them before calling); 
- Phase 3 limitations: `media_roots` must be set by hand in `cinemind.toml` (no UI to add roots); the Library has no sort/filter/bulk actions yet (later phases add the data they sort by); no job cancel/retry buttons in the UI yet (API exists); proxy hardware encoders other than VideoToolbox/libx264 are untested here (no NVENC/QSV on this machine); HEVC/ProRes decoding speed on the 8 GB M1 not benchmarked (no numbers claimed).
- Phase 2 limitations: `e2e/` is linted but not type-checked by `T check`; the SSE hook is unit-tested with a fake EventSource and only the connected indicator uses it (no job UI yet, so no E2E for live progress); the Playwright port 8765 is fixed.
