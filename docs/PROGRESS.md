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
- [ ] Phase 2: Frontend shell
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
Phase 1 complete (DB, migrations, job queue, worker, SSE, projects API, path safety). Next step: Phase 2 (frontend shell).

## DEVELOPMENT PLACEHOLDERs
None.

## Open issues / notes
- No browser-driven (Playwright) check yet; frontend-to-backend proof is a Vitest test of the generated client plus real HTTP through the Vite proxy. Add the Playwright MCP before Phase 2's E2E test.
- shadcn/ui, TanStack Router and Zustand are deferred to Phase 2 (nothing in Phase 0 needs them).
- Test footage folder still needed from Phase 3 (see pack Appendix B).
- Phase 1 known limitations (from review, deferred): single worker assumed (D-016, no lease/lock file); SSE uses a sync polling generator (no async disconnect detection, `job_events` never pruned); cached results are not checked against artifact files and are not scoped per project (revisit when Phase 3 stages write files); `cancel`/`retry` are not atomic conditional updates; `resolve_in_roots` accepts relative paths (callers in Phase 3 must pass absolute); no enqueue/list-jobs endpoint yet (arrives with Phase 3 `process`).
- Upload size limit (rule 7) is not implemented yet; the unused `max_upload_mb` setting was removed and returns with uploads in Phase 3.
