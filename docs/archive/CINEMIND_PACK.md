# CineMind AI — Claude Code Master Pack (v2)

This single file contains everything Claude Code needs to build CineMind AI.
It is split into small files on purpose: Claude Code re-reads `CLAUDE.md` every session, so it must stay short. The long specification lives in `docs/` and is read only when needed.

## How to use (5 minutes)

1. Create an empty folder `cinemind/`, run `git init`, and put this file inside it as `CINEMIND_PACK.md`.
2. Install Claude Code, open a terminal in the folder, run `claude`.
3. Press `Shift+Tab` until **Plan Mode** is on, then paste the **Kickoff Prompt** (last section of this file). Review the plan, approve it, and let it run Phase 0.
4. After each phase: commit, run `/clear`, then type `/next-phase` (created in Phase 0). Claude reads `docs/PROGRESS.md` and continues. Never ask "what next?"
5. From Phase 1 onward, add the Playwright MCP so Claude can look at the UI itself:
   `claude mcp add playwright -- npx @playwright/mcp@latest`

Before you start, edit the **Project Context** block in the Kickoff Prompt (deadline, DaVinci version, footage languages).

---

## What changed from the old prompt (and why)

| Old prompt | This pack | Reason |
|---|---|---|
| One giant prompt | `CLAUDE.md` (short, always loaded) + `SPEC.md` + `ROADMAP.md` + `PROGRESS.md` | Claude Code keeps `CLAUDE.md` in context every session; a huge prompt gets forgotten after `/clear` or `/compact` |
| venv + pip | **uv** (Python) + **pnpm** | Faster, reproducible lockfiles, easy for Claude to run |
| Browser can't play camera formats | **Proxy generation** (H.264, 720p) at import | HEVC/ProRes/MKV/camera files won't play in a browser, and this breaks the whole UI otherwise |
| Copy footage into `data/` | **Reference in place** (copy optional) | Raw footage is huge; students have limited disk |
| Background processing, unspecified | **SQLite-backed job queue + worker process + SSE progress**, idempotent cached stages | No Redis/Celery, resumable, never re-runs finished work |
| Transcript-only semantic search | **Hybrid search**: SQLite FTS5 (BM25) + text embeddings + **visual embeddings (SigLIP/CLIP)** fused with RRF | Much better retrieval; visual search is the headline feature |
| "FCP XML or EDL" | **OpenTimelineIO (OTIO)** as internal timeline model, exports FCP7 XML, EDL, OTIO, plus markers + SRT | One model, many formats; Resolve import is validated early (Phase 4) instead of last |
| Scene = shot (blurry) | **Shot → Scene → Take** hierarchy, defined clearly | Honest and useful to editors |
| Generic features | Unique features: **script-to-footage alignment, best-take selection, speech-aware trimming, explainable ranking with sliders, search by reference image, selects/reject feedback** | These are real editor pain points and are all buildable locally |
| Evaluation at the end | **`eval/` harness built alongside each module** | Metrics are real and reproducible; no fabricated numbers |

---

## FILE 1 — `CLAUDE.md`

````markdown
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
_Filled in during Phase 0._

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
````

---

## FILE 2 — `docs/SPEC.md`

````markdown
# CineMind AI — Specification

## 1. Vision
CineMind AI: an intelligent, local-first pre-editing assistant for filmmakers and video editors. It analyses raw footage and turns an unorganized card dump into a searchable, organized, ranked library, then produces an **AI-assisted rough cut** that exports to DaVinci Resolve (and other NLEs) for the human editor to finish.

Primary user: an independent filmmaker / student editor with a normal laptop and hours of raw footage.
Core promise: "Find the right shot in seconds, get a first assembly in minutes, keep full creative control."

### Terminology (use consistently in code, UI and docs)
- **Media asset**: one source file.
- **Shot**: continuous run of frames between two camera cuts. Detected automatically.
- **Scene**: group of consecutive shots that belong together (same location/time, similar visual+audio). Inferred heuristically and user-editable. Do NOT confuse with shot.
- **Take**: one attempt at the same action/dialogue. A **take group** = several assets/segments that are repeats of the same material.
- **Segment**: a searchable unit (a shot, or a transcript segment with its time range).
- **Select / Reject**: the editor's flags on clips/segments. They feed ranking.
- **Rough cut**: ordered timeline of trimmed segments, always labelled "AI-assisted rough cut. Human review required."

