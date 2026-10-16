const path = require("path");
const pptxgen = require("pptxgenjs");
const C = require("./content.js");
const HERE = __dirname;
const SCREENS = "/Volumes/externalssd/cinemind/docs/report/screens";
const FIG = path.join(HERE, "fig");

const NAVY = "14306E", ACCENT = "2563EB", INK = "1F2937", MUTED = "6B7280", LIGHT = "EEF2FF";
const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
pptx.title = C.title;

function frame(title, num) {
  const s = pptx.addSlide();
  s.background = { color: "FFFFFF" };
  s.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: 13.33, h: 0.9, fill: { color: NAVY } });
  s.addText(title, { x: 0.5, y: 0.12, w: 11.5, h: 0.66, fontSize: 26, bold: true, color: "FFFFFF", fontFace: "Calibri" });
  s.addText(`CineMind AI · BCSE306L · ${num}`, { x: 9.3, y: 7.05, w: 3.8, h: 0.3, fontSize: 10, color: MUTED, align: "right" });
  return s;
}
function bullets(s, items, opts = {}) {
  s.addText(items.map((t) => ({ text: t, options: { bullet: { indent: 18 }, paraSpaceAfter: 8 } })),
    { x: opts.x ?? 0.6, y: opts.y ?? 1.2, w: opts.w ?? 12.1, h: opts.h ?? 5.6, fontSize: opts.size ?? 18, color: INK, valign: "top", fontFace: "Calibri" });
}
const img = (s, file, x, y, w, h) => s.addImage({ path: file, x, y, w, h, sizing: { type: "contain", w, h } });

// 1 Title
let s = pptx.addSlide();
s.background = { color: "FFFFFF" };
s.addImage({ path: path.join(HERE, "vit_logo_dark.png"), x: 4.2, y: 0.4, w: 4.9, h: 1.45 });
s.addText("BCSE306L – Artificial Intelligence · Slot C1 + TC1", { x: 0.5, y: 2.0, w: 12.33, h: 0.4, fontSize: 16, color: MUTED, align: "center" });
s.addText("CineMind AI", { x: 0.5, y: 2.6, w: 12.33, h: 0.9, fontSize: 48, bold: true, color: NAVY, align: "center" });
s.addText("A local-first, explainable AI assistant for video pre-editing", { x: 0.5, y: 3.5, w: 12.33, h: 0.6, fontSize: 24, color: INK, align: "center" });
s.addText(C.members.map(([n, r]) => `${n}  (${r})`).join("     ·     "), { x: 0.5, y: 4.7, w: 12.33, h: 0.5, fontSize: 18, color: INK, align: "center" });
s.addText("School of Computer Science and Engineering · VIT · October 2026", { x: 0.5, y: 5.4, w: 12.33, h: 0.4, fontSize: 14, color: MUTED, align: "center" });

// 2 Problem
s = frame("The problem", 2);
bullets(s, [
  "A shoot produces hundreds of clips: repeated takes, mixed frame rates, soft or badly exposed shots, speech in several languages",
  "Before editing starts, someone must watch, log, discard, find each line's best take and build a first assembly: hours of manual work",
  "Existing AI help is fragmented: Premiere text editing, Resolve 20 IntelliScript (paid Studio), search plug-ins; often cloud-based and unexplained",
  "Research models solve single tasks (shots, scenes, cut plausibility, moment retrieval) on edited films, on GPUs",
  "Goal: organise, search, rank and assemble raw footage on the filmmaker's own laptop, and explain every decision",
]);

// 3 Objectives
s = frame("Objectives and principles", 3);
bullets(s, [
  "Turn an unorganised footage folder into a searchable, ranked library and an editable AI-assisted rough cut",
  "Export to DaVinci Resolve (FCP7 XML), EDL and OpenTimelineIO, so the human editor finishes the film",
  "Local-first: no cloud, no paid APIs, no internet while processing; runs on CPU (Apple M1, 8 GB)",
  "Non-destructive: source footage is never modified",
  "Explainable and honest: every tag, rank and cut stores its inputs; every reported number comes from an evaluation script",
], { w: 7.3 });
img(s, path.join(SCREENS, "03_library.png"), 8.1, 1.4, 4.9, 3.1);

// 4 Architecture
s = frame("System architecture", 4);
img(s, path.join(FIG, "fig1_architecture.png"), 0.6, 1.05, 12.1, 6.0);

