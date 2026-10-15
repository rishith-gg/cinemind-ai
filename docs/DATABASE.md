# Database

SQLite at `data/cinemind.db` (WAL, `foreign_keys=ON`, `busy_timeout=30s`). Schema is owned by Alembic
(`backend/src/cinemind/db/migrations`); the API and worker run `upgrade head` at startup.
Add tables only through a new migration (`alembic revision --autogenerate`, then replace app types such as
`UTCDateTime` with plain `sa.DateTime()` so old migrations never import app code).

## Phase 1 tables
| Table | Purpose |
|---|---|
| `projects` | id (uuid hex), name, description, timestamps, `settings` (JSON, choices made in the app, e.g. `speech`: `{languages, detect_only}`; migration 0011). Deleting removes derived files under `data/projects/<id>/` only. |
| `media_assets` | id, project_id, path, filename, `content_hash`. `import_mode` (reference/copy/upload), `size_bytes`, ffprobe metadata (`probed`, container, duration, size, rational `fps_num/fps_den`, `is_vfr`, codecs, bitrate, audio, timecode, colour) and artifact paths relative to the project dir (`proxy_path`, `poster_path`, `strip_path`, `waveform_path`), `speech_language` (set by the user for this clip, null = detected; migration 0011). Unique `(project_id, content_hash)` = duplicate detection. Migration 0002. |
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
| `transcripts` | one row per clip once the transcribe stage ran: `status` (incl. `not_written` = speech in a "detect only" language), `language` and its probability, `model` and `model_revision`, `speech_s` (seconds kept by the voice-activity detector), `digest` (hash of the stage result the rows were written from; an unchanged result keeps its rows and ids), `details` (engine version, device, compute type, settings, `language_source` (`detected`, `project`, `clip`, `settings`), `language_scores`, reason when there is no text). |
| `transcript_segments` | `index`, `start_s`/`end_s`, `text`, `confidence` (mean word probability), and the model's `avg_logprob`, `no_speech_prob`, `compression_ratio`. Integer id. Cascades from `media_assets`. |
| `transcript_words` | `segment_id`, `index`, `start_s`/`end_s`, `word`, `probability`. Cascades from `transcript_segments`. |
| `transcript_fts` | FTS5 virtual table over `transcript_segments.text` (external content, `rowid` = segment id, tokenizer `unicode61 remove_diacritics 2 categories 'L* N* Co Mn Mc'` since 0007, which rebuilds the index so combining marks stay inside words). Three triggers on `transcript_segments` keep it in step, also for cascaded deletes. Not an ORM model; created with raw SQL in the migration. |

## Phase 7 tables (migration 0008)
Models live in `db/people.py` (imported by `db/models.py`).