## 2. Feature tiers
**P0 — V1 (must work end-to-end):**
1. Projects. 2. Import (reference in place / copy / upload) with ffprobe metadata, content hash, **proxy** + thumbnails + waveform. 3. Shot detection + scene grouping. 4. Technical quality analysis (video + audio). 5. Transcription (timestamps, words, language). 6. Face detection → actor clustering → rename/merge/split. 7. Visual + text embeddings. 8. Hybrid semantic search with explainable ranking. 9. Selects/rejects + tags. 10. Rough cut generation from a text brief. 11. Timeline editor (reorder/trim/remove) + preview. 12. Export: FCP7 XML, EDL, OTIO, markers, SRT. 13. Dashboard, library, clip detail, processing status.

**P1 — Differentiators (build at least 3, in this order):**
- **A. Script-to-footage alignment**: user uploads a screenplay (Fountain or plain text); dialogue lines are fuzzy/semantically matched to transcript segments; output is a **script-ordered assembly** with the best take per line.
- **B. Take detection and best-take suggestion**: group repeated takes via transcript similarity + visual embedding similarity + temporal adjacency; suggest the best take using transparent signals (focus, exposure, audio clarity, completeness of the line, no flubs/ends cleanly); show the reasons.
- **C. Speech-aware trimming**: in/out points snap to sentence boundaries and pauses (VAD + word timestamps), trim leading/trailing dead air, optional "tighten" mode removing long silences; never cut inside a word.
- **D. Explainable ranking with what-if sliders**: UI shows per-signal score breakdown and lets the editor change weights live; learned re-weighting from the editor's select/reject feedback (simple logistic regression; show before/after).
- **E. Search by reference image / "more like this"**: drop a frame or pick a clip; retrieve visually similar shots (mood-board matching).

**P2 — Stretch (only if all P0 + 3 P1 are done and evaluated):**
camera-motion classification (static/pan/tilt/zoom/handheld), shot-type classification (wide/medium/close-up) from CLIP zero-shot + face-size heuristic, speaker diarization linked to actors (who is speaking), multilingual transcripts + translation for search (e.g. Tamil/Hindi/English), local VLM captions (Ollama) for richer text search, HTML "Dailies Report" export, Tauri desktop packaging, Resolve scripting (needs Studio), watch-folder auto import.

**Out of scope (document as future work only):** generative video, auto color grading, music/VFX, deepfakes/voice cloning, cloud/multi-user, mobile, full autonomous filmmaking, emotion recognition as a core feature.

## 3. Architecture
```
Browser (React)  ──HTTP/SSE──▶  FastAPI (127.0.0.1)
                                   │  reads/writes
                                   ▼
                               SQLite (WAL, FTS5)  ◀── Worker process (job runner)
                                   │                       │ runs pipeline stages
                                   ▼                       ▼
                            data/ filesystem      FFmpeg · OpenCV · PySceneDetect · faster-whisper ·
                            FAISS index files     InsightFace · SigLIP · sentence-transformers
```
- API process stays responsive; heavy work runs in a separate worker process. Jobs are rows in SQLite (`jobs`, `job_stages`); the worker polls, locks, runs stages, writes progress. API streams progress to the UI via **Server-Sent Events**. Support cancel, retry, resume.
- Heavy models are loaded lazily, one at a time (memory lock), and unloaded when idle. Frame sampling and batching keep CPU-only machines usable.
- Serve proxies/thumbnails with **HTTP Range support** so seeking works; verify it.

## 4. Ingest
- Import modes: **reference** (default; store absolute path, no copy), **copy**, **upload** (small files). Browser cannot give absolute paths, so provide an in-app **server-side folder browser** limited to user-configured media roots, plus drag-and-drop upload.
- Validate with ffprobe (not file extension). Extract: filename, container, duration, resolution, rational FPS, VFR flag, video/audio codec, bitrate, audio channels/sample rate, color info, start timecode (if present), file size, content hash (fast partial hash such as xxhash of head+tail+size).
- Detect duplicates by hash; detect missing/moved files and offer "relink".
- Generate a **proxy** (H.264, ≤720p, AAC, constant frame rate, `+faststart`) using a hardware encoder if available (NVENC / VideoToolbox / QSV) else libx264. Generate thumbnail strip, waveform peaks (for wavesurfer), and keyframes.
- All analysis runs on the proxy or on frames/audio derived with ffmpeg; export always references the ORIGINAL file with source timecode.

