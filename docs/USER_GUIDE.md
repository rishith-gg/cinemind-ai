# User guide

Screenshots are in `docs/report/screens/` (taken from the real app on the user's footage).

1. **Start**: `uv run cinemind serve`, open http://127.0.0.1:8000. The dot at the top right shows live updates.
2. **Projects**: create a project; the switcher at the top chooses the current one.
3. **Library**: *Import* a folder inside an approved media root (`CINEMIND_MEDIA_ROOTS`) or upload files. Clips are
   referenced in place and never modified. Processing runs in the background with live progress: metadata, proxy,
   thumbnails, waveform, shots, keyframes, quality, audio checks, transcript, faces, picture and text vectors, tags.
   Filter and sort by quality; open a clip to see its player, shot strip, QC lane, transcript, tags and faces.
4. **Shots / Scenes**: shots grouped into scenes by picture and colour similarity, with the number behind every
   boundary. Split, join and rename scenes; mark shots Select / Reject / stars.
5. **Actors**: faces grouped into people. Rename, merge, split, answer "Same person?" questions.
6. **Transcripts**: set the project's spoken languages; read and search transcripts; uncertain lines are hidden by
   default.
7. **Search**: type what you are looking for ("person walking in forest"), or *Search by picture*. Each card shows
   why it ranked there (relevance, quality, your selects, person, scene, duplicate penalty); *Ranking weights*
   changes the weights for one search. ✓ / ✕ judge a result for the evaluation.
8. **Takes**: repeated takes of the same line or set-up, with the suggested best take and its signals (focus,
   exposure, audio, completeness, clean delivery). *Make best take* or *Not a take of these* to correct it.
9. **Script**: paste a screenplay (Fountain or "NAME: line"); every dialogue line gets its takes from the footage;
   choose a take or mark "not filmed"; *Build script assembly*.
10. **Timeline**: write a brief ("45 second sequence about friends at the waterfall"), optional length, order,
    person and scene; *Build rough cut*. In the editor drag to reorder, trim with the sliders, remove, swap with a
    suggestion (other takes first), play the cut. Every clip says why it was chosen. The result is always labelled
    "AI-assisted rough cut. Human review required."
11. **Export**: FCP7 XML (recommended for DaVinci Resolve), EDL, OTIO, plus SRT subtitles. In Resolve: *File →
    Import → Timeline*, choose the XML, keep the source clips where they are.
12. **Settings**: environment check (ffmpeg, models, hardware tier).
