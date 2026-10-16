# Demo video script (about 6–8 minutes)

Record the screen (macOS: Shift-Cmd-5) with the app running (`uv run cinemind serve`) and a project already
processed, so nothing has to wait. Speak the lines in quotes or paraphrase them.

| # | Time | Show | Say |
|---|---|---|---|
| 1 | 0:00 | Title slide | "CineMind AI: local-first, AI-assisted pre-editing. Raw footage in, an editable rough cut in DaVinci Resolve out. Everything runs on this laptop." |
| 2 | 0:20 | Terminal: `uv run cinemind doctor` | "It checks ffmpeg, memory and GPU and picks a model tier. This M1 with 8 GB gets the lite tier; no NVIDIA GPU needed." |
| 3 | 0:40 | Projects → new project → Library → Import folder | "We point it at a footage folder. Clips are referenced in place, never modified." |
| 4 | 1:00 | Library with live progress, then a clip page | "Each clip goes through cached stages: proxy, shots, keyframes, quality, transcript, faces, embeddings, tags. Here is the shot strip, the quality lane and the transcript with word timings." |
| 5 | 1:45 | Shots / Scenes | "Shots are grouped into scenes by picture and colour similarity, and every boundary shows its numbers. I can split, join and rename." |
| 6 | 2:10 | Actors | "Faces are grouped into people with YuNet and SFace. I rename them; it asks me when two people look alike." |
| 7 | 2:35 | Search: "person walking in forest" | "Hybrid search fuses spoken words, labels, meaning of speech and picture with Reciprocal Rank Fusion. Every card explains its score." Open *Ranking weights*, move the quality slider. |
| 8 | 3:20 | Search by picture (drop a frame) | "Search by a reference image: mood-board matching." |
| 9 | 3:40 | Takes | "Repeated takes are grouped; the best take is suggested from focus, exposure, audio, completeness and flubs, and I can overrule it." |
| 10 | 4:10 | Script: paste the park scene | "A screenplay is aligned to the transcripts: each line gets its takes; an invented line is rejected. Build the script assembly." |
| 11 | 4:50 | Timeline: brief "45 second sequence about friends at the waterfall" | "From one sentence it builds an AI-assisted rough cut: search, quality filter, one take per group, trim to whole sentences, fit the length. Every clip says why." |
| 12 | 5:30 | Timeline editor: drag, trim, swap, play | "The editor stays in control: reorder, trim, swap with suggestions, preview." |
| 13 | 6:00 | Export → FCP7 XML; Resolve: File → Import → Timeline | "The timeline opens in DaVinci Resolve with markers explaining each clip, ready to finish." |
| 14 | 6:40 | EVALUATION.md / report charts | "Every number we report comes from a script in eval/: WER 4.7 %, face grouping F1 0.99, search nDCG@10 0.91, script alignment 0.83 of transcribed lines." |
| 15 | 7:10 | Closing slide | "Not an auto-editor: an assistant that does the organising so the editor can do the editing." |