## 5. Pipeline stages
Each stage: idempotent, cached by `(media_hash, stage, params_hash, model_version)`, reports progress, has a friendly failure message, stores provenance (model, version, params, timestamp).

| # | Stage | Method | Output |
|---|---|---|---|
| 1 | validate | ffprobe checks | metadata, status |
| 2 | proxy+thumbs | ffmpeg | proxy, thumbs, waveform |
| 3 | shots | PySceneDetect (Adaptive/Content detector; thresholds in config); optional TransNetV2 later | shots (start/end frame+sec), thumbnail |
| 4 | scenes | group adjacent shots by visual-embedding + color + audio similarity, merge threshold in config | scenes (editable) |
| 5 | keyframes | 1–3 frames per shot (sharpest near start/mid/end) | keyframe images |
| 6 | quality | per shot/clip; see §8 | metrics + score |
| 7 | audio QC | ffmpeg `ebur128` loudness, `silencedetect`, clipping, `blackdetect`/`freezedetect` flags | audio metrics, QC flags |
| 8 | transcribe | faster-whisper, `vad_filter`, `word_timestamps`, language auto-detect | segments + words + confidence |
| 9 | faces | sample 1–2 fps; detect; filter by size/blur/pose; embed; track within shot | faces, tracks |
| 10 | actors | cluster (see §9) | actor clusters |
| 11 | embed | SigLIP on keyframes; text embedding of transcript segments (+ tags) | vectors in FAISS + metadata rows |
| 12 | tags | CLIP zero-shot with calibrated thresholds (indoor/outdoor, day/night, shot type, a small fixed vocabulary) + face count + dialogue flag. **Only keep tags above an evaluated confidence threshold; show confidence; user can approve/reject.** | tags |
| 13 | index | FTS5 + FAISS update | searchable |
| 14 | done | summary row | status |

Stage 12 must not produce tags just to look rich; remove any tag type whose evaluated precision is poor.

## 6. Models and hardware tiers
`cinemind doctor` detects OS, CPU cores, RAM, GPU (CUDA / Apple MPS / none) and VRAM, then selects a tier. Always verify current model names/availability before pinning.

| Tier | Typical hardware | Whisper | Visual embed | Text embed | Faces | Frame sampling |
|---|---|---|---|---|---|---|
| lite | CPU only, ≤8 GB RAM | `base`/`small` int8 | OpenCLIP ViT-B/32 | MiniLM-class | YuNet+SFace | 0.5 fps |
| balanced | CPU 16 GB or GPU 4–6 GB | `small`/`medium` int8 (or fp16 on GPU) | SigLIP base | bge-small-class | InsightFace small | 1 fps |
| quality | GPU ≥ 8 GB | large-v3(-turbo) fp16 | SigLIP larger variant | bge-base/multilingual | InsightFace large | 2 fps |

Models are user-configurable in `cinemind.toml`; `cinemind models pull` downloads them (ask before > 2 GB). Record model name + version with every embedding/transcript so results stay reproducible. Use onnxruntime/PyTorch device auto-selection with CPU fallback.

## 7. Data model (create only what the current phase needs)
projects · media_assets · jobs · job_stages · shots · scenes · keyframes · quality_metrics · audio_metrics · qc_flags · transcript_segments (+ FTS5 table) · transcript_words · faces · face_tracks · actors · tags · vector_refs (kind, ref_id, model, dim, index_offset) · selects (user flag on asset/shot/segment) · take_groups · take_group_members · script_docs · script_lines · script_alignments · timelines · timeline_items · feedback_events.
Rules: integer PKs, foreign keys ON, `created_at/updated_at`, indexes on every FK and on search columns, provenance columns on derived rows, Alembic migrations from day one, SQLite WAL.

