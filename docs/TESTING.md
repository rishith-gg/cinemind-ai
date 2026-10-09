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
- Timecode: drop-frame conversion is checked against known values and round-tripped frame by frame across minute and
  ten-minute boundaries.

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
| | | A | FCP7 XML (after audio fix) | not run yet | |
| | | A | EDL | not reported | |
| | | A | OTIO | not reported | |
