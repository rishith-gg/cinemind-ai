# API

OpenAPI is the contract (`T gen-api` regenerates the TypeScript client). Errors are always
`{"code": "<machine code>", "message": "<plain language>"}`; codes: `invalid_input` (422), `not_found` (404),
`path_not_allowed` (403), `job_state` (409), `unreadable_media` / `unsupported_media` (422), `source_missing` (404),
`too_large` (413), `low_disk_space` (507), `ffmpeg_missing` (500), `export_failed` (500), `model_missing` (409), `transcription_failed` (500).

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

## Implemented (Phase 4): shots, keyframes, timelines, export
- `GET /api/media/{id}/shots`, `GET /api/projects/{id}/shots` (adds `filename`): shots with `start_s`/`end_s`,
  frames on the proxy rate, `detection` (library, detector, threshold) and their keyframes (`time_s`, `sharpness`).
- `GET /api/keyframes/{id}/image` (JPEG).
- `POST /api/projects/{id}/timelines` body `{name, kind: "all_shots", fps?: [num, den], mixed_rates: include|exclude}`:
  every detected shot, clips in file-name order. `fps` omitted = the rate most clips have. 422 when there are no shots.
- `GET /api/projects/{id}/timelines`, `GET/DELETE /api/timelines/{id}`. A timeline reports `item_count`,
  `duration_frames`, `warnings` (mixed frame rates, missing originals) and, in detail, each cut's record position.
- `GET /api/timelines/{id}/export/{fcp7xml|edl|otio}`: writes the file to `data/projects/<id>/exports/` and downloads
  it. Files reference the ORIGINAL media (`file://` URL), never the proxy. An EDL is refused (422) above 60 fps or
  above 999 cuts.

## Implemented (Phase 5): technical quality and QC
- Media items carry `quality_score` (0..1, null until measured), `low_quality` and `qc_flags` (kinds present).
- `GET /api/media/{id}/quality`: the clip score, per-shot metrics and sub-scores, audio measurements, every flag
  with its time range and the value/threshold (or detector) behind it, and the `[quality]` settings in force.
  Formulas: AI_PIPELINE.md. Where the thresholds come from: EVALUATION.md.

## Implemented (Phase 6): transcripts and keyword search
- Media items carry `transcript_status` (null until the stage ran) and `transcript_language`.
- `GET /api/media/{id}/transcript`: `status` (`pending`, `done`, `no_speech`, `no_audio`, `model_missing`,
  `audio_unreadable`), a plain `message` whenever there is no text, language and its probability, model, revision,
  engine and settings, and the segments with their words (start, end, probability). `uncertain` and
  `language_uncertain` are explained in AI_PIPELINE.md; the limits are returned in `thresholds`.
- `GET /api/projects/{id}/transcripts`: one row per clip (status, language, seconds of speech, segment and word count).
- `GET /api/projects/{id}/speech-languages`: `{languages, detect_only, available}` (empty `languages` = detect any).
  `PUT` with `{languages, detect_only}` saves them and queues every clip again (`queued`); only transcripts and what
  is made from them are redone. Unknown codes, duplicates, more than 8, or "detect only" outside the list are 422.
- `PUT /api/media/{id}/speech-language` `{language}` (a code, or null to detect): sets the clip's language and
  queues it. Media items carry `speech_language`. Transcript status `not_written` = speech in a "detect only"
  language (no text, `speech_s` set).
- Search leaves out segments marked uncertain unless `include_uncertain=true`.
- `GET /api/projects/{id}/transcripts/search?q=...&media_id=...&limit=50`: keyword search (FTS5, BM25 order). Each
  hit has the clip, the segment's time range, `jump_s` (when the first word starting with the first search term is
  spoken, else the segment start) and the text split
  into `parts` with `match` set on the found words. An entry without any letter or digit is a 422.
- CLI: `cinemind models list`, `cinemind models pull [name] [--yes]` (asks before a download over 2 GB).
  `cinemind doctor` and `/api/system/health` report whether the tier's speech model is on disk.

## Implemented (Phase 7): faces and actors
- `GET /api/media/{id}/faces`: `status` (`pending`, `done`, `no_faces`, `no_video`, `model_missing`), a plain
  `message` when there is nothing to show, counts (frames sampled, faces detected and used, most in one frame),
  `details` (models, revisions, settings, how many faces each check left out) and the clip's tracks, each with its
  time range, crop, actor, `state` (`auto`, `pinned`, `ignored`, `unknown`) and `assignment` (why it sits there).
