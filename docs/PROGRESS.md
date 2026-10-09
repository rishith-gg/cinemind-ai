# Progress

_Last updated: 2026-10-09_

## Project context
- Deadline / demo date: TBD (not provided)
- DaVinci Resolve: **free edition, 21.1.0** (read from `/Applications/DaVinci Resolve.app` Info.plist on 2026-10-09). Free edition: plan on a manual import test, do not rely on external scripting.
- Footage: `/Volumes/externalssd/CineMind-Footage` (set as `CINEMIND_MEDIA_ROOTS` in the gitignored `.env`), 17 clips, 1.9 GB, phone footage: 11 HEVC + 6 H.264, mostly 4K, 24/25/30/59.94/60 fps, average and base frame rate differ slightly on 10 clips, 1 is flagged variable frame rate by the 0.5 % rule, one 1080p 120 fps, one clip without audio. Languages: TBD
- Machine: macOS (Darwin 25.5), Apple M1 8 cores, 8 GB RAM, Apple GPU (MPS), ~480 GB free on external SSD
- Recommended model tier: **lite** (see DECISIONS.md D-006)

## Phases
- [x] Phase 0: Environment, repo, docs, tooling
- [x] Phase 1: Backend core + DB + job system
- [x] Phase 2: Frontend shell
- [x] Phase 3: Ingest, metadata, proxies, thumbnails
- [ ] Phase 4: Shots, keyframes + first timeline export (Resolve test). **Code complete; waiting for the user's DaVinci Resolve import result** (the acceptance criterion that only the user can run)
- [ ] Phase 5: Quality + audio QC
- [ ] Phase 6: Transcription
- [ ] Phase 7: Faces and actors
- [ ] Phase 8: Embeddings, tags, scenes
- [ ] Phase 9: Hybrid search
- [ ] Phase 10: Ranking, selects, explainability
- [ ] Phase 11: Rough cut engine + timeline UI
- [ ] Phase 12: P1 differentiators
- [ ] Phase 13: Evaluation
- [ ] Phase 14: Polish, packaging, demo

## Current state
Phase 4 is implemented and verified by tests, but NOT closed: the roadmap requires the user to import an exported
timeline into DaVinci Resolve and report the result, and to fix what that finds before Phase 5.

What exists now: `shots` and `keyframes` stages in the ingest chain (PySceneDetect on the proxy; sharpest-frame
keyframes), shot strip on the clip page, Shots page, `timelines`/`timeline_items`, the chronological "all shots"
timeline, and export to FCP7 XML, EDL and OTIO from the Export page (see API.md, DECISIONS D-034 to D-042).

Next step: the user runs `docs/TESTING.md` "DaVinci Resolve import checklist" (timelines A and B) and reports. Then:
fix any import problem, record the result in TESTING.md, tick Phase 4, start Phase 5.

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
- E2E: `T e2e` (Playwright, real built app, throwaway `data/e2e`). Needs a one-time `pnpm exec playwright install chromium`; here only full Chrome for Testing downloaded (headless shell stalled), so `playwright.config.ts` uses `channel: "chromium"`.
- shadcn/ui is deferred until a screen needs a dialog/table (D-021); delete confirmation uses `window.confirm` for now. Wavesurfer, Recharts and dnd-kit arrive with their screens.
- **Waiting on the user: Resolve import test** (above). Nothing about Resolve compatibility is claimed until it is run.
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
