# CineMind AI — Roadmap

Principle: **walking skeleton first, depth later.** A thin end-to-end path (import → shots → simple rough cut → Resolve import) exists by Phase 4, so the riskiest integrations are proven early. Each phase is a vertical slice with a visible UI result.

Every phase ends with the Phase Report (see CLAUDE.md). Mark phases in `docs/PROGRESS.md`.

## Phase 0 — Environment, repo, docs, tooling
- Inspect OS, Python, uv, Node, pnpm, Git, FFmpeg/ffprobe, CPU, RAM, GPU. Report what's missing and how to install it on this OS (don't silently install system packages).
- Create repo layout, `pyproject.toml`, backend/frontend skeletons, `justfile`/scripts, ruff/pyright/pytest/vitest configs, `.gitignore` (data/, models/, .env), `.env.example`, `cinemind.toml` defaults.
- Implement `cinemind doctor` (real checks + tier recommendation).
- Write `docs/` skeleton from SPEC, `PROGRESS.md`, `DECISIONS.md`; fill in the Commands section of CLAUDE.md.
- Create `.claude/` helpers from the pack (commands, subagents, settings).
- Backend health endpoint + frontend page calling it through the generated client; CI-less local `just check` (lint+types+tests).
**Accept:** `doctor` runs; backend and frontend start; the frontend shows backend health; `just check` passes; first commit made.

## Phase 1 — Backend core + DB + job system
- SQLAlchemy models + Alembic (projects, media_assets, jobs, job_stages), SQLite WAL.
- Worker process, job queue, stage runner with caching/provenance, cancel/retry/resume, SSE events.
- Projects CRUD API + tests; config + path-safety utilities (media roots, sanitization) + tests.
**Accept:** a dummy no-op stage chain (test-only) runs in the worker, survives a kill/restart, and streams progress over SSE; path-traversal tests pass.

## Phase 2 — Frontend shell
- App layout, dark theme, navigation, routing, project switcher, TanStack Query + generated API client, toast/error system, empty/loading states, SSE hook.
**Accept:** create/list/open projects in the UI; E2E smoke test (Playwright) passes.

## Phase 3 — Ingest, metadata, proxies, thumbnails
- Folder browser (restricted) + upload; ffprobe metadata; content hash; duplicate/missing detection; proxy + thumbnail strip + waveform; Range streaming; library grid; clip detail page with working player.
**Accept:** import a folder containing mixed formats (include one that browsers can't play natively); all play via proxy; metadata correct; errors for a corrupt file are friendly.

## Phase 4 — Shots, keyframes + FIRST timeline export (Resolve early test)
- PySceneDetect stage; shot table; shot strip UI; keyframes.
- Minimal timeline model on OTIO; simple chronological "all shots" timeline; export FCP7 XML + EDL + OTIO; round-trip tests; manual Resolve import checklist.
**Accept:** shots match synthetic ground truth; exported timeline passes round-trip tests; **user imports it into DaVinci Resolve and reports the result** — fix issues before continuing (this decides the export path for the rest of the project).

## Phase 5 — Quality + audio QC
- Metrics, configurable score, flags, calibration script in `eval/`, UI (score badges, QC overlays, filters, low-quality list).
**Accept:** synthetic blur/exposure fixtures score as expected; thresholds calibrated on labelled clips with real numbers recorded.

## Phase 6 — Transcription
- faster-whisper stage with VAD, words, language detect; FTS5 index; transcript panel synced to player; click-to-seek; no-speech/no-audio handling; WER script.
**Accept:** real clip transcribed with word timings; keyword search jumps to the right moment; WER measured on a labelled sample.

## Phase 7 — Faces and actors
- Detection, quality filter, embeddings, tracking, two-pass clustering with cannot-link; Actors page (rename/merge/split/ignore); corrections persisted; clustering eval script.
**Accept:** multi-person clips produce sensible clusters; user corrections survive re-processing; purity/ARI measured.

## Phase 8 — Embeddings, tags, scenes
- SigLIP keyframe embeddings, text embeddings, FAISS index (`VectorIndex` interface), scene grouping, calibrated zero-shot tags with confidence + approve/reject.
**Accept:** vector index rebuilds from the DB; scene grouping editable; tags below the evaluated threshold are hidden.

## Phase 9 — Hybrid search
- FTS5 + dense text + visual search, RRF fusion, filters, image-query / "more like this", result cards with highlights and jump-to-time; search eval script (P@K, nDCG, MRR, ablations).
**Accept:** query "person walking" returns visually relevant shots; ablation table produced from real runs.

## Phase 10 — Ranking, selects, explainability
- Score breakdown, MMR dedupe, selects/rejects/stars, config weights, what-if sliders, feedback events and optional learned re-weighting (P1-D).
**Accept:** UI shows per-signal breakdown; changing weights changes the order deterministically; rejects are excluded.

## Phase 11 — Rough cut engine + timeline UI
- Brief → candidates → filter → select → trim → order → fit duration → OTIO; explanations per clip; timeline editor (reorder/trim/remove/swap), proxy playback; export panel (FCP7 XML, EDL, OTIO, markers, SRT); banner text.
**Accept:** from a 1-sentence brief, produce a timeline in < 1 min on the dev machine; exports pass round-trip; user confirms Resolve import again.

## Phase 12 — P1 differentiators (in order; each is its own mini-phase with eval)
A. Script-to-footage alignment → B. Take detection/best take → C. Speech-aware trimming → D/E remaining items. Stop after at least three are solid and evaluated.

## Phase 13 — Evaluation
- Finish the dataset, labelling helpers, all `eval/` scripts, full results tables/plots, user-study protocol + analysis script, `ACADEMIC_NOTES.md`.
**Accept:** `docs/EVALUATION.md` contains only numbers produced by committed scripts, with hardware + model versions.

## Phase 14 — Polish, packaging, demo
- Performance pass (profile; batching; sampling), UI polish, accessibility basics, first-run wizard, `uv run cinemind serve` single-command launch, README + USER_GUIDE, demo project + script (see below), seed sample project.
**Final demo:** create project → import footage folder → analyse with live progress → shots/scenes → quality + QC flags → actor clusters (rename) → transcript → search "person walking in forest" (text) and by reference image → ranked results with "why" → generate rough cut from a brief → edit timeline → export XML/EDL → open in DaVinci Resolve → continue editing.
