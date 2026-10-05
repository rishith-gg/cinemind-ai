# Progress

_Last updated: 2026-10-05_

## Project context
- Deadline / demo date: TBD (not provided)
- DaVinci Resolve: installed on this Mac (`DaVinci Resolve.app`); free vs Studio and version TBD, ask at Phase 4
- Footage / languages: TBD
- Machine: macOS (Darwin 25.5), Apple M1 8 cores, 8 GB RAM, Apple GPU (MPS), ~480 GB free on external SSD
- Recommended model tier: **lite** (see DECISIONS.md D-006)

## Phases
- [x] Phase 0: Environment, repo, docs, tooling
- [x] Phase 1: Backend core + DB + job system
- [x] Phase 2: Frontend shell
- [x] Phase 3: Ingest, metadata, proxies, thumbnails
- [ ] Phase 4: Shots, keyframes + first timeline export (Resolve test)
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
Phase 3 complete (ingest chain, folder browser + upload, library, clip page with proxy player; see API.md). Next step: Phase 4 (shots, keyframes, first timeline export; ask the user about the DaVinci Resolve version and for real sample footage).

## DEVELOPMENT PLACEHOLDERs
None.

## Open issues / notes
- E2E: `T e2e` (Playwright, real built app, throwaway `data/e2e`). Needs a one-time `pnpm exec playwright install chromium`; here only full Chrome for Testing downloaded (headless shell stalled), so `playwright.config.ts` uses `channel: "chromium"`.
- shadcn/ui is deferred until a screen needs a dialog/table (D-021); delete confirmation uses `window.confirm` for now. Wavesurfer, Recharts and dnd-kit arrive with their screens.
- Real test footage still needed (pack Appendix B): Phase 3 was verified with synthetic ffmpeg clips (ProRes .mov, H.264 mp4/mkv, 29.97 fps, VFR, no-audio, audio-only, corrupt). Before Phase 4, please provide a folder of real clips (include one HEVC/phone clip) and add it to `media_roots` in `cinemind.toml`.
- Phase 1 known limitations (from review, deferred): single worker assumed (D-016, no lease/lock file); SSE uses a sync polling generator (no async disconnect detection, `job_events` never pruned); `cancel`/`retry` are not atomic conditional updates; `resolve_in_roots` accepts relative paths (Phase 3 callers reject them before calling); 
- Phase 3 limitations: `media_roots` must be set by hand in `cinemind.toml` (no UI to add roots); the Library has no sort/filter/bulk actions yet (later phases add the data they sort by); no job cancel/retry buttons in the UI yet (API exists); proxy hardware encoders other than VideoToolbox/libx264 are untested here (no NVENC/QSV on this machine); HEVC/ProRes decoding speed on the 8 GB M1 not benchmarked (no numbers claimed).
- Phase 2 limitations: `e2e/` is linted but not type-checked by `T check`; the SSE hook is unit-tested with a fake EventSource and only the connected indicator uses it (no job UI yet, so no E2E for live progress); the Playwright port 8765 is fixed.