## 8. Technical quality
Never claim to measure "cinematic quality". Compute transparent technical metrics:
- **Sharpness**: variance of Laplacian on downscaled grayscale (normalize by resolution; compute on face region too if a face exists)
- **Exposure**: mean luma, % clipped highlights, % crushed shadows → under/overexposure scores
- **Contrast**: luma std-dev / percentile spread
- **Noise** (optional), **Shake/motion** (optical flow, P2), **Audio**: integrated loudness (LUFS), clipping %, silence %, speech present
- **Technical Quality Score** = weighted sum of normalized [0–1] sub-scores; weights in config, formula documented in `AI_PIPELINE.md`. Calibrate thresholds against a labelled set in `eval/` instead of guessing; report the result.
- Flags (not scores): out-of-focus, overexposed, underexposed, black frames, frozen frames, long silence, clipped audio, low audio level.

## 9. Faces and actors
detect → quality-filter → embed → track within shot → cluster. Cluster in two passes: per-media track clusters, then project-level agglomerative clustering on cosine distance (threshold in config; HDBSCAN as alternative; evaluate both). Use **cannot-link** constraints (two faces in the same frame are different people). Auto-name "Actor 001…". UI: rename, merge, split, mark "not a face/ignore", "unknown". Corrections are stored (feedback_events) and re-applied on re-cluster. Handle no face, many faces, partial/profile faces, low light. Never claim perfect recognition. Never match to real-world identities; clusters are local to the project.

## 10. Search and ranking
- **Keyword**: SQLite FTS5 (BM25) over transcript, tags, filenames, actor names.
- **Semantic text**: sentence embeddings of transcript segments.
- **Semantic visual**: SigLIP text→image similarity against keyframe embeddings; also image→image ("more like this", reference image).
- **Fusion**: Reciprocal Rank Fusion across the three result lists (documented, configurable `k`), optional filters (actor, scene, quality ≥ x, has dialogue, selects only).
- **Ranking score** (all signals normalized 0–1, weights in config, per-signal breakdown returned by the API as `score_breakdown`):
  `final = w_sem·semantic + w_txt·transcript + w_q·quality + w_act·actor + w_scn·scene + w_sel·select_bonus − w_dup·duplicate_penalty`
  Diversity via MMR to avoid near-duplicates. Rejected items are excluded unless requested.
- Result cards show thumbnail, file, timestamp range, relevance, matched transcript text (highlighted), and "why this result" (top contributing signals). Clicking jumps the player to the exact timestamp.
- Rankings are heuristic — never describe them as scientifically validated; evaluate them (P@K, nDCG@K, MRR) and ablate (BM25 only, dense only, hybrid, with/without quality).

## 11. Rough cut engine
Input: a text **brief** (e.g. "2-minute sequence about the grandfather walking home at night"), optional target duration, optional actors/scenes filter, ordering mode.
Steps: parse brief (rules + optional local LLM, never required) → retrieve candidates via search → filter technically poor / rejected → pick by score with MMR → trim in/out (speech-aware when dialogue) → order (chronological by source time | by scene | by script order | by score) → fit target duration → build OTIO timeline with transitions = cuts only → report **why each clip was chosen**.
Timeline UI: reorder (dnd-kit), trim handles, remove, swap with an alternative suggestion, play whole timeline using proxies (sequential playback with pre-seek), banner "AI-assisted rough cut. Human review required."
Script mode (P1-A) and take selection (P1-B) plug into the same engine as ordering/selection strategies.

## 12. Export (research and verify before coding)
- Internal model = **OpenTimelineIO**. Verify which adapters are in core vs separate plugin packages in the installed version.
- Export formats: **FCP7 XML (xmeml)** (primary Resolve path), **CMX3600 EDL** (cuts only, simplest), **OTIO**, optionally FCPXML; **markers** (scene/shot boundaries, transcript highlights) and **SRT/VTT** subtitles.
- Each item: source file (original, relinkable path), reel/name, source in/out with source timecode offset, record position, duration, correct rational frame rate (incl. 29.97/23.976 and drop-frame), audio+video tracks.
- Generate a test timeline from sample footage in Phase 4 and have the user import it into DaVinci Resolve right away (checklist in `docs/TESTING.md`). Claude cannot run Resolve: write the manual import checklist, ask the user to run it, and record the result. Do not claim native Resolve integration.
- Round-trip test: export → re-parse with OTIO → durations/in/out equal the source timeline.