// 5 Pipeline
s = frame("AI pipeline: existing models + our logic", 5);
s.addTable([
  [{ text: "Stage", options: { bold: true, fill: { color: LIGHT } } }, { text: "Model / library", options: { bold: true, fill: { color: LIGHT } } }, { text: "Our contribution", options: { bold: true, fill: { color: LIGHT } } }],
  ["Shots & keyframes", "PySceneDetect (adaptive)", "sharpest keyframes, false-cut reporting"],
  ["Technical quality", "OpenCV, EBU R128", "re-blur focus measure, calibrated flags"],
  ["Transcription", "faster-whisper (Whisper small)", "uncertainty marking, per-project languages"],
  ["Faces → actors", "YuNet + SFace", "quality filter, tracking, constrained clustering"],
  ["Embeddings & tags", "OpenCLIP / SigLIP, MiniLM", "thresholds calibrated to 0.9 precision"],
  ["Search & ranking", "SQLite FTS5 (BM25), FAISS", "RRF fusion, explained weighted rank, MMR"],
  ["Takes, script, rough cut", "difflib, OpenTimelineIO", "best-take signals, alignment, brief → timeline"],
], { x: 0.6, y: 1.25, w: 12.1, colW: [3.0, 4.0, 5.1], fontSize: 15, color: INK, border: { type: "solid", color: "CCCCCC", pt: 0.75 } });

// 6 Search & ranking
s = frame("Explainable hybrid search and ranking", 6);
bullets(s, [
  "Four lists: spoken words (BM25), labels, meaning of speech, picture",
  "Reciprocal Rank Fusion: score = Σ 1 / (60 + rank)",
  "Weighted rank: relevance, quality, selects, person, scene − duplicate penalty (MMR)",
  "Every card shows value × weight = contribution; what-if sliders",
  "Search by reference picture ('more like this')",
], { w: 5.2, size: 17 });
img(s, path.join(SCREENS, "14_search.png"), 6.0, 1.2, 7.0, 4.4);

// 7 Takes + script
s = frame("Takes and script alignment", 7);
bullets(s, [
  "Take groups: same words (≥ 0.6) or same picture (≥ 0.9) nearby; average linkage",
  "Best take = focus, exposure, audio, completeness, clean delivery (flubs, fillers, cut-off)",
  "Editor can overrule; corrections survive re-processing",
  "Script page: each screenplay line → up to 5 takes; never-filmed lines rejected → script-ordered assembly",
], { w: 5.2, size: 17 });
img(s, path.join(SCREENS, "08_takes.png"), 6.0, 1.2, 7.0, 4.4);

// 8 Rough cut
s = frame("AI-assisted rough cut → DaVinci Resolve", 8);
bullets(s, [
  "Brief: '45 second sequence about friends at the waterfall'",
  "Search + ranking → quality ≥ 0.5, ≥ 1.5 s → one take per group",
  "Trim to whole sentences (+0.25 s) or 6 s around the match; fit length ±10 %",
  "Drag, trim, swap (other takes first), preview; each clip explains why",
  "Export FCP7 XML / EDL / OTIO / SRT with reason markers; imported in Resolve 21.1",
], { w: 5.2, size: 17 });
img(s, path.join(SCREENS, "11_timeline_editor.png"), 6.0, 1.2, 7.0, 4.4);

// 9 Results 1
s = frame("Results: component accuracy (our pipeline, public data)", 9);
img(s, path.join(FIG, "fig3_wer.png"), 0.4, 1.1, 6.2, 2.9);
img(s, path.join(FIG, "fig4_faces.png"), 6.8, 1.1, 6.2, 2.9);
img(s, path.join(FIG, "fig5_tags.png"), 0.4, 4.1, 6.2, 3.0);
img(s, path.join(FIG, "fig2_quality.png"), 6.8, 4.1, 6.2, 3.0);

// 10 Results 2
s = frame("Results: search, script and rough cut", 10);
img(s, path.join(FIG, "fig6_search.png"), 0.4, 1.1, 6.2, 3.0);
img(s, path.join(FIG, "fig7_script.png"), 6.8, 1.1, 6.2, 3.0);
img(s, path.join(FIG, "fig8_roughcut.png"), 0.4, 4.15, 6.2, 2.85);
s.addText([
  { text: "Key numbers", options: { bold: true, breakLine: true } },
  { text: "WER 4.70 % (Whisper small, CPU)", options: { bullet: true, breakLine: true } },
  { text: "Actor grouping B-cubed F1 0.993 (LFW)", options: { bullet: true, breakLine: true } },
  { text: "Search nDCG@10 0.907, MRR 0.971", options: { bullet: true, breakLine: true } },
  { text: "Script: 83 % of transcribed lines found", options: { bullet: true, breakLine: true } },
  { text: "Rough cut in 0.2 s, within 10 % of length", options: { bullet: true, breakLine: true } },
  { text: "Search/take labels made with an AI assistant: indicative", options: { italic: true, color: MUTED } },
], { x: 7.0, y: 4.2, w: 6.0, h: 2.8, fontSize: 15, color: INK, valign: "top" });

