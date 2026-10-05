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
- [ ] Phase 3: Ingest, metadata, proxies, thumbnails
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
Phase 2 complete (app shell, routing, project switcher, projects UI, toasts, SSE hook, Playwright smoke test). Next step: Phase 3 (ingest, ffprobe metadata, proxies, thumbnails; also add enqueue/list-jobs endpoints and the upload size limit).

## DEVELOPMENT PLACEHOLDERs
None.

## Open issues / notes
- E2E: `T e2e` (Playwright, real built app, throwaway `data/e2e`). Needs a one-time `pnpm exec playwright install chromium`; here only full Chrome for Testing downloaded (headless shell stalled), so `playwright.config.ts` uses `channel: "chromium"`.
- shadcn/ui is deferred until a screen needs a dialog/table (D-021); delete confirmation uses `window.confirm` for now. Wavesurfer, Recharts and dnd-kit arrive with their screens.
- Test footage folder still needed from Phase 3 (see pack Appendix B).
- Phase 1 known limitations (from review, deferred): single worker assumed (D-016, no lease/lock file); SSE uses a sync polling generator (no async disconnect detection, `job_events` never pruned); cached results are not checked against artifact files and are not scoped per project (revisit when Phase 3 stages write files); `cancel`/`retry` are not atomic conditional updates; `resolve_in_roots` accepts relative paths (callers in Phase 3 must pass absolute); no enqueue/list-jobs endpoint yet (arrives with Phase 3 `process`).
- Upload size limit (rule 7) is not implemented yet; the unused `max_upload_mb` setting was removed and returns with uploads in Phase 3.
- Phase 2 limitations: `e2e/` is linted but not type-checked by `T check`; the SSE hook is unit-tested with a fake EventSource and only the connected indicator uses it (no job UI yet, so no E2E for live progress); the Playwright port 8765 is fixed.