## 13. API (keep minimal; OpenAPI is the contract; generate the TS client)
Projects: `POST/GET /api/projects`, `GET/PATCH/DELETE /api/projects/{id}`
Import: `GET /api/fs/browse` (restricted), `POST /api/projects/{id}/media` (register or upload), `GET /api/media/{id}`, `GET /api/media/{id}/stream` (proxy, Range)
Processing: `POST /api/projects/{id}/process`, `POST /api/media/{id}/process`, `GET /api/jobs/{id}`, `GET /api/jobs/events` (SSE), `POST /api/jobs/{id}/cancel|retry`
Library: `GET /api/projects/{id}/media|shots|scenes|actors|transcripts|tags`, `PATCH /api/actors/{id}` (rename/merge/split), `PUT /api/selects`
Search: `POST /api/projects/{id}/search` (text or image, filters, weights override)
Rough cut: `POST /api/projects/{id}/rough-cut`, `GET/PATCH /api/timelines/{id}`, `POST /api/timelines/{id}/export?format=`
Script (P1-A): `POST /api/projects/{id}/script`, `GET .../alignment`
System: `GET /api/system/health` (ffmpeg, models, hardware tier), `GET /api/system/config`

## 14. UI
Dark post-production look, high information density, minimal animation, keyboard-first.
Navigation: Dashboard · Library · Shots/Scenes · Actors · Transcripts · Search · Timeline · Export · Settings.
- **Dashboard**: totals (videos, shots, scenes, duration, actors, transcript minutes, analysed clips, low-quality clips), processing status, charts (quality distribution, shots per clip, speaking time per actor).
- **Library**: cards/rows with thumbnail, name, duration, scene, quality score, actors, transcript status, processing status; sort/filter; select/reject/star; bulk actions.
- **Clip detail**: proxy player with J/K/L, I/O, space, arrow-frame stepping; shot boundary strip; waveform with QC flag overlays; transcript synced to playback (click to seek); actors with face crops; tags with confidence; quality breakdown; QC flags; markers.
- **Processing**: per-stage progress via SSE, cancel/retry, readable errors.
- **Search**: one box (text) + drop image; filters; result cards with "why"; weights panel.
- **Timeline**: see §11. **Export**: format picker, preview of what will be written, test-import instructions.
- Empty states, loading states and error states for every screen. First-run wizard runs `doctor` and explains what is missing in plain language.

## 15. Errors (plain-language messages, never silent)
Invalid/corrupt/unsupported video · FFmpeg missing · no audio track · no speech · no face · many faces · model missing/not downloaded · out of memory (fall back to a smaller tier and say so) · low disk space (check before proxy generation) · file moved/missing (offer relink) · job crashed (keep partial results, allow retry).

## 16. Testing
- Unit + integration tests with pytest; API tests with httpx; DB tests on temp SQLite.
- **Synthetic fixtures generated with ffmpeg** (`testsrc`, color blocks, sine tones, silence gaps, known cut positions) so shot detection, quality metrics, silence detection and timeline math have exact ground truth and need no copyrighted footage.
- Model-dependent tests marked `@pytest.mark.model` (run on demand) using a few short real clips (use own-recorded or open-licensed footage; record licenses in `eval/DATASETS.md`). Fakes/mocks are allowed ONLY in tests, never in the app.
- Frontend: Vitest + Testing Library for components; Playwright E2E for the main flow (create project → import → process → search → rough cut → export).
- Timeline: export/re-parse round-trip, frame-accurate duration checks incl. 23.976/29.97.
- Security tests: path traversal, filename sanitization, subprocess argument safety.
- Manual test procedures in `docs/TESTING.md` (including Resolve import checklist).

