# Contributors

CineMind AI was built by three students for BCSE306L (Artificial Intelligence, Slot C1 + TC1) at VIT, with equal
effort. Each commit is attributed to the member who owned that part of the work; each member describes their own part
below.

## Rishith Raj G (24BCE0175) · [@rishith-gg](https://github.com/rishith-gg)
- System architecture: FastAPI service, SQLite schema with Alembic migrations, job queue and worker with cached,
  resumable stages, security rules (localhost binding, media-root path validation).
- Ingest pipeline: ffprobe metadata, content hashing, proxies, thumbnails, waveforms; shot detection and keyframes;
  timeline export to FCP7 XML, CMX3600 EDL and OpenTimelineIO, and the manual DaVinci Resolve import tests.
- Speech: faster-whisper transcription with word timings, uncertainty marking, per-project languages;
  script-to-footage alignment and the script assembly.
- Report: introduction, methodology, proposed approach, tools and technologies.

## Hrishikesh Acharya (24BDS0231) · [@Hrishikesh-Acharya](https://github.com/Hrishikesh-Acharya)
- Computer vision: technical quality metrics (focus, exposure, contrast) and audio QC, with threshold calibration on
  synthetically degraded frames.
- Faces and actors: YuNet/SFace detection, tracking, constrained agglomerative clustering and the "same person?"
  review loop; evaluation on LFW (purity, ARI, NMI, B-cubed).
- Embeddings and tags: OpenCLIP/SigLIP picture vectors, MiniLM text vectors, zero-shot tag calibration on Places365
  and CODaN, scene grouping, and take detection with best-take signals.
- Report: dataset description, result analysis and figures, summary of gaps.

## Krish Singh (24BDS0235) · [@singhkrish2006](https://github.com/singhkrish2006)
- Frontend: React + TypeScript + Tailwind interface (library, clip player, shots/scenes, actors, transcripts, search,
  takes, script, timeline editor with drag-and-drop, export), generated API client, Vitest and Playwright tests.
- Search and ranking: four retrieval lists, Reciprocal Rank Fusion, explainable weighted ranking with MMR duplicate
  penalty and what-if sliders; search evaluation (P@K, nDCG@10, MRR, ablations).
- Rough-cut engine: brief parsing, candidate selection, speech-aware trimming, length fitting, ordering, swap
  suggestions and SRT/marker export; timing evaluation.
- Report: comparative analysis, user manual with screenshots, presentation and demonstration video.