- `GET /api/projects/{id}/actors`: the people, most seen first (name, `named`, tracks, faces, clips, seconds seen,
  crop), how many tracks are set aside, clips per scan state, a `message` when faces are missing for a reason the
  user can fix, and `run` (engine, method, distance, counts of the last grouping).
- `POST /api/projects/{id}/actors/regroup`: group again with the current `[faces]` settings; corrections stay.
- `GET /api/actors/{id}`: one person with every track. `PATCH /api/actors/{id}` `{name}`: rename.
  `POST /api/actors/{id}/merge` `{actor_ids}`: merge the listed people into this one.
  `POST /api/actors/{id}/split` `{track_ids}`: move those tracks to a new person (returned).
  SPEC section 12 lists all three under `PATCH`; they are separate calls so each has one clear body.
- `POST /api/projects/{id}/face-tracks/place` `{track_ids, state, actor_id?}`: `actor` (move to `actor_id`),
  `ignored` (not a face), `unknown` (a person not worth naming), `auto` (hand back to automatic grouping).
  `GET /api/projects/{id}/face-tracks`: the tracks currently set aside, by the user (`ignored`, `unknown`) or
  automatically (`brief`: seen in too few sampled frames). `ActorsOut.brief` counts the latter.
- `GET /api/projects/{id}/actors/pairs`: "same person?" questions, closest first (`first`, `second`, `distance`),
  with `cluster_distance` and how many were answered. `POST /api/projects/{id}/actors/pairs/answer`
  `{first_id, second_id, same}`: yes merges the two, no keeps their tracks apart from now on; returns the new list.
- `GET /api/face-tracks/{id}/image`: the track's face crop (JPEG).
- Ids from another project, unknown ids, an empty name, a move without a target or a split that would leave nobody
  are 404/422 with a plain message. Cancelling a project's last queued job groups the faces found so far. The job event stream sends an `actors` event after a project was grouped.
- CLI: `cinemind models pull` now also fetches the face models (`models pull faces` for those alone);
  `models list`, `cinemind doctor` and `/api/system/health` report whether they are on disk.