## 17. Evaluation (real experiments only)
Build `eval/` incrementally with each module; every script is reproducible (`uv run python -m eval.<name>`), writes JSON/CSV to `eval/results/` with config + model versions + hardware, and `docs/EVALUATION.md` quotes only those files.
- Datasets: own shoot + open-licensed footage (e.g. Blender open movies such as Tears of Steel, Pexels/Pixabay clips; verify licenses). Target: ≥ 60 min diverse footage, with hand-labelled ground truth: shot boundaries (assisted), ~20 min of hand-corrected transcripts, ≥ 300 labelled face crops across several people, 30–50 search queries with relevance judgments, ~200 clips labelled sharp/blurry/over/under-exposed.
- Metrics: shot detection precision/recall/F1 (± N frames tolerance) · blur/exposure classification accuracy/P/R · transcription WER (jiwer) per model tier · face clustering purity, ARI/NMI, B-cubed F1 · search P@K, nDCG@K, MRR with ablations (BM25 vs dense vs visual vs hybrid, ± quality, ± selects) · take grouping precision/recall (P1-B) · script alignment accuracy (P1-A) · real-time factor (processing seconds per minute of footage) per tier and hardware · peak RAM.
- **User study** (the key result): ≥ 5 participants (or ≥ 5 repeated tasks), timed tasks such as "find every shot where X happens" and "assemble a 60-second selects sequence", manual (file browser/Resolve media pool) vs CineMind. Report times, time saved %, and honest limitations (small n). Provide the task protocol and a CSV template; the user will run it.
- Do not tune on the test split; keep a held-out set.

## 18. Documentation to maintain
README.md; docs/: PROJECT_OVERVIEW, ARCHITECTURE, DATABASE, API, AI_PIPELINE (incl. quality + ranking formulas), DEVELOPMENT_PLAN (=ROADMAP summary), TESTING, EVALUATION, DECISIONS, USER_GUIDE, PROGRESS. Update docs in the same commit as the change. `ACADEMIC_NOTES.md`: table of existing models/libraries vs our pipeline vs our scoring logic vs our evaluation (for the report/viva).
````

---

## FILE 3 — `docs/ROADMAP.md`

````markdown
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
````

---

## FILE 4 — `.claude/` helpers (create in Phase 0)

````markdown
<!-- .claude/commands/next-phase.md -->
Continue CineMind development.
1. Read docs/PROGRESS.md, CLAUDE.md, and the next unfinished phase in docs/ROADMAP.md (or the phase named here: $ARGUMENTS).
2. Inspect the current implementation first. State a short plan (what, files, risks). 
3. Implement ONLY that phase, with tests alongside. Run `just check`, run the app, verify the feature works (Playwright MCP for UI).
4. Use the code-reviewer subagent on the diff and fix what it finds.
5. Update docs + PROGRESS.md, commit with Conventional Commits.
6. End with the Phase Report from CLAUDE.md. Do not start the next phase.

<!-- .claude/commands/verify.md -->
Run the full verification: lint, type-check, backend tests, frontend tests, and the Playwright smoke test. Start the app, hit /api/system/health, and report PASS/FAIL per step with exact error output for failures. Fix failures you caused; report ones you can't fix.

<!-- .claude/commands/status.md -->
Summarise current state from docs/PROGRESS.md and `git log --oneline -15`: finished phases, current phase, open issues, DEVELOPMENT PLACEHOLDERs still in the code (grep for them), and the recommended next step.

<!-- .claude/agents/code-reviewer.md -->
---
name: code-reviewer
description: Reviews the current git diff for bugs, security issues (path traversal, shell injection, unsafe file serving), fake/placeholder AI, spec violations, missing tests and missing docs. Use proactively at the end of every phase.
tools: Read, Grep, Glob, Bash
---
You are a strict senior reviewer for CineMind AI. Read CLAUDE.md first. Review `git diff` against the Non-negotiables. Look for: shell=True or unsanitized args, paths escaping media roots, hard-coded absolute paths, silent exception swallowing, uncached/non-idempotent stages, float-fps timeline math, mocked AI outside tests, unlabeled placeholders, fabricated metrics in docs, missing error messages, files > 400 lines, unused dependencies. Output a prioritised list (Blocker / Should fix / Nit) with file:line and a concrete fix. Do not edit files.

<!-- .claude/agents/eval-scientist.md -->
---
name: eval-scientist
description: Designs and runs evaluation experiments (shot detection, WER, clustering, retrieval, timing) and writes honest results. Use for any metric, benchmark or EVALUATION.md change.
tools: Read, Grep, Glob, Bash, Edit, Write
---
You produce reproducible experiments for CineMind AI. Every number you report must come from a committed script in eval/ that you ran; record dataset version, config, model versions and hardware. Use held-out data, report confidence intervals or variance where feasible, include ablations, and state limitations plainly. Never invent, round up or "expect" results. If data is missing, write the labelling instructions for the user instead.

