# Demonstration video script: Google Meet, three presenters (about 14 minutes)

**Who does what**
- **Rishith Raj G**: hosts the Meet and shares this Mac's screen for the **whole** recording. The app only runs on
  this Mac, so he does every click. He presents the opening and the ingest pipeline.
- **Hrishikesh Acharya**: presents the vision part (scenes, actors, transcripts, takes) and the accuracy results.
  He talks while Rishith clicks, using the cues in *[brackets]*.
- **Krish Singh**: presents search, script, rough cut, export, and the closing slides. He also talks while Rishith
  clicks.
- Everyone keeps their camera on and stays muted when not speaking.

Deck: `docs/report/CineMind_AI_Presentation.pptx` (14 slides). Slides 6–8 are **backup** slides for the features
shown live. Use them only if the app has a problem.

## Before you start (Rishith, 15 minutes before)
1. Start the demo project: `CINEMIND_DATA_DIR=data/phase12b-verify CINEMIND_PORT=8766 uv run cinemind serve`, then
   open http://127.0.0.1:8766 and check that the project switcher shows **Phase 12B verify**. (You can rename it to
   "CineMind demo" on the Projects page.) **Stop the other CineMind server** on port 8000 first: two servers are too
   much for 8 GB RAM.
2. Open the deck in PowerPoint and open these browser tabs in order: Dashboard, Library, Shots / Scenes, Actors,
   Transcripts, Takes, Search, Script, Timeline, Export.
3. In Terminal, have `uv run cinemind doctor` typed but not yet run.
4. Open DaVinci Resolve with an empty project. On the Export page, download the FCP7 XML of the rough cut "45 second
   sequence about friends at the waterfall" and save it to the Desktop.
5. Close other apps, turn on Do Not Disturb, and hide notifications. Zoom the browser to 110 % so it is readable on
   the recording.
6. **Recording**: in Meet, click *Activities → Recording → Start recording*. This needs a Google Workspace account;
   VIT student accounts usually have it, personal Gmail accounts do not. If it is not available, record this Mac's
   screen with OBS Studio, capturing both "Display" and "Desktop audio" so the other two voices are recorded.
7. Do one full practice run.

## Script

