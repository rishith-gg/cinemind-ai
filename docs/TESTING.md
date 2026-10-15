# Testing

## Automated
| What | Command |
|---|---|
| Everything except E2E (ruff, pyright, pytest, tsc, eslint, vitest) | `uv run python scripts/tasks.py check` |
| Backend only | `uv run pytest -q` |
| Frontend unit tests | `cd frontend && pnpm test` |
| Browser E2E against the real built app | `uv run python scripts/tasks.py e2e` |

Test footage is synthetic and generated on demand with ffmpeg (never committed). Ground truth that the tests rely on:
- `cuts.mp4` (backend) has cuts at exactly 2.0 s, 3.52 s and 6.0 s at 25 fps; shot detection must return those frames.
- `three_shots.mp4` (E2E) has cuts at 2.0 s and 4.0 s.
- Export round trip: each exported file is re-read with OpenTimelineIO's own adapters (`fcp_xml`, `cmx_3600`,
  `otio_json`) and every cut's name, source in, duration and record position must equal the timeline.
- Transcription: unit and API tests replace the speech model with a fixed fake (test code only) so they need no
  download; they check storage, word times, the keyword index, `jump_s`, cache behaviour and every "no text" state.
  One test (`-m model`, skipped unless the model is in `data/models/` and macOS `say` exists) runs the real model on
  a synthesised sentence with known words and on a pure tone that must give no speech. The E2E data folder has no
  model on purpose: it checks the "not downloaded" path in the real app.
- Faces and actors: unit and API tests replace the face models with a fixed fake (test code only) that returns
  made-up people at known places, so they need no download. They check the tracking rule, tracks ending at cuts,
  the grouping with "never the same person" and "always the same person" constraints for both methods, every
  correction, corrections surviving a rescan with other settings, a correction whose face is gone, the cache
  behaviour (including going back to earlier settings), ids from another project, a cancelled last job, a proxy
  that ends early, models that disappear after a good scan, every "no faces" state, faces seen too briefly being
  set aside until placed, and "same person?" answers (no keeps two people apart through a regrouping that would
  join them, yes merges). The grouping quality on real photos is measured by
  `eval/face_clusters.py`, not by a test. The E2E data folder has no face models on purpose.
- Embeddings, tags, scenes: tests replace the picture and text models with a fixed fake (test code only: picture
  vectors from a frame's mean colour, text vectors from a hash) and use a test thresholds file, so they need no
  download. They check vector rows per keyframe and segment, every tag status (`shown`, `below`, `disabled`,
  `not_evaluated`), new thresholds taking effect without a model run, reviews surviving reprocessing, the
  "no models" path, the index rebuilt from the database after its file was deleted and after a clip was removed,
  FAISS and numpy giving the same neighbours, scene grouping with its numbers, split / join / auto / rename kept
  through regrouping, and the image preparation against both preprocessing styles. One test (`-m model`, skipped
  without the downloaded models) runs the real CLIP and MiniLM: a red and a blue picture must match "red" and
  "blue" prompts, and two paraphrases must be closer than an unrelated sentence. Tag precision on labelled photos is
  measured by `eval/tag_calibration.py`, not by a test. The E2E data folder has no picture or text models: the E2E
  test edits scenes by hand and checks the "not downloaded" message on the clip page.
- Search: unit tests check the RRF arithmetic and weights, the label matching rule, the settings and the metrics
  (precision, reciprocal rank, nDCG) against their definitions. API tests with the stand-in models (on `cuts.mp4`,
  four shots, and a made-up transcript) check that a typed query fuses all four lists and explains each, that one
  list can run alone, that uncertain lines never match, every filter, "more like this", search by a dark-blue picture
  finding the dark-blue shot, judgments per normalised query, a missing model turning its list off with a message,
  the text-similarity floor, the evaluation script end to end, tied scores sharing a rank, picture sizes read from
  JPEG / PNG / WebP headers (TIFF refused), a time before or after every shot, a search leaving no write lock and a
  stale index rebuilt once and committed, a filter finding a shot beyond each list's depth, the speech filter
  following the user's tag review, small words and unnamed people not matching labels, other projects' shots and
  oversized or fake pictures refused, a double judgment replacing the first, and vectors of another model reported
  instead of hidden. How good search is on real footage is measured
  by `eval/search_eval.py`, not by a test. The E2E test searches by a file name (the E2E data folder has no models)
  and moves to the next clip with the N key.
- Ranking: tests on the same processed `cuts.mp4` project check that every result's final score is the sum of its
  breakdown, the duplicate penalty points at a shot placed higher, the same weights give the same order, quality
  alone sorts by quality and relevance alone keeps the fused order, invalid weights are refused, selects and stars
  rise with the selection weight, rejected shots disappear (and come back with "show rejected"), "selects only",
  marks on the Shots page, mark validation and the feedback log, and the person / scene signals. Frontend tests
  check the breakdown table, the mark buttons, the weight sliders sending new weights and the reset; the E2E test
  rejects a result and checks it is gone from the next search.
- Timecode: drop-frame conversion is checked against known values and round-tripped frame by frame across minute and
  ten-minute boundaries.

- Rough cut: unit tests check the brief rules (lengths in minutes, seconds, m:ss and words; orders; framing words;
  "a" not read as a length), every trim rule (too short, around the match, near the end, a limit, whole lines and
  closest neighbours, speech never shortened, a line past the shot edge, a very short line), the timeline size by
  orientation, and SRT placement (words inside the cut, pieces under 0.3 s dropped). API tests on the processed
  `cuts.mp4` project check that a brief builds a cut within the target ± 10 % in source order with a reason per
  clip, the spoken line kept whole and the uncertain one ignored, the request overriding the brief, a brief without
  subject using every shot except rejected and poor ones (with why), friendly errors, reorder / trim / remove /
  rename with validation, swap bookkeeping, and the exports (banner, one marker / `* WHY:` per clip, OTIO re-read,
  SRT with only the certain line, 422 without speech), and after review: NaN / Infinity and sub-frame clips refused,
  other timelines' items refused, "trimmed by you", removed clips returning as suggestions, swapping back, the
  emptied-timeline message, speech fitting a limit with fewer lines, brief phrases that are not lengths, a short whole
  subtitle line kept. Frontend tests check the edit helpers, the brief form, the "why" panel, swap and remove
  requests, a refused edit, a trim saved on release, and the player (an early-ending proxy cuts to the next clip,
  Play at the end starts over, only the shown clip reports errors). The E2E test builds a cut from "10 seconds, best first",
  trims with the keyboard (kept after reload), plays it, removes a clip and checks the exported XML.

## Manual: DaVinci Resolve import checklist (Phase 4)
Claude cannot run Resolve. This is done by hand; write the outcome in the results table and in `docs/PROGRESS.md`.
Tested so far: DaVinci Resolve 21.1 (free edition), macOS, FCP7 XML, on 2026-10-09 (results below).

Build the two test timelines on the Export page of the app:
- **A**: frame rate "Auto", "Leave out clips at other frame rates" ticked. One frame rate only: the clean case.
- **B**: frame rate "Auto", box not ticked. Mixed frame rates: the hard case, expected to be imperfect.

Ready-made files from the 2026-10-09 run on the user's footage (60 fps, 2160x3840; A = 10 cuts, 13048 frames;
B = 20 cuts, 21157 frames) are in `data/phase4-verify/projects/5be0ca7ef72a4dc991a04bbad682f352/exports/`:
`Resolve test A_71a3b4f9.{xml,edl,otio}` and `Resolve test B_f2a89543.{xml,edl,otio}`.

