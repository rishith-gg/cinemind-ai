# Contributors

CineMind AI was built by three students for BCSE306L (Artificial Intelligence, Slot C1 + TC1) at VIT, with equal
effort. Development happened on one shared machine, so most of the history is committed from one account; each member
describes their own part below and committed it from their own account.

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