| # | Time | Speaker | Screen (Rishith clicks) | What to say |
|---|---|---|---|---|
| 1 | 0:00 | Rishith | Slide 1 (title) | "Hello, we are Rishith, Hrishikesh and Krish. Our AI project is **CineMind AI**, a local-first, explainable assistant for video pre-editing. It takes raw footage and gives you an editable rough cut in DaVinci Resolve, and everything runs on this laptop." |
| 2 | 0:30 | Rishith | Slide 2 (problem) | "A shoot produces hundreds of clips: repeated takes, mixed frame rates, blurry shots and several languages. An editor spends hours just logging footage before any creative work starts. The AI tools that help today are cloud-based, paid, tied to one editor, and don't explain their choices." |
| 3 | 1:15 | Rishith | Slide 3 (objectives) | "Our goal is to organise, search, rank and assemble raw footage on the filmmaker's own computer, without modifying the source files, and to explain every decision. It is not an auto-editor: the human editor stays in charge." |
| 4 | 1:45 | Rishith | Slide 4 (architecture) | "Here is the architecture: a FastAPI server bound to localhost, one background worker, SQLite with full-text search, and a React interface. Every clip goes through cached, resumable analysis stages, and the results feed search, ranking, takes, script alignment and the rough cut, which exports to DaVinci Resolve." |
| 5 | 2:30 | Rishith | Slide 5 (pipeline table) | "We separate existing models from our own logic: PySceneDetect, faster-whisper, YuNet with SFace, CLIP and MiniLM are the models; the calibration, fusion, ranking, take logic and rough-cut engine are ours." |
| 6 | 3:00 | Rishith | Terminal: run `uv run cinemind doctor` | "The doctor checks FFmpeg, Python, memory and GPU and picks a model tier. This M1 with 8 GB gets the lite tier, and no NVIDIA GPU is needed." |
| 7 | 3:20 | Rishith | Browser: **Dashboard** | "The dashboard shows our 25 clips: almost nine minutes, 2.2 GB, H.264 and HEVC, portrait and landscape, from 24 to 120 fps. Everything was detected automatically: 76 shots, 72 scenes, 15 actors, the quality score distribution and the quality flags." |
| 8 | 4:00 | Rishith | **Library**, then open *Timeline One.mov* | "In the Library, footage is referenced in place and never modified. Each clip gets a proxy, thumbnails and a waveform. On the clip page you can see the shot strip, the quality lane with its flags, and the transcript with word timings. Clicking a word jumps to that moment." *[click a transcript word]* |
| 9 | 5:00 | Hrishikesh | **Shots / Scenes** | "I worked on the vision side. Shots are grouped into scenes by picture and colour similarity, and every boundary shows the numbers behind it, so the editor can split, join or rename a scene." *[hover over a similarity note]* |
| 10 | 5:30 | Hrishikesh | **Actors** | "Faces are detected with YuNet and embedded with SFace, then grouped into people with constrained agglomerative clustering. Two faces in the same frame can never be the same person. When two groups look alike, the app asks 'Same person?'." |
| 11 | 6:05 | Hrishikesh | **Transcripts** | "Speech is transcribed by Whisper with voice-activity detection. Lines the model is unsure about are hidden, because on noisy audio Whisper can write text nobody said. Kannada is detected but marked 'detect only', because the small model writes it poorly." |
| 12 | 6:35 | Hrishikesh | **Takes** | "Takes: shots that repeat the same words or the same set-up are grouped. The best take is suggested from focus, exposure, audio, how complete the line is and whether it has flubs, and every number is shown. The editor can choose another take or say 'not a take of these'." |
| 13 | 7:15 | Hrishikesh | Slide 9 (results 1) | "Results through our own pipeline: Whisper small gives 4.7 % word error rate on LibriSpeech; actor grouping reaches B-cubed F1 0.993 on LFW; our tags reach 0.90 to 1.00 precision because we calibrated thresholds and switched off six unreliable tags; quality flags have F1 between 0.95 and 0.997." |
| 14 | 8:00 | Krish | **Search**: type *person walking in forest*, press Enter | "I built the interface, search and the rough cut. Search fuses four lists, spoken words, labels, meaning of speech and picture, with Reciprocal Rank Fusion. Each card shows exactly why it ranked there: relevance, quality, your selects, and a duplicate penalty." *[open "Ranking weights", move the Quality slider]* "Changing a weight re-ranks the results immediately." |
| 15 | 9:00 | Krish | **Search by picture**: choose a keyframe image | "You can also search with a reference image, to find shots that look like this one." |
| 16 | 9:20 | Krish | **Script** (the park scene) | "On the Script page, a screenplay is matched to the transcripts. Each line gets its takes with scores, and the line we made up, 'The train leaves at noon', is correctly marked as not filmed. One click builds a script-ordered assembly." |
| 17 | 10:00 | Krish | **Timeline**: the waterfall rough cut, open the editor | "From one sentence, '45 second sequence about friends at the waterfall', the engine searched, removed low-quality shots, kept one take per group, trimmed to whole sentences and fitted the length. It is labelled 'AI-assisted rough cut, human review required', and each clip says why it was chosen." *[drag a clip, open a swap list, press play]* |
| 18 | 11:00 | Krish | **Export**, then DaVinci Resolve: *File → Import → Timeline*, choose the XML | "We export FCP7 XML, EDL, OTIO and subtitles. Here it opens in DaVinci Resolve with the original clips and a marker explaining each cut, ready for the editor to finish." |
| 19 | 11:45 | Krish | Slide 10 (results 2) | "On our own footage, search reached nDCG@10 of 0.907 and MRR of 0.971; the relevance labels were made with an AI assistant, so treat these as indicative. Script alignment found 83 % of the lines Whisper transcribed, and rough cuts are built in 0.2 seconds within 10 % of the requested length." |
| 20 | 12:20 | Krish | Slide 11 (comparison) | "Compared with Premiere's text-based editing, Resolve's IntelliScript, Jumper and the research models, we don't beat specialised GPU models on their own benchmarks. What we add is the combination: local, free, explained, and end-to-end to an editable timeline." |
| 21 | 12:50 | Krish | Slide 12 (limitations) | "Limitations: dialogue features depend on speech recognition; our footage has few real retakes; some thresholds are conventions. Next we want word-level trimming, speaker labels and multilingual models." |
| 22 | 13:20 | Rishith | Slide 13 (team) | "We split the work equally: I built the backend, ingest, export and speech; Hrishikesh the vision, faces, tags and takes; Krish the interface, search, ranking and rough cut." |
| 23 | 13:40 | Rishith | Slide 14 (thank you) | "CineMind is not an auto-editor. It does the organising so the editor can do the editing. Thank you." Stop the recording. |

## After recording
1. Find the Meet recording in Rishith's Google Drive, in the *Meet Recordings* folder. Trim it if needed.
2. Share it with *Anyone with the link → Viewer*, or upload it to YouTube as **Unlisted**.
3. Put the link in `docs/report/tools/links.json` (`"video"`), together with the PPT link (`"ppt"`), then rebuild
   the report (see `docs/report/tools/README.md`), or ask Claude to do it.

## If something goes wrong live
- If a page does not load, show the backup slide instead: Search → slide 6, Takes and Script → slide 7, Timeline
  → slide 8. Then continue.
- If the app is slow, the first search after a restart takes about 25 seconds while the models load. Run one search
  before you start recording.
