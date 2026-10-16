const fs = require("fs");
const path = require("path");
const d = require("docx");
const C = require("./content.js");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, ImageRun, Table, TableRow, TableCell,
  WidthType, ShadingType, LevelFormat, PageBreak, BorderStyle, Footer, PageNumber, TableOfContents,
} = d;

const HERE = __dirname;
const REPO = "/Volumes/externalssd/cinemind";
const SCREENS = path.join(REPO, "docs/report/screens");
const LINKS = JSON.parse(fs.readFileSync(path.join(HERE, "links.json"), "utf8"));
const W = 9026; // A4 text width in DXA with 1" margins

const p = (text, opts = {}) =>
  new Paragraph({ spacing: { after: 120, line: 300 }, alignment: opts.align ?? AlignmentType.JUSTIFIED, ...opts.para,
    children: Array.isArray(text) ? text : [new TextRun({ text, ...opts.run })] });
const runs = (parts) => parts.map(([t, b]) => new TextRun({ text: t, bold: !!b }));
const h1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 240, after: 120 }, children: [new TextRun(t)] });
const h2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 180, after: 100 }, children: [new TextRun(t)] });
const bullet = (text, level = 0) => new Paragraph({ numbering: { reference: "bul", level }, spacing: { after: 60 },
  children: Array.isArray(text) ? text : [new TextRun(text)] });
const caption = (t) => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
  children: [new TextRun({ text: t, italics: true, size: 18 })] });
const pageBreak = () => new Paragraph({ children: [new PageBreak()] });

function image(file, widthPx, type = "png") {
  const buf = fs.readFileSync(file);
  // read PNG size
  const w = buf.readUInt32BE(16), hgt = buf.readUInt32BE(20);
  const height = Math.round((widthPx * hgt) / w);
  return new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 60 },
    children: [new ImageRun({ type, data: buf, transformation: { width: widthPx, height } })] });
}

const border = { style: BorderStyle.SINGLE, size: 4, color: "999999" };
const borders = { top: border, bottom: border, left: border, right: border };
function cell(content, width, opts = {}) {
  const kids = (Array.isArray(content) ? content : [content]).map((c) =>
    typeof c === "string" ? new Paragraph({ spacing: { after: 40 }, children: [new TextRun({ text: c, size: 17, bold: opts.bold })] }) : c);
  return new TableCell({ borders, width: { size: width, type: WidthType.DXA }, margins: { top: 60, bottom: 60, left: 80, right: 80 },
    shading: opts.fill ? { fill: opts.fill, type: ShadingType.CLEAR, color: "auto" } : undefined, children: kids });
}
const smallBullet = (t) => new Paragraph({ numbering: { reference: "bul", level: 0 }, spacing: { after: 30 }, children: [new TextRun({ text: t, size: 17 })] });
function table(widths, header, rows) {
  return new Table({ width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA }, columnWidths: widths,
    rows: [new TableRow({ tableHeader: true, children: header.map((h, i) => cell(h, widths[i], { bold: true, fill: "D9E2F3" })) }),
      ...rows.map((r) => new TableRow({ children: r.map((c, i) => cell(c, widths[i])) }))] });
}
const multiline = (s) => s.split("\n").map((l) => new Paragraph({ spacing: { after: 20 }, children: [new TextRun({ text: l, size: 17 })] }));

const body = [];
// ---------- [1] Title page
body.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 },
  children: [new ImageRun({ type: "png", data: fs.readFileSync(path.join(HERE, "vit_logo_dark.png")), transformation: { width: 420, height: 124 } })] }));
const center = (t, size, bold = false, after = 120) => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after },
  children: [new TextRun({ text: t, size, bold })] });
