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

## Phase 4 tables (migrations 0003, 0004)
| Table | Purpose |
|---|---|
| `shots` | one detected shot of a media asset: `index`, `start_frame`/`end_frame` (end exclusive) and `start_s`/`end_s` on the proxy's constant frame rate (`fps_num/fps_den`), and `detection` (library, version, detector, threshold, minimum length). Id = hash of (media id, start frame, end frame). Cascades from `media_assets`. |
| `keyframes` | 1 to 3 per shot: `slot`, `frame`, `time_s`, `path` (JPEG, relative to the project dir, under `keyframes/<media id>/`), `sharpness` (why it was picked). Cascades from `shots`. |
| `timelines` | `name`, `kind` (`all_shots`), rational `fps_num/fps_den`, `width`/`height`, `params` (how it was built: order, rate choice, clips left out). |
| `timeline_items` | ordered cuts: `position`, `media_id`, optional `shot_id` (set to NULL if the shot disappears), `source_in_s`/`source_out_s`. Frames are computed at export time on the timeline rate. Cascades from `timelines` and `media_assets`. |

`media_assets` gained `nominal_fps_num/nominal_fps_den` (the stream's base rate; `fps_*` is the measured average).

## Phase 5 tables (migration 0005)
| Table | Purpose |
|---|---|
| `quality_metrics` | one row per shot (`shot_id` is the key): frames measured, the seven picture metrics, the three sub-scores (`sharpness_score` is NULL when focus was not judged), the shot score, and `details` (the settings used, metrics version). Rewritten on every job run. |
| `audio_metrics` | one row per clip with sound: integrated LUFS, loudness range, true peak, sample peak, clipped %, silence seconds and %, audio score, `details`. |
| `qc_flags` | `kind`, `source` (picture or audio), optional `shot_id`, `start_s`/`end_s`, and `details` (metric, value, threshold, direction, or detector and settings). |

`media_assets` gained `quality_score` (clip-level Technical Quality Score, null until measured).

## Phase 6 tables (migrations 0006, 0007)
| Table | Purpose |
|---|---|
| `transcripts` | one row per clip once the transcribe stage ran: `status`, `language` and its probability, `model` and `model_revision`, `speech_s` (seconds kept by the voice-activity detector), `digest` (hash of the stage result the rows were written from; an unchanged result keeps its rows and ids), `details` (engine version, device, compute type, settings, reason when there is no text). |
| `transcript_segments` | `index`, `start_s`/`end_s`, `text`, `confidence` (mean word probability), and the model's `avg_logprob`, `no_speech_prob`, `compression_ratio`. Integer id. Cascades from `media_assets`. |
| `transcript_words` | `segment_id`, `index`, `start_s`/`end_s`, `word`, `probability`. Cascades from `transcript_segments`. |
| `transcript_fts` | FTS5 virtual table over `transcript_segments.text` (external content, `rowid` = segment id, tokenizer `unicode61 remove_diacritics 2 categories 'L* N* Co Mn Mc'` since 0007, which rebuilds the index so combining marks stay inside words). Three triggers on `transcript_segments` keep it in step, also for cascaded deletes. Not an ORM model; created with raw SQL in the migration. |