<!-- .claude/settings.json (merge with existing; adjust to this OS) -->
{
  "permissions": {
    "allow": [
      "Bash(uv run:*)", "Bash(uv sync:*)", "Bash(uv add:*)", "Bash(pnpm:*)", "Bash(just:*)",
      "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git add:*)", "Bash(git commit:*)",
      "Bash(ffprobe:*)", "Bash(ffmpeg:*)"
    ],
    "deny": [
      "Bash(git push --force:*)", "Bash(git reset --hard:*)", "Bash(git clean:*)", "Bash(rm -rf:*)"
    ]
  },
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          { "type": "command", "command": "uv run ruff format --quiet backend eval scripts || true" }
        ]
      }
    ]
  }
}
````

---

## KICKOFF PROMPT (paste this into Claude Code, in Plan Mode, after editing the Project Context)

````text
You are the lead engineer (architecture, AI/CV, backend, frontend, QA, DevOps) building CineMind AI with me, the product owner. Read CINEMIND_PACK.md in this folder completely.

PROJECT CONTEXT (edited by me):
- Team/skill: B.Tech CSE student project; I know basic C++, so explain important Python/React/AI decisions briefly in plain language.
- Deadline / demo date: <fill in>
- DaVinci Resolve: <free or Studio, version>
- Footage: <e.g. my own short film / phone footage; languages spoken: English / Tamil / Hindi ...>
- OS: <Windows / macOS / Linux> (detect it yourself and use cross-platform code and commands; no bash-only scripts)

TASKS NOW:
1. Extract the files defined in CINEMIND_PACK.md verbatim into the repo: CLAUDE.md, docs/SPEC.md, docs/ROADMAP.md, and the .claude/ helpers (commands, agents, settings). Keep CINEMIND_PACK.md in docs/archive/.
2. Create docs/PROGRESS.md and docs/DECISIONS.md.
3. Execute ONLY Phase 0 from docs/ROADMAP.md: inspect my environment (Python, uv, Node, pnpm, Git, FFmpeg, CPU/RAM/GPU), tell me exactly what to install if anything is missing (do not install system packages without asking), build the skeleton, `cinemind doctor`, and prove frontend ↔ backend communication through the generated API client.
4. Recommend the model tier for my hardware and explain why. Verify current versions of key libraries and models before pinning them.
5. Commit, then give me the Phase Report. Stop; do not start Phase 1.

RULES: follow CLAUDE.md. Do not build advanced AI features yet. Make routine decisions yourself and log them in DECISIONS.md; ask me only for things you truly cannot decide or do (e.g. installing FFmpeg, large model downloads, the manual Resolve import test).
````

---

## Appendix A — Per-phase "continue" prompt (if you don't use `/next-phase`)

```text
Proceed with the next phase. Read docs/PROGRESS.md and the phase in docs/ROADMAP.md. Inspect the current implementation first, implement only that phase with tests, run and verify the app, run the code-reviewer subagent, fix issues, update docs and PROGRESS.md, commit, and give the Phase Report.
```

## Appendix B — Tips for working with Claude Code on this project

- Use **Plan Mode** for phases 4, 7, 9, 11, 12: let it plan, read the plan, then approve.
- `/clear` between phases; `docs/PROGRESS.md` carries the state. Use `/compact` only inside a long phase.
- Commit after every stable step so you can roll back (Claude Code checkpoints are not a replacement for git).
- Keep a **sample-footage folder** early (5–10 short clips: a dialogue scene with 2–3 people, an outdoor walking scene, a deliberately blurry/dark clip, one HEVC or MKV file, one clip without audio). Phases 3–9 become much easier to verify.
- Two things only you can do: (1) test the Resolve import (Phase 4 and 11), (2) label the evaluation ground truth and run the user study (Phase 13). Claude will prepare templates and scripts for both.
- If a model download or install is large, let Claude ask first; model downloads are the only time internet is needed.
- Run `/status` whenever you come back after a break.