body.push(center(LINKS.school, 28, true, 360));
body.push(center("BCSE306L – Artificial Intelligence", 26, true));
body.push(center("Slot: C1 + TC1  ·  Project Document (Digital Assignment)", 22, false, 480));
body.push(center("Project Title", 22, false, 80));
body.push(center(C.title, 34, true, 600));
body.push(center("Submitted by", 22, false, 160));
body.push(new Table({ width: { size: 6000, type: WidthType.DXA }, columnWidths: [3600, 2400], alignment: AlignmentType.CENTER,
  rows: [new TableRow({ children: [cell("Name", 3600, { bold: true, fill: "D9E2F3" }), cell("Registration No.", 2400, { bold: true, fill: "D9E2F3" })] }),
    ...C.members.map(([n, r]) => new TableRow({ children: [cell(n, 3600), cell(r, 2400)] }))] }));
body.push(center("", 22, false, 480));
body.push(center(LINKS.faculty ? `Under the guidance of ${LINKS.faculty}` : "", 22));
body.push(center("October 2026", 22));
body.push(pageBreak());

// Contents
body.push(new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: "Contents", bold: true, size: 30, color: "1F3864" })] }));
body.push(new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-1" }));
body.push(p("(Right-click the table and choose Update Field in Word if page numbers are missing.)", { run: { italics: true, size: 16 } }));
body.push(pageBreak());

// ---------- [2] Structured abstract
body.push(h1("1. Structured Abstract"));
for (const [k, v] of C.abstract) body.push(p(runs([[`${k}: `, true], [v]])));
body.push(p(runs([["Keywords: ", true], ["video pre-editing, multimodal retrieval, speech recognition, face clustering, explainable ranking, rough cut, local-first AI"]])));

// ---------- [3] Introduction
body.push(h1("2. Introduction"));
body.push(h2("2.1 Background and Problem Definition"));
body.push(p(C.intro[0].replace(/^Background and problem definition\. /, "")));
body.push(h2("2.2 Objective and Methodology"));
body.push(p(C.intro[1].replace(/^Objective and methodology\. /, "")));
body.push(p(C.intro[2]));
body.push(h2("2.3 Results, Outcomes and Analysis"));
body.push(p(C.intro[3].replace(/^Results and analysis\. /, "")));

// ---------- [4] Related work
body.push(h1("3. Background / Related Work"));
body.push(p("Each team member studied five research articles (2020 onwards) and two or three tools or reports. The six paragraphs below discuss them by theme with their flaws; Table 1 summarises the research articles in the prescribed template and Table 2 the tools."));
C.litParas.forEach((t) => body.push(p(t)));
body.push(caption("Table 1. Literature survey of research articles (2020 onwards)"));
const lw = [500, 1900, 2700, 1900, 2026];
body.push(table(lw, ["Sl#", "Articles", "Work Done", "Dataset", "Gaps / Limitations"],
  C.litTable.map((r, i) => [String(i + 1), multiline(r[0]), r[1].map(smallBullet), r[2], r[3].map(smallBullet)])));
body.push(caption(""));
body.push(caption("Table 2. Tools, blogs and reports studied"));
body.push(table([2600, 3400, 3026], ["Tool / report", "What it does", "Gaps / Limitations"], C.toolTable));

// ---------- [5] Gaps
body.push(h1("4. Summary of Limitations / Gaps"));
C.gaps.forEach((g, i) => body.push(bullet(runs([[`G${i + 1}. `, true], [g]]))));

// ---------- [6] Contributions
body.push(h1("5. Primary Contributions of the Project"));
C.contributions.forEach(([t, v]) => body.push(bullet(runs([[t + ": ", true], [v]]))));

// ---------- [7] Individual contributions
body.push(h1("6. Individual Contributions"));
body.push(p("All three members contributed equally in effort. The work was divided by area as below; design reviews, testing on our footage and the final report were done together."));
for (const [name, items] of C.individual) {
  body.push(h2(name));
  items.forEach((t) => body.push(bullet(t)));
}

// ---------- [8] Tools
body.push(h1("7. Tools and Technologies Used"));
body.push(h2("7.1 Hardware Requirements"));
body.push(table([2800, 6226], ["Item", "Specification"], C.hardware));
body.push(caption("Table 3. Hardware"));
body.push(h2("7.2 Software Requirements"));
body.push(table([2400, 6626], ["Layer", "Software"], C.software));
body.push(caption("Table 4. Software stack"));

// ---------- [9] Methodology
body.push(h1("8. Methodology Used"));
C.methods.forEach(([t, v]) => { body.push(h2(t)); body.push(p(v)); });

// ---------- [10] Dataset
body.push(h1("9. Dataset Used"));
body.push(p("CineMind analyses the user's own footage, which needs no training data; datasets are used to evaluate and calibrate each AI component. All public datasets were downloaded once by the scripts in eval/ into a git-ignored folder and are used through the application's own code."));
body.push(table([2300, 2900, 3826], ["Dataset (source)", "Used for", "Properties"], [
  ["Team footage (own recording)", "End-to-end runs, search, takes, rough cut", "25 clips, 532 s, 2.23 GB; phone and stock video; H.264 and HEVC; 1080p–4K, portrait and landscape; 24–120 fps (2 variable frame rate); English, Kannada and Hindi speech; 76 shots, 158 keyframes, 31 transcript segments, 475 faces, 15 actors, 72 scenes"],
  ["Mini LibriSpeech dev-clean-2 (openslr.org/31, CC BY 4.0)", "Word error rate of transcription", "Read English audiobook speech, 16 kHz FLAC with reference transcripts; fixed random sample of 1,682 words"],
  ["Labeled Faces in the Wild (vis-www.cs.umass.edu/lfw)", "Actor grouping purity, ARI, NMI, B-cubed", "13,233 face photos of 5,749 people; we used people with ≥ 2 photos, split into a tuning half (2,295 photos / 412 people) and held-out half (2,307 / 411)"],
  ["Places365 validation (places2.csail.mit.edu)", "Place and indoor/outdoor tag thresholds", "36,500 scene photos, 365 categories (100 each); mapped to our tags"],
  ["CODaN (Common Objects Day and Night)", "Day / night tag thresholds", "Object crops captured in daylight and in low light; 1,250 + 1,250 held-out images"],
  ["Tears of Steel (Blender Foundation, CC BY 3.0)", "Script alignment accuracy", "12-minute live-action short film (734 s) with English subtitles used as the script; split into development and test halves (48 test lines)"],
]));
body.push(caption("Table 5. Datasets"));
body.push(p("Sample of the team footage (metadata read by ffprobe; every column is stored per clip):"));
const sample = [
  ["IMG_0867.MOV", "90.1", "2160×3840", "HEVC / AAC", "60.00", "No", "519.6"],
  ["IMG_4405.MOV", "18.6", "3840×2160", "H.264 / AAC", "24.00", "No", "79.8"],
  ["43307CA1-…D043.mov", "7.5", "1920×1080", "HEVC / AAC", "119.39", "Yes", "20.6"],
  ["Timeline One.mov", "12.5", "3240×2160", "H.264 / AAC", "30.00", "No", "74.1"],
  ["VID_20260527_…314.MP4", "6.3", "1080×1920", "H.264 / AAC", "55.17", "Yes", "13.3"],
  ["5977460-uhd_…25fps.mp4", "13.0", "3840×2160", "H.264 / none", "25.00", "No", "34.4"],
];
body.push(table([2300, 900, 1250, 1400, 900, 1000, 1276], ["File", "Duration (s)", "Resolution", "Video / audio codec", "Frame rate", "Variable rate", "Size (MB)"], sample));
body.push(caption("Table 6. Sample records of the footage dataset"));
body.push(p("Characteristics: duration and size vary by two orders of magnitude; portrait (2160×3840) and landscape clips are mixed; frame rates range from 24 to 119.39 fps, and two clips have a variable frame rate (average and base rate differ by more than 0.5 %), which the exporter must handle with rational rates. One stock clip has no audio track. Speech is sparse: 5 of 76 shots have three or more clearly transcribed words, because most clips are music, water or crowd noise or Kannada speech, which the small Whisper model cannot write reliably (it is marked 'detect only')."));

// ---------- [11] Proposed approach
body.push(h1("10. Proposed Approach"));
body.push(image(path.join(HERE, "fig/fig1_architecture.png"), 600));
body.push(caption("Fig. 1. System architecture and process flow of CineMind AI"));
C.approachSteps.forEach((s, i) => body.push(bullet(runs([[`Step ${i + 1}. `, true], [s]]))));

// ---------- [12] Results
body.push(h1("11. Result Analysis and Discussion"));
body.push(p("All figures below were produced by scripts in the project's eval/ folder on an Apple M1 (8 GB) CPU and are recorded with their settings in docs/EVALUATION.md. Where relevance or take labels were produced with an AI assistant (Claude) rather than by independent viewers, this is stated."));
const fig = (file, cap, text) => { body.push(image(path.join(HERE, "fig", file), 520)); body.push(caption(cap)); body.push(p(text)); };
fig("fig2_quality.png", "Fig. 2. Precision, recall and F1 of the technical quality flags",
  "The focus flag (re-blur ratio with a Laplacian floor) reaches F1 0.997, better than plain Laplacian variance (0.985, Table 7). Exposure flags reach 0.954–0.982. The labels come from synthetic blur and exposure changes of 55 real frames, so these numbers are an upper bound. Fog, water and plain walls still read as soft in real footage.");
body.push(table([3600, 1400, 1400, 1300, 1326], ["Flag / rule", "Precision", "Recall", "F1", "Accuracy"], [
  ["Out of focus (used: blur > 0.547 or sharpness < 5.32)", "0.994", "1.000", "0.997", "0.995"],
  ["Out of focus, Laplacian variance alone (baseline)", "0.976", "0.994", "0.985", "0.977"],
  ["Overexposed", "0.963", "0.945", "0.954", "0.955"],
  ["Underexposed", "0.965", "1.000", "0.982", "0.982"],
]));
body.push(caption("Table 7. Quality flag calibration (5-fold grouped by clip)"));
fig("fig3_wer.png", "Fig. 3. Word error rate and speed of the two Whisper sizes on Mini LibriSpeech",
  "Whisper small lowers WER from 6.60 % to 4.70 % (left) at almost three times the processing time (right) (0.29 s per second of audio, still about 3.4× faster than real time on CPU), so small is the default for the lite tier. On the team's noisy field audio, the uncertainty rule hid the hallucinated lines, but some fluent text that passes the model's own limits remains.");
fig("fig4_faces.png", "Fig. 4. Actor grouping quality on LFW (held-out half)",
  "Average-linkage agglomerative clustering at distance 0.60 (chosen on the tuning half) gives 410 groups for 409 people, with B-cubed F1 0.993, ahead of HDBSCAN (0.955), which splits more people. LFW photos are frontal and well lit, so footage is harder. On our clips, setting aside faces seen in only one frame reduced 27 'actors' to 14.");
fig("fig5_tags.png", "Fig. 5. Held-out precision of the zero-shot tags",
  "Thresholds were set at 0.9 precision on the tuning half. Eight tags keep held-out precision of 0.90–1.00, while six tags such as 'street' (0.85) and 'inside a vehicle' (0.83) were switched off rather than shown wrongly. Recall is low for rare places (forest 0.41), so tags favour being right over being complete.");
fig("fig6_search.png", "Fig. 6. Search ablation on the team's footage (nDCG@10 and MRR)",
  "With 17 picture-oriented test queries, the picture list alone reaches nDCG@10 0.925 and MRR 1.0. The four-list fusion keeps almost all of that (0.907 / 0.971) while still answering spoken-word queries, and removing the picture list collapses quality (0.042). The explainable ranking with quality and duplicate penalty costs a little nDCG (0.881), because binary judgements cannot credit the extra variety. The relevance judgements were made with an AI assistant (Claude) from keyframes, not by independent viewers, so the numbers are indicative.");
body.push(table([3800, 1300, 1300, 1300, 1326], ["Configuration", "P@5", "P@10", "nDCG@10", "MRR"], [
  ["Keyword (BM25)", "0.000", "0.000", "0.000", "0.000"], ["Labels", "0.047", "0.024", "0.043", "0.078"],
  ["Meaning of speech", "0.000", "0.000", "0.000", "0.000"], ["Picture", "0.588", "0.376", "0.925", "1.000"],
  ["Hybrid (RRF, all four)", "0.600", "0.376", "0.907", "0.971"], ["Hybrid without picture", "0.047", "0.024", "0.042", "0.074"],
  ["Ranked (weights, MMR)", "0.565", "—", "0.881", "0.961"],
]));
body.push(caption("Table 8. Search evaluation (test queries)"));
fig("fig7_script.png", "Fig. 7. Script-to-footage alignment on Tears of Steel (test half)",
  "About 60 % of all script lines are placed correctly (29–30 of 48). Among lines that Whisper actually transcribed, 79–83 % are found, and 8–9 of 10 invented 'not filmed' lines are rejected. The missing lines (14 of 38 never transcribed) show that speech recognition, not the matcher, limits this feature. The 95 % intervals of the three variants overlap.");
fig("fig8_roughcut.png", "Fig. 8. Rough cuts built from briefs on the team's footage",
  "Every cut lands within 10 % of the requested length (56.1 s for 60 s, 108.7 s for 120 s) because speech clips keep whole sentences. The first brief takes 28.7 s while the models load, and later briefs take 0.0–0.2 s. This measures speed and length only. Whether the chosen clips suit the brief is left to the editor.");
fig("fig9_takes.png", "Fig. 9. Take grouping on 76 shots: sensitivity to the picture limit",
  "With the default limits the system found the one labelled repeat (recall 1.0) and one false pair, a continuous shot split by a false cut (precision 0.5, B-cubed F1 0.993). Raising the picture limit to 0.95 removes the false pair, and lowering it to 0.85 groups unrelated neighbours (precision 0.11). The footage contains almost no retakes, so this is a sanity check and the defaults were not tuned on it.");
body.push(p("Discussion. Three lessons stand out. First, for visual queries a calibrated picture embedding is the strongest single signal, and fusion protects against its blind spots (spoken words, names) at little cost. Second, speech recognition quality on field audio limits every dialogue feature (script alignment, speech-aware trimming, take grouping by words), so marking uncertain text is essential. Third, calibrating thresholds on labelled data and switching off unreliable outputs costs some recall but keeps the editor's trust. Exporting through FCP7 XML worked in DaVinci Resolve 21.1 (verified by hand), and the reason attached to each clip makes the AI-assisted rough cut reviewable."));

// ---------- [13] Comparative analysis
body.push(h1("12. Comparative Analysis"));
body.push(p("Table 9 compares CineMind with the surveyed systems on scope and method. Table 10 places our measured figures next to those reported in the literature. The datasets differ, so the numbers show the same order of magnitude rather than a head-to-head ranking."));
body.push(table([2000, 1300, 1150, 1150, 1150, 1100, 1176], ["System", "Runs locally on CPU", "Search", "Rough cut / assembly", "Takes / script", "Explains decisions", "NLE export"], [
  ["CineMind AI (ours)", "Yes (M1, 8 GB)", "Text, speech, picture", "Yes, from a brief", "Yes, both", "Yes, every score", "FCP7 XML, EDL, OTIO"],
  ["Premiere Text-Based Editing [16]", "Inside Premiere", "Transcript", "Manual via text", "No", "No", "Native only"],
  ["Resolve 20 IntelliScript [17]", "Resolve Studio (paid)", "Limited", "From a script", "Script only", "No", "Native only"],
  ["Jumper [18]", "Yes", "Text, speech, similar", "No", "No", "Partly", "Plug-in only"],
  ["CLIP4Clip [5] / QVHighlights [14]", "GPU", "Text→video", "No", "No", "No", "No"],
  ["Learning to Cut [12] / AVE [11]", "GPU", "No", "Cut scoring / benchmark", "No", "No", "No"],
]));
body.push(caption("Table 9. Functional comparison with surveyed tools and research"));
body.push(table([2400, 2600, 4026], ["Component", "Literature (reported, own dataset)", "CineMind (measured through our pipeline)"], [
  ["Speech recognition", "Whisper: robust zero-shot WER near supervised systems on LibriSpeech [1]", "Whisper small via faster-whisper: 4.70 % WER on Mini LibriSpeech, 0.29 s per audio second on CPU"],
  ["Word timestamps", "WhisperX adds forced alignment, 12× faster batching [2]", "Built-in VAD + word timings; uncertain lines hidden"],
  ["Face detection / grouping", "RetinaFace SOTA on WIDER FACE (GPU) [6]; YuNet millisecond-level [7]", "YuNet + SFace on CPU: B-cubed F1 0.993 on LFW held-out"],
  ["Zero-shot visual tags", "CLIP / SigLIP zero-shot transfer, uncalibrated scores [3], [4]", "Calibrated thresholds: 0.90–1.00 precision on 8 enabled tags"],
  ["Text→video retrieval", "CLIP4Clip state-of-the-art on MSR-VTT with fine-tuning [5]", "No fine-tuning: nDCG@10 0.907, MRR 0.971 on our footage (judged with an AI assistant)"],
  ["Scenes", "LGSS multimodal model on MovieScenes [10]", "Transparent similarity rule plus editor corrections (not evaluated against labels)"],
  ["Script assembly", "IntelliScript (closed, no published accuracy) [17]", "83 % of transcribed lines found; 90 % of invented lines rejected (Tears of Steel)"],
]));
body.push(caption("Table 10. Reported literature results versus CineMind measurements"));
body.push(p("Inference: CineMind does not beat specialised GPU models on their own benchmarks and does not try to. What it adds is the combination: comparable component quality on a CPU laptop, calibrated and explained outputs, and a complete path from raw clips to an editable timeline in a free NLE. That combination is absent from both the research systems, which cover one task each, and the commercial tools, which are closed or locked to one editor."));

// ---------- [14] User manual
body.push(h1("13. User Manual"));
body.push(p("Start the application with `uv run cinemind serve` and open http://127.0.0.1:8000. The screenshots below were taken from the running application on the team's footage."));
const shots = [
  ["01_dashboard.png", "Dashboard", "Footage statistics of the current project: clips, shots, scenes, actors, speech, low-quality shots, take groups, your marks and timelines; processing state, the distribution of technical quality scores with the quality flags, footage formats, speech per language, and suggested next steps."],
  ["03_library.png", "Library", "Import a footage folder (referenced in place, never modified) and follow processing live. Filter and sort clips by technical quality."],
  ["04_clip.png", "Clip page", "Proxy player with the shot strip, the QC lane of quality flags, the waveform, the transcript with word timings, tags and faces."],
  ["05_shots_scenes.png", "Shots / Scenes", "Shots grouped into scenes, with the similarity behind each boundary. Split, join and rename scenes, and select or reject shots."],
  ["06_actors.png", "Actors", "Faces grouped into people. Rename, merge and split groups, and answer 'Same person?' questions."],
  ["07_transcripts.png", "Transcripts", "Spoken languages per project, the transcript of every clip and keyword search over all of them."],
  ["14_search.png", "Search", "Type a query or search by picture. Each card shows the score breakdown, and 'Ranking weights' changes the weights for one search."],
  ["08_takes.png", "Takes", "Repeated takes with the suggested best take and its signals. Make another take the best, or take a shot out of the group."],
  ["09_script.png", "Script", "Paste a screenplay. Every dialogue line gets its takes, and 'Build script assembly' creates a timeline."],
  ["10_timeline.png", "Timeline", "Write a brief and optionally set length, order, person and scene, then build an AI-assisted rough cut."],
  ["11_timeline_editor.png", "Timeline editor", "Reorder by drag-and-drop, trim, remove, swap with suggestions (other takes first) and play the cut. Every clip shows why it was chosen."],
  ["12_export.png", "Export", "Export FCP7 XML (for DaVinci Resolve), EDL, OTIO and SRT. In Resolve choose File → Import → Timeline."],
];
shots.forEach(([f, t, txt], i) => {
  body.push(h2(`13.${i + 1} ${t}`));
  body.push(p(txt));
  body.push(image(path.join(SCREENS, f), 560));
  body.push(caption(`Fig. ${10 + i}. ${t} page`));
});

// ---------- [15] References
body.push(h1("14. References"));
const refs = [
  "Radford, Alec, et al. \"Robust Speech Recognition via Large-Scale Weak Supervision.\" Proceedings of the 40th International Conference on Machine Learning, PMLR, vol. 202, 2023, pp. 28492–28518.",
  "Bain, Max, et al. \"WhisperX: Time-Accurate Speech Transcription of Long-Form Audio.\" Proceedings of Interspeech 2023, ISCA, 2023.",
  "Radford, Alec, et al. \"Learning Transferable Visual Models from Natural Language Supervision.\" Proceedings of the 38th International Conference on Machine Learning, PMLR, vol. 139, 2021, pp. 8748–8763.",
  "Zhai, Xiaohua, et al. \"Sigmoid Loss for Language Image Pre-Training.\" Proceedings of the IEEE/CVF International Conference on Computer Vision (ICCV), 2023, pp. 11975–11986.",
  "Luo, Huaishao, et al. \"CLIP4Clip: An Empirical Study of CLIP for End to End Video Clip Retrieval and Captioning.\" Neurocomputing, vol. 508, Elsevier, 2022.",
  "Deng, Jiankang, et al. \"RetinaFace: Single-Shot Multi-Level Face Localisation in the Wild.\" Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2020, pp. 5203–5212.",
  "Wu, Wei, Hanyang Peng, and Shiqi Yu. \"YuNet: A Tiny Millisecond-Level Face Detector.\" Machine Intelligence Research, vol. 20, no. 5, Springer, 2023, pp. 656–665.",
  "Souček, Tomáš, and Jakub Lokoč. \"TransNet V2: An Effective Deep Network Architecture for Fast Shot Transition Detection.\" arXiv preprint arXiv:2008.04838, 2020.",
  "Huang, Qingqiu, et al. \"MovieNet: A Holistic Dataset for Movie Understanding.\" Computer Vision – ECCV 2020, Springer, 2020.",
  "Rao, Anyi, et al. \"A Local-to-Global Approach to Multi-Modal Movie Scene Segmentation.\" Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR), 2020, pp. 10146–10155.",
  "Argaw, Dawit Mureja, et al. \"The Anatomy of Video Editing: A Dataset and Benchmark Suite for AI-Assisted Video Editing.\" Computer Vision – ECCV 2022, Springer, 2022, pp. 201–218.",
  "Pardo, Alejandro, et al. \"Learning to Cut by Watching Movies.\" Proceedings of the IEEE/CVF International Conference on Computer Vision (ICCV), 2021, pp. 6858–6868.",
  "Shen, Yaojie, et al. \"AutoTransition: Learning to Recommend Video Transition Effects.\" Computer Vision – ECCV 2022, Springer, 2022, pp. 285–300.",
  "Lei, Jie, Tamara L. Berg, and Mohit Bansal. \"Detecting Moments and Highlights in Videos via Natural Language Queries.\" Advances in Neural Information Processing Systems (NeurIPS), vol. 34, 2021.",
  "Wang, Wenhui, et al. \"MiniLM: Deep Self-Attention Distillation for Task-Agnostic Compression of Pre-Trained Transformers.\" Advances in Neural Information Processing Systems (NeurIPS), vol. 33, 2020.",
  "Adobe. \"NAB 2023: Introducing Text-Based Editing in Premiere Pro, Properties Panel in After Effects, and Much More.\" Adobe Blog, 13 Apr. 2023, blog.adobe.com/en/publish/2023/04/13/nab-2023-introducing-text-based-editing-premiere-pro-properties-panel-after-effects-more.",
  "\"Blackmagic Introduces DaVinci Resolve 20.\" ProVideo Coalition, 2025, www.provideocoalition.com/blackmagic-introduces-davinci-resolve-20/.",
  "\"Review: AI-Driven Video Search with Jumper.\" ProVideo Coalition, 2024, www.provideocoalition.com/review-ai-driven-video-search-with-jumper/.",
  "Castellano, Brandon. PySceneDetect: Video Scene Cut Detection and Analysis Tool. 2024, www.scenedetect.com.",
  "Academy Software Foundation. OpenTimelineIO: Open Source API and Interchange Format for Editorial Timeline Information. 2024, opentimeline.io.",
  "Cormack, Gordon V., Charles L. A. Clarke, and Stefan Büttcher. \"Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods.\" Proceedings of the 32nd International ACM SIGIR Conference, 2009, pp. 758–759.",
  "SYSTRAN. faster-whisper: Faster Whisper Transcription with CTranslate2. GitHub, 2024, github.com/SYSTRAN/faster-whisper.",
];
refs.forEach((r, i) => body.push(new Paragraph({ spacing: { after: 80 }, indent: { left: 567, hanging: 567 },
  children: [new TextRun({ text: `[${i + 1}]\t${r}` })] })));

// ---------- [16] Appendix
body.push(h1("15. Appendix"));
body.push(bullet(runs([["a) Presentation (PPT): ", true], [LINKS.ppt]])));
body.push(bullet(runs([["b) Pre-recorded demonstration video: ", true], [LINKS.video]])));
body.push(bullet(runs([["c) Source code and steps to execute: ", true], [LINKS.repo + " (README.md, section 'Run it'; full guide in docs/USER_GUIDE.md)"]])));
body.push(h2("Steps to execute"));
["git clone <repository> cinemind && cd cinemind", "uv sync  and  (cd frontend && pnpm install)", "uv run cinemind doctor  (checks ffmpeg, Python, Node, RAM, GPU)",
  "uv run cinemind models pull  (downloads models once)", "Set CINEMIND_MEDIA_ROOTS in .env to the footage folder",
  "uv run python scripts/tasks.py build-ui", "uv run cinemind serve  → open http://127.0.0.1:8000"].forEach((s, i) =>
  body.push(new Paragraph({ numbering: { reference: "num", level: 0 }, spacing: { after: 40 }, children: [new TextRun({ text: s, font: "Consolas", size: 18 })] })));

const doc = new Document({
  creator: "CineMind team", title: C.title,
  styles: {
    default: { document: { run: { font: "Calibri", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 30, bold: true, color: "1F3864" }, paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 24, bold: true, color: "2F5496" }, paragraph: { spacing: { before: 180, after: 80 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [
    { reference: "bul", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 360, hanging: 240 } } } }] },
    { reference: "num", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 360, hanging: 300 } } } }] },
  ] },
  features: { updateFields: true },
  sections: [{
    properties: { page: { margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [
      new TextRun({ text: "BCSE306L – CineMind AI  ·  Page ", size: 16 }), new TextRun({ children: [PageNumber.CURRENT], size: 16 })] })] }) },
    children: body,
  }],
});
Packer.toBuffer(doc).then((buf) => {
  const out = path.join(REPO, "docs/report/CineMind_AI_Project_Report.docx");
  fs.writeFileSync(out, buf);
  console.log("written", out);
});
