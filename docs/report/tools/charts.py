import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = sys.argv[1]
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "figure.dpi": 160})
BLUE, ORANGE, GREEN, GREY, RED = "#2563eb", "#ea580c", "#16a34a", "#6b7280", "#dc2626"

def save(fig, name):
    fig.tight_layout()
    fig.savefig(f"{OUT}/{name}.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)

def labels(ax, bars, fmt="{:.3f}"):
    for b in bars:
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.01, fmt.format(b.get_height()),
                ha="center", va="bottom", fontsize=8)

# Fig 2: quality flags
fig, ax = plt.subplots(figsize=(6.5, 3.2))
names = ["Out of focus", "Overexposed", "Underexposed"]
p, r, f = [0.994, 0.963, 0.965], [1.000, 0.945, 1.000], [0.997, 0.954, 0.982]
x = range(3); w = 0.25
labels(ax, ax.bar([i - w for i in x], p, w, label="Precision", color=BLUE))
labels(ax, ax.bar(list(x), r, w, label="Recall", color=ORANGE))
labels(ax, ax.bar([i + w for i in x], f, w, label="F1", color=GREEN))
ax.set_xticks(list(x), names); ax.set_ylim(0.8, 1.05); ax.set_ylabel("Score")
ax.set_title("Technical quality flags (synthetic degradations of 55 real frames)")
ax.legend(loc="lower right", fontsize=8)
save(fig, "fig2_quality")

# Fig 3: WER and speed as two panels (one axis each)
fig, (a1, a2) = plt.subplots(1, 2, figsize=(6.8, 2.9))
m = ["Whisper base", "Whisper small"]
for ax, vals, fmt, ttl, col in ((a1, [6.60, 4.70], "{:.2f} %", "Word error rate (%)", BLUE),
                                (a2, [0.104, 0.290], "{:.3f} s", "Seconds per second of audio", ORANGE)):
    bars = ax.bar(m, vals, 0.5, color=col)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v * 1.02, fmt.format(v), ha="center", va="bottom", fontsize=8)
    ax.set_title(ttl, fontsize=9); ax.set_ylim(0, max(vals) * 1.25)
fig.suptitle("Transcription on Mini LibriSpeech (1682 words), Apple M1 CPU", fontsize=10)
save(fig, "fig3_wer")

# Fig 4: face grouping
fig, ax = plt.subplots(figsize=(6.5, 3.0))
mets = ["Purity", "ARI", "NMI", "B³ P", "B³ R", "B³ F1"]
agg = [0.997, 0.991, 0.998, 0.995, 0.991, 0.993]; hdb = [0.985, 0.945, 0.984, 0.976, 0.935, 0.955]
x = range(len(mets)); w = 0.38
labels(ax, ax.bar([i - w/2 for i in x], agg, w, label="Agglomerative (ours, default)", color=BLUE))
labels(ax, ax.bar([i + w/2 for i in x], hdb, w, label="HDBSCAN", color=GREY))
ax.set_xticks(list(x), mets); ax.set_ylim(0.85, 1.04)
ax.set_title("Actor grouping on LFW held-out half (2298 faces, 409 people)"); ax.legend(fontsize=8, loc="lower left")
save(fig, "fig4_faces")

# Fig 5: tag precision
fig, ax = plt.subplots(figsize=(6.5, 3.2))
tags = ["indoor", "outdoor", "day", "night", "forest", "field", "temple", "office", "street*", "vehicle*"]
prec = [0.903, 0.905, 0.920, 0.923, 0.927, 1.000, 0.944, 0.966, 0.846, 0.825]
cols = [GREEN if t[-1] != "*" else RED for t in tags]
b = ax.bar(tags, prec, color=cols); labels(ax, b, "{:.2f}")
ax.axhline(0.85, color=GREY, ls="--", lw=1); ax.text(9.4, 0.855, "0.85 cut-off", fontsize=7, ha="right", color=GREY)
ax.set_ylim(0.7, 1.06); ax.set_ylabel("Held-out precision"); plt.xticks(rotation=30)
ax.set_title("Zero-shot tag precision (Places365 / CODaN). * = switched off")
save(fig, "fig5_tags")

# Fig 6: search ablation
fig, ax = plt.subplots(figsize=(6.8, 3.3))
cfg = ["Keyword", "Labels", "Text\nmeaning", "Picture", "Hybrid\n(RRF)", "Hybrid\n−picture", "Ranked\n(Phase 10)"]
nd = [0.000, 0.043, 0.000, 0.925, 0.907, 0.042, 0.881]; mrr = [0.000, 0.078, 0.000, 1.000, 0.971, 0.074, 0.961]
x = range(len(cfg)); w = 0.38
labels(ax, ax.bar([i - w/2 for i in x], nd, w, label="nDCG@10", color=BLUE), "{:.2f}")
labels(ax, ax.bar([i + w/2 for i in x], mrr, w, label="MRR", color=ORANGE), "{:.2f}")
ax.set_xticks(list(x), cfg, fontsize=8); ax.set_ylim(0, 1.15)
ax.set_title("Search on the user's footage: 17 test queries, 71 shots (judged with an AI assistant)"); ax.legend(fontsize=8)
save(fig, "fig6_search")