For each timeline, and for each of the three files (start with the FCP7 XML):
1. Create a NEW Resolve project. Before adding any media, set the project's timeline frame rate to the timeline's
   rate (shown on the Export page) and its resolution to the timeline's size.
2. Add the footage folder to the Media Pool.
3. Import the timeline file (File menu, Import, Timeline; wording may differ slightly between versions).
4. Check and note:
   - [ ] The import finishes without an error dialog (copy the exact text if there is one).
   - [ ] The number of cuts equals "cuts" on the Export page, in the same order.
   - [ ] Every clip is online (no "Media Offline"), linked to the original file in the footage folder.
   - [ ] The timeline starts at 01:00:00:00 and its total length matches the Export page.
   - [ ] Audio is present once (not doubled on a second track) and in sync; clips without sound leave a gap.
   - [ ] Frame check, for any three cuts: in Resolve, park the playhead on the first frame of the cut and look at
         the picture. In CineMind open the same clip, click that shot in the shot strip (the player jumps to the
         shot's first frame) and compare. The two pictures should be the same moment. Do the same for the last
         frame of the cut. This checks that a cut starts and ends where CineMind says, not a few frames off.
   - [ ] Where one source clip was split into several shots, playback across the cut is seamless (no repeated or
         missing frame).
   - [ ] (B only) Note for each clip at another frame rate whether its in and out points are right, early or late.

### Results
| Date | Resolve | Timeline | File | Result | Notes |
|---|---|---|---|---|---|
| 2026-10-09 | 21.1 free | A | FCP7 XML (first export) | Imported, no error. All clips online. | Stereo clips had their audio twice (A1 and A2): our file had one audio item per channel and Resolve reads each as the whole stereo audio. Fixed the same day (one audio item per cut); **re-check pending**. User also reported "in some the order of clips after splitting is reversed"; the file lists the pieces in source order (in points ascending), so which clip and what is reversed is **still to be pinned down**. Frame check not done. |
| 2026-10-09 | 21.1 free | B | FCP7 XML (first export) | Imported, no error. All clips online. | Same audio duplication. Mixed-rate clips imported; their in/out accuracy not checked yet. |
| 2026-10-09 | 21.1 free | A, B | FCP7 XML (after audio fix) | User: "everything is correct in DaVinci Resolve". | Audio no longer doubled; the earlier "reversed order" remark was not repeated. Which checklist items were looked at individually (frame check, mixed-rate in/out) was not stated. |
| | | A | EDL | not reported | |
| | | A | OTIO | not reported | |

## Manual: rough cut import checklist (Phase 11)
Claude cannot run Resolve; this is done by hand. On the Timeline page build a rough cut (for example "1-minute
sequence of people walking outdoors"), then on its page download the FCP7 XML and the SRT.
1. Import the XML as in the Phase 4 checklist (new project, timeline rate and size as shown on the page).
   - [ ] Imports without an error; the number of clips, their order and the total length match the page.
   - [ ] Each clip's first and last frame match its in and out point on the page (check two or three).
   - [ ] Markers: Resolve shows one timeline marker per clip ("Clip 1", "Clip 2", ...) with the reason as its note.
         If no markers appear, write that down: the cut itself is still usable.
2. Import the SRT onto the timeline (File, Import, Subtitle; then drag it to the timeline start if asked).
   - [ ] The subtitle lines appear under the clips where the words are spoken (the file counts from 00:00:00, the
         timeline starts at 01:00:00:00; note whether Resolve lines them up by itself).
3. Edit the cut in CineMind (move a clip, trim one, remove one), export again and re-import: the changes are there.

### Results (Phase 11)
| Date | Resolve | File | Result | Notes |
|---|---|---|---|---|
| | | FCP7 XML (rough cut, markers) | not yet tested | |
| | | SRT | not yet tested | |
