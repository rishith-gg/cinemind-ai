# API

OpenAPI is the contract (`T gen-api` regenerates the TypeScript client). Errors are always
`{"code": "<machine code>", "message": "<plain language>"}`; codes: `invalid_input` (422), `not_found` (404),
`path_not_allowed` (403), `job_state` (409), `unreadable_media` / `unsupported_media` (422), `source_missing` (404),
`too_large` (413), `low_disk_space` (507), `ffmpeg_missing` (500).

## Implemented (Phase 1)
- `GET /api/system/health`
- `POST/GET /api/projects`, `GET/PATCH/DELETE /api/projects/{id}`
- `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel`, `POST /api/jobs/{id}/retry`
- `GET /api/jobs/events` (SSE). Query: `job_id` (filter), `follow=false` (send stored events, then close).
  Frames carry `id:` = `job_events.id`; reconnect with `Last-Event-ID` to resume without gaps.

## Implemented (Phase 3): ingest and library
- `GET /api/fs/browse?path=` folder browser. Without `path` it lists the approved roots (`media_roots`). Paths must be
  absolute and resolve (symlinks followed) inside a root; links leaving a root are hidden.
- `POST /api/projects/{id}/media` body `{paths, mode: reference|copy}`: files or folders (recursive, media-like names
  only). One result per file (`duplicate`, `error_code`); one bad file never aborts the batch. Queues the `ingest` job.
- `POST /api/projects/{id}/media/upload?filename=` raw body (`application/octet-stream`), streamed to disk, capped by
  `max_upload_mb` (default 2048), file name sanitized. 413 `too_large` when over the cap.
- `GET /api/projects/{id}/media`, `GET/DELETE /api/media/{id}`. Delete removes derived data (and our own copy/upload),
  never a referenced source. `source_missing` is computed on read.
- `POST /api/media/{id}/relink` `{path}`: accepted only if the content hash matches.
- `POST /api/media/{id}/process`, `POST /api/projects/{id}/process`: (re)queue ingest; no duplicate while one is active.
- `GET /api/jobs?project_id=&status=&limit=`.
- Files (derived data only, served with HTTP Range): `GET /api/media/{id}/stream` (proxy), `/poster`, `/strip`
  (horizontal thumbnail strip, `strip_frames` evenly spaced tiles), `/waveform` (`{duration, peaks[1000]}`, 0..1).

## Ingest chain (`ingest`): validate, proxy, thumbnails, waveform
- validate: ffprobe (by content, not extension): rational fps, VFR flag (avg vs nominal rate differ > 0.5 %),
  codecs, display size (rotation applied), timecode, colour tags. Corrupt or non-media files fail with a plain message.
- proxy: H.264 (+AAC), <= `proxy_max_height` (720), constant frame rate (nominal rate, halved above 60), `+faststart`.
  Encoder order: NVENC, VideoToolbox, QSV if FFmpeg lists them, with automatic fallback to libx264 (CPU) if one fails
  at run time. Audio-only sources get an AAC `.m4a` proxy. Disk space is checked first.
- thumbnails (poster + strip) and waveform peaks are made from the proxy. Everything is written to a `.partial` file and
  renamed, so a crash never leaves a half-written artifact.
- Stage cache for these stages is per project and re-validated against the files on disk (`Stage.scope_project`,
  `Stage.verify`); `Stage.persist` copies results onto the media row, also on a cache hit.

## Jobs and the worker
`cinemind serve` starts the API and one worker process (`--no-worker` to skip; `cinemind worker` runs it alone).
The worker polls `jobs`, runs the chain's stages in order, caches each stage, and writes events.
On startup it re-queues any job left `running` (assumes exactly one worker); finished stages come back from the
cache, so a killed job resumes at the stage that was interrupted (that stage restarts from its beginning).
Cancel is cooperative: stages call `ctx.check_cancelled()` and the runner checks between stages.
Retry keeps succeeded stages.

## Static frontend
`cinemind serve` serves `frontend/dist`. Unknown extensionless non-`/api` paths return `index.html` (client-side routing deep links and reloads); missing files with an extension and unknown `/api` paths are real 404s.
