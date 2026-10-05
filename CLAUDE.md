# CineMind AI

AI-assisted pre-editing for filmmakers: raw footage → understanding → organization → search → ranking → AI-assisted rough cut → OTIO / FCP XML / EDL → DaVinci Resolve.
Local-first B.Tech student project. It is NOT an auto-editor: the human editor makes the creative decisions. Always call generated edits "AI-assisted rough cut".

## Non-negotiables
1. **Local-first**: all processing runs on the user's machine. No cloud, no paid APIs, no internet during processing. Internet is allowed only at setup (installing dependencies, downloading models via `cinemind models pull`). Optional LLM features are behind a provider interface (`none` | `ollama`) and OFF by default; the app must be fully functional with `none`.
2. **Non-destructive**: never modify, move, rename or delete source footage. All derived data lives under `data/` (gitignored).
3. **Honest AI**: no fake or hard-coded "AI" output. If something is temporarily mocked, mark it `DEVELOPMENT PLACEHOLDER` in code + `docs/PROGRESS.md` and replace it before the phase is marked done. Never invent evaluation numbers; every metric in docs must come from a script in `eval/` that was actually run. Distinguish clearly: existing model/library vs our pipeline vs our scoring logic vs our evaluation.
4. **Modular monolith**: one FastAPI app + one worker process. No microservices, no Docker, no Redis/Celery. Avoid over-engineering.
5. **Idempotent, cached, resumable stages**: each pipeline stage is cached by `(media content hash, stage, params hash, model name+version)`. Re-running skips finished work; a crash resumes where it stopped.
6. **Explainable**: every ranking/tag/cluster decision stores its inputs (scores, model, version, thresholds) so the UI can show "why".
7. **Security**: bind to 127.0.0.1 only; never `shell=True`; subprocess args as lists; validate/sanitize filenames; media paths must resolve inside user-approved media roots (resolve symlinks, reject `..`); upload size limits; no secrets in git.
8. **Hardware-aware**: never assume an NVIDIA GPU. Detect hardware, pick a model tier (lite/balanced/quality), and always provide a CPU path.
9. **Verify before pinning**: before choosing a library/model version or relying on an API from memory, check the current docs/package index. Don't trust training-data memory for versions, model names or CLI flags.
10. **Autonomy**: make reasonable engineering decisions yourself, record them in `docs/DECISIONS.md`, keep going. Ask the user only if a decision fundamentally changes the product, or needs something you cannot do (e.g. manual DaVinci Resolve import test, large model download > 2 GB, recording sample footage).

## Stack (change only with a written reason in DECISIONS.md)
- Backend: Python 3.11+ (3.12 ok), **uv**, FastAPI, Pydantic v2 + pydantic-settings, SQLAlchemy 2.0 + Alembic, SQLite (WAL mode, FTS5), pytest, ruff, pyright/mypy
- Video/audio: FFmpeg/ffprobe (subprocess, argument lists), OpenCV, PySceneDetect, PyAV only if it clearly helps
- Speech: faster-whisper (VAD + word timestamps), optional multilingual
- Vision-language embeddings: SigLIP (or OpenCLIP fallback) on keyframes
- Text embeddings: sentence-transformers (small English default, multilingual option)
- Faces: InsightFace (onnxruntime) with OpenCV YuNet+SFace as lightweight fallback; scikit-learn clustering
- Vector index: FAISS (flat inner product on normalized vectors) behind a `VectorIndex` interface (numpy fallback)
- Timeline: **OpenTimelineIO** is the internal model; exporters for FCP7 XML, EDL (CMX3600), OTIO, SRT/markers
- Frontend: React + Vite + TypeScript + Tailwind + shadcn/ui, TanStack Query, TanStack Router (or React Router), Zustand, wavesurfer.js, Recharts, dnd-kit; API client **generated from FastAPI's OpenAPI schema**
- Tests: pytest, Vitest + Testing Library, Playwright (E2E)