## Implemented (Phase 8): scenes, tags, embeddings, vector indexes
- `GET /api/projects/{id}/scenes`: the scenes in order, each with its shots (clip, time range, first keyframe, the
  similarity to the shot before: `visual`, `color`, `combined`, the `decision` in words, the user's `edit`), shots
  not grouped yet (`ungrouped`), the `[scenes]` settings, the last grouping's `details`, and `model_missing` with a
  `message` when the picture model is not on disk.
- `PUT /api/projects/{id}/scenes/boundaries` `{shot_id, decision}`: before that shot, `split` (start a scene),
  `join` (stay with the shot before; not for the project's first shot), or `auto` (the similarity decides again).
  `PATCH /api/scenes/{id}` `{name}`: rename (an empty name goes back to the number).
  `POST /api/projects/{id}/scenes/regroup`: group again; edits stay. All three return the new scene list.
- `GET /api/media/{id}/tags`: the visual embedding `status` with a plain `message`, the model, when its thresholds
  were set and from which results file, and per shot every tag with `score`, `threshold`, `status`, the user's
  `review`, `visible` (approved, or `shown` and not rejected) and `details` (the evaluation behind the threshold).
- `PUT /api/tags/review` `{shot_id, name, decision}`: `approved`, `rejected` or `none` (withdraw). Returns the clip's
  tags. `GET /api/projects/{id}/tags`: the visible tags of the project with the number of shots each is on.
- `GET /api/media/{id}/embeddings`: state of the `visual` and `text` embeddings of a clip.
- `GET /api/projects/{id}/index`: the vector index files (kind, model, backend, size, `up_to_date`).
  `POST /api/projects/{id}/index/rebuild`: rebuild them all from the database.
- The job event stream sends a `scenes` event after a project was grouped into scenes. Removing a clip regroups
  actors and scenes and updates the indexes.
- CLI: `cinemind models pull` now also fetches the picture and text models of the tier (`models pull visual`,
  `models pull text`, or a model name such as `siglip-base`); `models list` and `cinemind doctor` report them.

## Implemented (Phase 9): hybrid search
- `POST /api/projects/{id}/search` `{q | like_shot_id, filters?, use?}`: shots, best first. `filters`: `media_id`,
  `actor_id`, `scene_id`, `min_quality` (0..1), `has_dialogue`. `use`: which lists (`keyword`, `labels`, `text`,
  `visual`; default all). A `like_shot_id` search uses the picture list only. Each result: shot, clip, times,
  `jump_s`, `keyframe_url`, scene name, quality score, fused `score`, `why` (per list: `rank`, `score`,
  `contribution`, `time_s`, matched `text` / `parts` / `matched` labels) and the user's judgment (`relevant`).
  The response also says how many shots each list found, which lists could not run and why, `rrf_k` and `weights`.
- `POST /api/projects/{id}/search/image`: a picture as the raw body (`application/octet-stream`, up to 15 MB; not
  stored); filters as query parameters. 413 when too large, 422 when not a picture.
- `PUT /api/projects/{id}/search/judgments` `{query, shot_id, relevant}`: mark a result good (`true`) or not
  (`false`), or take it back (`null`); stored with the query normalised (trimmed, lower case, single spaces).
- Errors: an empty query 422, a shot from another project 404.

## Ingest chain (`ingest`): validate, proxy, thumbnails, waveform, shots, keyframes, quality, audio_qc, transcribe, faces, embed_visual, embed_text, tags
- validate: ffprobe (by content, not extension): rational fps, VFR flag (avg vs nominal rate differ > 0.5 %),
  codecs, display size (rotation applied), timecode, colour tags. Corrupt or non-media files fail with a plain message.
- proxy: H.264 (+AAC), <= `proxy_max_height` (720), constant frame rate (the source's average rate, halved above 60), `+faststart`.
  Encoder order: NVENC, VideoToolbox, QSV if FFmpeg lists them, with automatic fallback to libx264 (CPU) if one fails
  at run time. Audio-only sources get an AAC `.m4a` proxy. Disk space is checked first.
- thumbnails (poster + strip) and waveform peaks are made from the proxy. Everything is written to a `.partial` file and
  renamed, so a crash never leaves a half-written artifact.
- shots: PySceneDetect on the proxy (`shot_detector` adaptive|content, `shot_threshold`, `shot_min_len_s`). A clip
  without cuts is one shot; audio-only files have none. Existing library, default thresholds, not tuned yet.
- keyframes: per shot, the sharpest frame near 1 to 3 anchor points (`keyframes_per_shot`), see DECISIONS D-038.
- quality: picture metrics per shot on the proxy, plus ffmpeg black/frozen-picture detection. audio_qc: loudness,
  silence and clipped samples on the original file's audio. Both cache measurements only; scores and flags are
  recomputed from the current `[quality]` settings on every run.
- transcribe: faster-whisper on the original file's audio (16 kHz mono), voice-activity detection first, word
  timings, language detection. Never downloads; without the model it records `model_missing` and retries on the next
  run. Its cache key depends on the source file and the `[transcribe]` settings only (`Stage.upstream`).
- faces: YuNet + SFace on the proxy at `[faces] sample_fps`, quality checks, tracking inside each shot; writes one
  crop per track and the track vectors under `faces/<media id>/`. Never downloads; without the models it records
  `model_missing` and retries on the next run. Its cache key depends on the shots and the `[faces]` settings other
  than the grouping ones, so changing `cluster_distance` regroups without decoding video.
- embed_visual: every keyframe through the picture model (CLIP or SigLIP, `[embed] visual_model`) plus an HSV colour
  histogram; vectors go to `embeddings`. embed_text: every transcript segment through the text model
  (`[embed] text_model`). tags: zero-shot scores per keyframe against the tag vocabulary; which tags are shown is
  decided when they are stored, from `ai/tag_thresholds.json`. None of the three downloads anything; without a model
  they record `model_missing` and retry on the next run. embed_visual hangs on the keyframes, embed_text on the
  transcript, tags on embed_visual (`Stage.upstream`).
- Stage cache for these stages is per project and re-validated against the files on disk (`Stage.scope_project`,
  `Stage.verify`); `Stage.persist` copies results onto the media row, also on a cache hit.

## Jobs and the worker
`cinemind serve` starts the API and one worker process (`--no-worker` to skip; `cinemind worker` runs it alone).
The worker polls `jobs`, runs the chain's stages in order, caches each stage, and writes events.
On startup it re-queues any job left `running` (assumes exactly one worker); finished stages come back from the
cache, so a killed job resumes at the stage that was interrupted (that stage restarts from its beginning).
Cancel is cooperative: stages call `ctx.check_cancelled()` and the runner checks between stages.
Retry keeps succeeded stages.
After an ingest job the worker groups the project's faces into actors, but only once no job of that project is
queued or running, so a large import is grouped once at its end.

## Static frontend
`cinemind serve` serves `frontend/dist`. Unknown extensionless non-`/api` paths return `index.html` (client-side routing deep links and reloads); missing files with an extension and unknown `/api` paths are real 404s.
