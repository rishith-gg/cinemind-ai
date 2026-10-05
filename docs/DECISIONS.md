# Decisions

| ID | Date | Decision | Why |
|---|---|---|---|
| D-001 | 2026-10-05 | Branch renamed `master` -> `main`. | CLAUDE.md/pack name `main` as the main branch. |
| D-002 | 2026-10-05 | `scripts/tasks.py` (run with `uv run python`) instead of a `justfile`. | `just` is not installed, and a Python script works on Windows/macOS/Linux. The pack allows either. |
| D-003 | 2026-10-05 | Python: `requires-python >=3.11`, running on the system 3.13.1; no `.python-version` pin. | Phase 0 has no ML wheels. Revisit and pin 3.12 in Phase 6-8 if torch/onnxruntime wheels need it. |
| D-004 | 2026-10-05 | Versions verified against PyPI/npm today (FastAPI 0.142.2, Pydantic 2.13.5, pydantic-settings 2.15.0, Typer 0.27.2, uvicorn 0.54.0, psutil 7.2.2, React 19.3.0, Vite 8.3.2, Tailwind 4.3.3, TanStack Query 5.104.1, Vitest 5.0.3, ESLint 10.12.0, @hey-api/openapi-ts 0.99.0). Backend uses compatible-range pins with `uv.lock`; frontend uses `pnpm-lock.yaml`. | CLAUDE.md rule 9. SQLAlchemy 2.1.3, Alembic 1.20.0, OpenTimelineIO 0.18.1, faster-whisper 1.2.1, scenedetect 0.7.1, open-clip-torch 3.3.0 exist on PyPI; they are pinned when first used. SQLAlchemy is now 2.1 (pack said 2.0): check migration notes in Phase 1. |
| D-005 | 2026-10-05 | TypeScript pinned to **6.0.3**, not the latest 7.0.2. | TS 7 is the native rewrite and has no JS compiler API; `@hey-api/openapi-ts` crashed on it. Revisit when the generator supports TS 7. |
| D-006 | 2026-10-05 | Model tier for this machine: **lite**. | M1 with 8 GB RAM, no CUDA. SPEC §6: lite = CPU only, <=8 GB RAM. Apple GPU (MPS) helps PyTorch embeddings, but faster-whisper (CTranslate2) has no MPS backend, so transcription runs on CPU int8. Larger models risk running out of memory next to ffmpeg and the browser. |
| D-007 | 2026-10-05 | API client generated with `@hey-api/openapi-ts` using the fetch client and TanStack Query plugin; generated code in `frontend/src/api/` is committed and lint-ignored. | Matches "client generated from OpenAPI". Committing it keeps the frontend buildable without Python. |
| D-008 | 2026-10-05 | Dev dependency `httpx2` instead of `httpx`. | Starlette's TestClient now warns that httpx is deprecated in favour of httpx2. |
| D-009 | 2026-10-05 | `rich` added as an explicit dependency. | The doctor table uses it directly; don't depend on Typer's transitive install. |
| D-010 | 2026-10-05 | `.claude/settings.json` hook: removed the shell-only `\|\| true`. Everything else verbatim. | Keeps the hook cross-platform; hook failures are non-blocking anyway. |
| D-011 | 2026-10-05 | `GET /api/system/health` runs the doctor on every call (no cache). | Cheap enough (~100s of ms); caching can come with the first-run wizard. |
| D-012 | 2026-10-05 | pnpm enabled through `corepack enable pnpm` (user approved). pnpm 12.9.1. | Ships with Node, no Homebrew package needed. |
| D-013 | 2026-10-05 | `uv` link-mode set to `copy`. | Project is on an external SSD; hardlinks from the uv cache across filesystems failed with a warning. |
| D-014 | 2026-10-05 | SQLAlchemy **2.1.3** (not the 2.0 in the pack) and Alembic 1.20.0, pinned `>=2.1.3,<2.2`. | Verified on PyPI (D-004). 2.0-style `Mapped[]`/`select()` code ran unchanged. |
| D-015 | 2026-10-05 | Added `stage_results` (cache) and `job_events` (SSE log) tables beyond the SPEC table list. | Rule 5 needs a cache keyed by `(media hash, stage, params hash, model)`; resumable SSE needs durable, ordered events. Both live in SQLite, so no Redis. |
| D-016 | 2026-10-05 | Worker assumes a single instance: on startup every `running` job is re-queued (no heartbeats/leases). `serve` spawns the worker and passes `--parent-pid` so it exits if `serve` dies. | One worker process is the architecture (rule 4). Leases would be over-engineering. |
| D-017 | 2026-10-05 | A stage interrupted by a crash restarts from its beginning; only whole finished stages are cached. | Per-item checkpoints belong inside long stages (transcribe, faces) and are added there if needed. |
| D-018 | 2026-10-05 | Test-only chains live in `backend/tests/dummy_chain.py` and load through `extra_stage_modules` setting. | The Phase 1 acceptance chain must not ship as fake "AI" in the package. |
| D-019 | 2026-10-05 | Alembic migrations are excluded from pyright (generated code). | Strict mode flags Alembic's generated column calls; the models themselves stay strict-checked. |