# Fig 7: script alignment
fig, ax = plt.subplots(figsize=(6.5, 3.0))
var = ["Words only", "Meaning only (default)", "Words + meaning"]
acc = [29/48, 29/48, 30/48]; heard = [20/24, 19/24, 20/24]; rej = [0.8, 0.9, 0.9]
x = range(3); w = 0.25
labels(ax, ax.bar([i - w for i in x], acc, w, label="Test accuracy (48 lines)", color=BLUE), "{:.2f}")
labels(ax, ax.bar(list(x), heard, w, label="Lines Whisper wrote, found", color=GREEN), "{:.2f}")
labels(ax, ax.bar([i + w for i in x], rej, w, label="Invented lines rejected", color=ORANGE), "{:.2f}")
ax.set_xticks(list(x), var); ax.set_ylim(0, 1.15); ax.legend(fontsize=7, loc="upper left", ncol=3)
ax.set_title("Script-to-footage alignment on Tears of Steel (test half)")
save(fig, "fig7_script")

# Fig 8: rough cut timing / length
fig, ax = plt.subplots(figsize=(6.5, 3.0))
briefs = ["1-min people\nwalking", "30 s water\n& beach", "2 min friends\ntalking", "45 s\n(no subject)"]
target = [60, 30, 120, 45]; got = [56.1, 31.1, 108.7, 41.8]; secs = [28.7, 0.1, 0.2, 0.0]
x = range(4); w = 0.38
ax.bar([i - w/2 for i in x], target, w, label="Target length (s)", color=GREY)
b = ax.bar([i + w/2 for i in x], got, w, label="Built cut length (s)", color=BLUE)
for bb, s in zip(b, secs): ax.text(bb.get_x() + w/2, bb.get_height() + 2, f"{s} s to build", ha="center", fontsize=7)
ax.set_xticks(list(x), briefs, fontsize=8); ax.set_ylim(0, 140); ax.legend(fontsize=8)
ax.set_title("AI-assisted rough cut from a brief (user's footage, M1 8 GB)")
save(fig, "fig8_roughcut")

# Fig 9: take sensitivity
fig, ax = plt.subplots(figsize=(6.0, 2.8))
pm = [0.85, 0.90, 0.95]; P = [0.111, 0.500, 1.000]; F = [0.200, 0.667, 1.000]
ax.plot(pm, P, "o-", color=BLUE, label="Pairwise precision"); ax.plot(pm, F, "s--", color=GREEN, label="Pairwise F1")
ax.plot(pm, [1, 1, 1], ":", color=ORANGE, label="Recall")
ax.set_xticks(pm); ax.set_xlabel("picture_min (default 0.90)"); ax.set_ylim(0, 1.1); ax.legend(fontsize=8)
ax.set_title("Take grouping sensitivity (76 shots, labels made with an AI assistant; not tuned)")
save(fig, "fig9_takes")

# Fig 1: architecture
fig, ax = plt.subplots(figsize=(10, 6.2)); ax.axis("off"); ax.set_xlim(0, 100); ax.set_ylim(0, 62)
def box(x, y, w, h, text, color, fs=8):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4", fc=color, ec="#1f2937", lw=0.8))
    ax.text(x + w/2, y + h/2, text, ha="center", va="center", fontsize=fs, wrap=True)
def arrow(x1, y1, x2, y2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="->", color="#374151", lw=1))
box(2, 50, 16, 8, "Raw footage\n(phone / camera clips)\nnever modified", "#fde68a")
box(24, 50, 22, 8, "Import & ingest\nffprobe metadata · SHA-256 hash\nproxy · thumbnails · waveform", "#bfdbfe")
box(52, 50, 20, 8, "Job queue (SQLite)\nworker process\ncached, resumable stages", "#e5e7eb")
box(78, 50, 20, 8, "React UI (browser)\nFastAPI on 127.0.0.1\nlive progress (SSE)", "#ddd6fe")
arrow(18, 54, 24, 54); arrow(46, 54, 52, 54); arrow(72, 54, 78, 54)
stages = [("Shot detection\nPySceneDetect\n+ keyframes", 2), ("Quality & audio QC\nfocus · exposure\nLUFS · clipping", 18),
          ("Transcription\nfaster-whisper\nword timings + VAD", 34), ("Faces → actors\nYuNet + SFace\nagglomerative", 50),
          ("Embeddings & tags\nCLIP / SigLIP · MiniLM\nzero-shot tags", 66), ("Scenes & takes\nsimilarity grouping\nbest-take signals", 82)]
for t, x in stages: box(x, 32, 15, 10, t, "#bbf7d0", 7.5)
arrow(62, 50, 62, 44)
ax.text(50, 45.5, "per-clip analysis stages (cached by content hash + params + model)", ha="center", fontsize=8, style="italic")
box(10, 16, 24, 9, "SQLite (WAL, FTS5)\n+ vector index (FAISS / numpy)\nall derived data under data/", "#e5e7eb")
box(40, 16, 24, 9, "Hybrid search + ranking\nBM25 · labels · text · picture\nRRF fusion · score breakdown · MMR", "#fecaca")
box(70, 16, 26, 9, "AI-assisted rough cut\nbrief → candidates → one take/group\n→ trim → order → timeline", "#fecaca")
arrow(50, 32, 22, 25); arrow(34, 20.5, 40, 20.5); arrow(64, 20.5, 70, 20.5)
box(70, 2, 26, 8, "Export: FCP7 XML · EDL · OTIO\nmarkers · SRT → DaVinci Resolve", "#fde68a")
box(40, 2, 24, 8, "Script page: screenplay →\ntakes per line → assembly", "#fecaca")
arrow(83, 16, 83, 10); arrow(52, 16, 52, 10); arrow(64, 6, 70, 6)
box(4, 2, 30, 8, "Human editor: selects / rejects, picks takes,\nedits timeline (feedback stored, explainable)", "#ddd6fe")
arrow(34, 6, 40, 6)
ax.set_title("Fig. 1  CineMind AI system architecture and process flow", fontsize=11)
save(fig, "fig1_architecture")
print("ok")