## Layout
```
cinemind/
  CLAUDE.md  README.md  pyproject.toml  justfile (or tasks via `uv run`)
  backend/src/cinemind/{api,core,db,jobs,pipeline,ai,search,rough_cut,export,utils}/
  backend/tests/
  frontend/src/{app,components,features,lib,api}/
  eval/            # datasets spec, scripts, results (reproducible)
  docs/            # SPEC, ROADMAP, PROGRESS, DECISIONS, ARCHITECTURE, DATABASE, API, AI_PIPELINE, TESTING, EVALUATION, USER_GUIDE
  data/            # gitignored: projects/<id>/{proxies,thumbnails,keyframes,audio,transcripts,analysis,index,exports}
  scripts/
```
Single-command run: `uv run cinemind serve` (serves API + built frontend). Dev: backend with reload + `pnpm dev`.
`uv run cinemind doctor` checks ffmpeg/Python/Node/RAM/GPU and prints the recommended model tier.

## Commands (keep this section accurate; update in Phase 0 and whenever they change)
Run from the repo root. `just` is not used; `scripts/tasks.py` is the cross-platform equivalent (`T` = `uv run python scripts/tasks.py`).
- Setup: `uv sync` then `cd frontend && pnpm install`
- Worker alone (normally started by `serve`; `serve --no-worker` to skip): `uv run cinemind worker`
- Environment check: `uv run cinemind doctor` (add `--json` for machine output)
- Run (single command, API + built UI): `T build-ui` once, then `uv run cinemind serve` -> http://127.0.0.1:8000
- Dev: `T dev-api` (backend, auto-reload) and `T dev-ui` (Vite on :5173, proxies /api to :8000)
- Regenerate the TS API client after any API change: `T gen-api` (writes `frontend/openapi.json` + `frontend/src/api/`, commit both)
- E2E smoke test (Playwright, real app; first run: `cd frontend && pnpm exec playwright install chromium`): `T e2e`
- Full check (ruff format/lint, pyright, pytest, tsc, eslint, vitest): `T check`
- Format Python: `T format`
- Backend tests only: `uv run pytest -q`; frontend tests only: `cd frontend && pnpm test`

## Conventions
- Python: type hints everywhere, Pydantic schemas at API boundaries, services are plain functions/classes without FastAPI imports, logging via `logging` (no prints), config only through `core/config.py`, no absolute paths in code.
- TypeScript strict mode, small reusable components, no `any`, data fetching only through the generated client + TanStack Query.
- Files < ~400 lines; no duplicated logic; no unused dependencies.
- Errors: typed domain exceptions → API errors with a plain-language `message` and a machine `code`. Never fail silently; the UI always shows what happened and what the user can do.
- Timecode: store frame rates as rationals (e.g. 30000/1001), times as seconds (float) AND frames where needed; never use float fps for export math. Handle VFR sources.
- Commits: Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`), one logical change each. Never use destructive git commands (force push, reset --hard, clean -fd) without warning the user first.

## Workflow for every phase
1. Read `docs/PROGRESS.md`, then the phase in `docs/ROADMAP.md`, then only the relevant parts of `docs/SPEC.md`.
2. Inspect the current code. Plan briefly (use plan mode for big phases).
3. Implement only this phase, in small verified steps. Don't break earlier features.
4. Write tests with the code (not afterwards). Run lint, type-check, tests. Run the app and check the feature really works (use the Playwright MCP for UI).
5. Update docs touched by the change, update `docs/PROGRESS.md`, commit.
6. Finish with a **Phase Report**: summary · files changed · tests run + results · exact commands for the user to verify · known limitations · next phase.

## Definition of done (phase)
Acceptance criteria in ROADMAP met · tests pass · lint/type-check clean · works on CPU-only · errors handled with friendly messages · docs updated · committed · no unlabeled placeholders.

## Where things are
Product/feature/tech detail → `docs/SPEC.md`. Phase list + acceptance criteria → `docs/ROADMAP.md`. Current state / next step / open issues → `docs/PROGRESS.md`. Past decisions → `docs/DECISIONS.md`.