// 11 Comparison
s = frame("Comparison with existing tools and research", 11);
const Y = "✓", N = "✗";
s.addTable([
  ["", "Local on CPU", "Search", "Rough cut", "Takes / script", "Explains", "NLE export"].map((t) => ({ text: t, options: { bold: true, fill: { color: LIGHT } } })),
  ["CineMind AI (ours)", Y, Y, Y, Y, Y, "XML / EDL / OTIO"],
  ["Premiere Text-Based Editing", "in Premiere", "transcript", "manual", N, N, "native"],
  ["Resolve 20 IntelliScript", "Studio (paid)", "limited", "from script", "script", N, "native"],
  ["Jumper", Y, Y, N, N, "partly", "plug-in"],
  ["CLIP4Clip / QVHighlights", "GPU", "text→video", N, N, N, N],
  ["Learning to Cut / AVE", "GPU", N, "cut scoring", N, N, N],
], { x: 0.6, y: 1.3, w: 12.1, colW: [3.1, 1.5, 1.5, 1.5, 1.6, 1.3, 1.6], fontSize: 15, color: INK, align: "center", border: { type: "solid", color: "CCCCCC", pt: 0.75 } });
s.addText("We do not beat specialised GPU models on their own benchmarks. What we add is the combination: local, explained, end-to-end to an editable timeline.",
  { x: 0.6, y: 5.6, w: 12.1, h: 0.9, fontSize: 16, italic: true, color: NAVY });

// 12 Limitations
s = frame("Limitations and future work", 12);
bullets(s, [
  "Dialogue features depend on speech recognition: noisy audio and Kannada are poorly transcribed by small Whisper",
  "Search and take labels were made with an AI assistant; user studies with real editors are next",
  "Our footage has few real retakes and no hand-marked cuts, so shot and take figures are sanity checks",
  "Thresholds of scenes, takes and ranking weights are conventions; learned re-weighting from selects/rejects is future work",
  "Future: word-level speech-aware trimming, speaker diarisation, multilingual models, desktop packaging",
]);

// 13 Team
s = frame("Team contributions (equal effort)", 13);
const TEAM = [
  ["Rishith Raj G (24BCE0175)", ["Backend architecture: FastAPI, SQLite, job worker, cached stages", "Ingest, proxies, shot detection, keyframes", "Export to FCP7 XML / EDL / OTIO; Resolve tests", "Speech: faster-whisper, script alignment", "Report: intro, methodology, approach"]],
  ["Hrishikesh Acharya (24BDS0231)", ["Technical quality metrics and calibration", "Faces → actors: YuNet/SFace, clustering, LFW evaluation", "CLIP/SigLIP and MiniLM embeddings, calibrated tags", "Scenes and take detection with best-take signals", "Report: datasets, results, gaps"]],
  ["Krish Singh (24BDS0235)", ["React + TypeScript user interface", "Hybrid search, RRF, explainable ranking, evaluation", "Rough-cut engine and timeline editor", "Playwright / Vitest tests", "Report: comparison, user manual, PPT, demo video"]],
];
TEAM.forEach(([name, items], i) => {
  const x = 0.5 + i * 4.2;
  s.addShape(pptx.ShapeType.roundRect, { x, y: 1.2, w: 4.0, h: 5.6, fill: { color: LIGHT }, line: { color: "C7D2FE" }, rectRadius: 0.1 });
  s.addText(name, { x: x + 0.15, y: 1.3, w: 3.7, h: 0.6, fontSize: 17, bold: true, color: NAVY });
  s.addText(items.map((t) => ({ text: t, options: { bullet: true, paraSpaceAfter: 8 } })),
    { x: x + 0.15, y: 2.0, w: 3.7, h: 4.6, fontSize: 15, color: INK, valign: "top" });
});

// 14 Thanks
s = pptx.addSlide();
s.background = { color: NAVY };
s.addText("Thank you", { x: 0.5, y: 2.4, w: 12.33, h: 1.0, fontSize: 48, bold: true, color: "FFFFFF", align: "center" });
s.addText("Not an auto-editor: an assistant that does the organising so the editor can do the editing.",
  { x: 0.5, y: 3.6, w: 12.33, h: 0.8, fontSize: 20, color: "E0E7FF", align: "center" });
s.addText("Demo · Source · Report: see the Appendix of the project document", { x: 0.5, y: 4.6, w: 12.33, h: 0.5, fontSize: 14, color: "C7D2FE", align: "center" });

pptx.writeFile({ fileName: "/Volumes/externalssd/cinemind/docs/report/CineMind_AI_Presentation.pptx" }).then((f) => console.log("written", f));