| Table | Purpose |
|---|---|
| `face_scans` | one row per clip once the faces stage ran: `status` (`done`, `no_faces`, `no_video`, `model_missing`), `frames_sampled`, `faces_detected`, `faces_used`, `max_in_frame`, `digest` (hash of the stage result; an unchanged result keeps its tracks, their ids and their actors), `details` (models, revisions, settings, faces left out per check, reason). |
| `face_tracks` | one face followed through one shot: `media_id`, `shot_id`, `index`, `start_s`/`end_s`, `face_count`, `embedding` (128 float32, length 1: the mean SFace vector), `crop_path` (inside the scan's own folder), `actor_id` (null when set aside), `state` (`auto`, `pinned`, `ignored`, `unknown`, `brief` = seen in too few sampled frames to group, set aside automatically), `assignment` (why it sits with its actor). Id = hash of (media, first frame, first box). |
| `faces` | every used face: `track_id`, `frame`, `time_s`, box `x`,`y`,`w`,`h` as fractions of the frame, `score`, `size_px`, `sharpness`, `turn`. Cascades from `face_tracks`. |
| `actors` | a group of tracks: `project_id`, `number` (lowest free number when created), `name` ("Actor 001" until renamed), `named`. Local to the project. |
| `face_pins` | the user's corrections, one row per face of a corrected track: `media_id`, `time_s`, box, `state` (`actor` = moved there by hand, `kept` = was with the actor when it was named or corrected, `ignored`, `unknown`), `actor_id`, and `track_id` (the track it currently belongs to; reset when the clip is scanned again and found again by place and time). Cascades from the clip and from the actor. |
| `actor_runs` | one row per project: `digest` (hash of what the grouping depends on: scan digests, pins, "different people" answers, method, distance, `min_track_faces`; an unchanged project is not grouped again), `details` (engine, method, distance, counts), `clustered_at`. |
| `actor_pair_answers` | the user's answers to "same person?": `project_id`, `tracks_a`, `tracks_b` (track ids of the two people when asked), `same`, `distance` (average-linkage distance then), `created_at`. "Different" answers keep those tracks apart in later groupings; all answers are labels for `eval/actor_pairs.py`. Migration 0010. |
| `feedback_events` | append-only log of corrections: `kind` (`actor_rename`, `actor_merge`, `actor_split`, `face_place`, `actor_pair`) and `payload`. Not read by the app yet; kept for the ranking phase. |


## Phase 8 tables (migration 0009)
Models live in `db/analysis.py` (imported by `db/models.py`). SPEC section 7 names a `vector_refs` table holding
pointers into the index files; here the vectors themselves are stored (`embeddings`), so the index files under
`index/` are derived data that can always be rebuilt from the database (roadmap acceptance), and positions in an
index file are mapped back to rows by a `.ids.json` file written next to it.

| Table | Purpose |
|---|---|
| `embedding_sets` | one row per clip and kind (`visual`, `text`) once the stage ran: `status` (`done`, `no_video`, `no_speech`, `no_transcript`, `model_missing`), `model`, `revision`, `count`, `digest` (hash of the stage result plus the keyframe or segment ids it points at; unchanged = rows left alone), `details` (engine, device, dimension, reason). |
| `embeddings` | one vector per row: `kind` (`keyframe` = picture model, `color` = HSV histogram, `segment` = transcript text model), `ref_id` (keyframe id or segment id), `shot_id` (keyframes and colours), `model`, `dim`, `vector` (float32 bytes; unit length except histograms, which sum to 1). No foreign key on `ref_id`: keyframe rows are rewritten on every run with the same ids. Cascades from the clip and the shot. |
| `tags` | one row per shot and tag, rewritten on every run: `group` (`setting`, `time`, `shot_size`, `place`, `faces`, `speech`), `name`, `label`, `source` (`model`, `faces`, `transcript`), `score` (mean over the shot's keyframes), `threshold` (the evaluated one, if any), `status` (`shown`, `below`, `disabled`, `not_evaluated`), `details` (model, revision, vocabulary version, keyframe scores, the evaluation behind the threshold, top Places365 categories for place tags, the rule for counted tags). |
| `tag_reviews` | the user's decision on a tag of a shot: `shot_id` (no foreign key, so it outlives a re-detection that keeps the shot's frames), `name`, `decision` (`approved`, `rejected`). Also logged in `feedback_events` (`tag_review`, with the score, threshold and status the app had suggested). |
| `scenes` | rebuilt by every grouping: `id` (hash of project and first shot), `index`, `name` ("Scene 001" or the user's), `named`, `shot_count`, `duration_s`, `details.steps` (per shot: similarity to the shot before, both signals, the decision in words). |
| `shots.scene_id` | the scene a shot belongs to (null until grouped). |
| `scene_edits` | the user's edits by shot id: `split` (a scene starts here), `join` (stays with the shot before), `name` (`value` = name of the scene holding this shot). Logged in `feedback_events` (`scene_boundary`, `scene_rename`). |
| `scene_runs` | one row per project: `digest` (shots, visual embedding digests, edits, settings; unchanged = not grouped again), `details` (model, settings, order, counts), `grouped_at`. |
| `vector_indexes` | one row per index file: `project_id`, `kind` (`keyframe`, `segment`), `model`, `backend` (`faiss`, `numpy`), `dim`, `count`, `digest` (hash of the rows it holds; a different digest = out of date), `path`, `built_at`. |
| `search_judgments` | relevance labels for the search evaluation: `project_id`, `media_id` (cascade), `query` (normalised), `shot_id` (no foreign key, like tag reviews), `relevant`, `judge` ("user" from the app, or the name given to `eval/search_eval.py import`), `created_at`. Unique per project, query, shot and judge. Migration 0012. |
