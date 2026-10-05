# Database

SQLite at `data/cinemind.db` (WAL, `foreign_keys=ON`, `busy_timeout=30s`). Schema is owned by Alembic
(`backend/src/cinemind/db/migrations`); the API and worker run `upgrade head` at startup.
Add tables only through a new migration (`alembic revision --autogenerate`, then replace app types such as
`UTCDateTime` with plain `sa.DateTime()` so old migrations never import app code).

## Phase 1 tables
| Table | Purpose |
|---|---|
| `projects` | id (uuid hex), name, description, timestamps. Deleting removes derived files under `data/projects/<id>/` only. |
| `media_assets` | id, project_id, path, filename, `content_hash`. `import_mode` (reference/copy/upload), `size_bytes`, ffprobe metadata (`probed`, container, duration, size, rational `fps_num/fps_den`, `is_vfr`, codecs, bitrate, audio, timecode, colour) and artifact paths relative to the project dir (`proxy_path`, `poster_path`, `strip_path`, `waveform_path`). Unique `(project_id, content_hash)` = duplicate detection. Migration 0002. |
| `jobs` | one processing run: `chain`, `params`, `status` (queued/running/succeeded/failed/cancelled), `progress`, `cancel_requested`, error code/message, `attempts`. |
| `job_stages` | one row per stage of the chain: status (pending/running/succeeded/cached/failed/cancelled), progress, and provenance (`cache_key`, `params_hash`, `model_name`, `model_version`). |
| `stage_results` | the cache. Key = sha256 of `(media content hash, stage, params hash, model name, model version)`; value = the stage's JSON result. |
| `job_events` | append-only event log (`queued`, `started`, `stage`, `progress`, `cancel_requested`, `succeeded`/`failed`/`cancelled`) streamed over SSE. |

Jobs without a media asset use `project:<id>` as the "media hash" in the cache key.
Datetimes are stored as naive UTC and returned timezone-aware (`UTCDateTime`).
