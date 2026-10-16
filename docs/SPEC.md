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
Script (P1-A): `POST/GET/DELETE /api/projects/{id}/script`, `POST .../script/align`, `POST .../script/assembly`, `PUT /api/script-lines/{id}/take` (D-098)
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
