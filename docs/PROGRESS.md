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
- [ ] Phase 1: Backend core + DB + job system
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
Phase 0 complete. Next step: Phase 1 (SQLAlchemy models + Alembic, worker, job queue, SSE).

## DEVELOPMENT PLACEHOLDERs
None.

## Open issues / notes
- No browser-driven (Playwright) check yet; frontend-to-backend proof is a Vitest test of the generated client plus real HTTP through the Vite proxy. Add the Playwright MCP before Phase 2's E2E test.
- shadcn/ui, TanStack Router and Zustand are deferred to Phase 2 (nothing in Phase 0 needs them).
- Test footage folder still needed from Phase 3 (see pack Appendix B).
