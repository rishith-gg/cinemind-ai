"""Thresholds for the zero-shot tags, set and checked on labelled public photos.

It calls the same code the app uses (`embedder.embed_images`, `tagger.score`), so the figures
describe that code on single photos. Limits are listed at the end of this text.

  uv run python eval/tag_calibration.py fetch
      Download into data/eval/ (setup step; needs internet):
      - Places365 validation set, 256 px (525 MB; 36,500 photos, 50 for each of 365 scene
        categories, with the authors' indoor/outdoor label per category). Research and
        education use (http://places2.csail.mit.edu). Checksums from torchvision's loader.
      - CODaN test sets, day and night (111 MB; 2,500 + 2,500 photos of ten everyday objects;
        day photos from COCO and ImageNet, night photos from ExDark). Research use
        (https://github.com/Attila94/CODaN). Checksums recorded at first download.
  uv run python eval/tag_calibration.py run [--model clip-vit-b32] [--per-class 50] [--install]
      Writes eval/results/tag_calibration_<model>_<date>.txt and .json. With --install the
      thresholds are copied into backend/src/cinemind/ai/tag_thresholds.json, which the app reads.

What is labelled where:
  indoor / outdoor and the place tags: Places365 (category and its indoor/outdoor label).
  day / night (low light): CODaN.
  shot size: no open labelled set was found, so these tags stay "not evaluated" and hidden.

Design: each set is split in two halves (every other photo of each category). A tag's threshold
is the lowest score at which the first half reaches TARGET_PRECISION among the photos at or above
it; every reported figure comes from the second half, which the choice never saw. A tag is
switched off when the second half's precision is under ENABLE_MIN or it has fewer than MIN_SHOWN
photos above the threshold.

Limits: precision depends on how common a tag is. On these sets a place tag is true for a few
photos in a thousand (2 of 365 categories for "beach or coast"); on footage shot at a beach it is
far more common, so precision there would be higher, on footage with none of it lower. Places365
photos are web photos, CODaN night photos are low-light crops of objects, indoor ones included;
neither is phone video. The indoor/outdoor labels are per category and some are debatable.
"""

# numpy/sklearn are partly typed.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

import argparse
import hashlib
import inspect
import json
import platform
import subprocess
import sys
import tarfile
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from sklearn.metrics import average_precision_score

from cinemind.ai import embedder, tagger
from cinemind.core.config import REPO_ROOT, get_settings
from cinemind.core.embed_config import VISUAL_MODELS
from cinemind.core.hardware import detect_hardware
from cinemind.pipeline import tag_stage

EVAL_DIR = REPO_ROOT / "data" / "eval"
PLACES_DIR = EVAL_DIR / "places365"
CODAN_DIR = EVAL_DIR / "codan"
PLACES_BASE = "https://data.csail.mit.edu/places/places365/"
PLACES_FILES = {  # file -> md5 (torchvision/datasets/places365.py)
    "val_256.tar": "e27b17d8d44f4af9a78502beb927f808",
    "filelist_places365-standard.tar": "35a0585fee1fa656440f3ab298f8479c",
}
CODAN_COMMIT = "e12a9f89a42a94832ec89bd87fe2f6025e51f68c"
CODAN_BASE = f"https://raw.githubusercontent.com/Attila94/CODaN/{CODAN_COMMIT}/data/"
CODAN_FILES = {  # file -> sha256, recorded at the first download on 2026-10-14 (none published)
    "codan_test_day.tar.bz2": "795bfb193d265f882c59ddac7b38aa59555209c39fc497ebe98f71b22a8395bf",
    "codan_test_night.tar.bz2": "f3099a6481e91de6fe3560423f4cbdf6ea7f129c8e5b8f5afba0a302186aca80",
}
TARGET_PRECISION = 0.9
ENABLE_MIN = 0.85
MIN_SHOWN = 10
IMAGES = {".jpg", ".jpeg", ".png"}  # CODaN mixes all three, in either case
THRESHOLD_FILE = REPO_ROOT / "backend" / "src" / "cinemind" / "ai" / "tag_thresholds.json"


def _download(url: str, target: Path) -> None:
    cmd = ["curl", "--fail", "--location", "--silent", "--show-error", "-o", str(target), url]
    subprocess.run(cmd, check=True, timeout=7200)  # noqa: S603


def _digest(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _fetch_set(
    folder: Path, base: str, files: dict[str, str | None], algo: str, done: Callable[[], bool]
) -> None:
    if done():
        print(f"already there: {folder}")
        return
    folder.mkdir(parents=True, exist_ok=True)
    for name, expected in files.items():
        archive = folder / name
        print(f"downloading {base}{name} ...")
        _download(base + name, archive)
        got = _digest(archive, algo)
        if expected is None:
            print(f"  {algo} {got} (no published checksum; recorded here)")
        elif got != expected:
            archive.unlink()
            sys.exit(f"{name} does not match its checksum; nothing was unpacked. Try again.")
        with tarfile.open(archive) as tar:
            tar.extractall(folder, filter="data")
        archive.unlink()
    print(f"ready: {folder}")


def fetch() -> None:
    _fetch_set(
        PLACES_DIR,
        PLACES_BASE,
        dict(PLACES_FILES),
        "md5",
        lambda: (PLACES_DIR / "places365_val.txt").is_file() and (PLACES_DIR / "val_256").is_dir(),
    )
    _fetch_set(
        CODAN_DIR,
        CODAN_BASE,
        dict(CODAN_FILES),
        "sha256",
        lambda: (CODAN_DIR / "test_night").is_dir(),
    )


# --- data -------------------------------------------------------------------------------------


def places_items(per_class: int) -> list[tuple[Path, str, int]]:
    """(photo, category, half): the first `per_class` photos of each category by file name,
    alternating between the halves."""
    names = [name for name, _ in tagger.places()]
    by_class: dict[int, list[str]] = {}
    for line in (PLACES_DIR / "places365_val.txt").read_text().split("\n"):
        if line.strip():
            file, label = line.split()
            by_class.setdefault(int(label), []).append(file)
    items: list[tuple[Path, str, int]] = []
    for label, files in sorted(by_class.items()):
        for i, file in enumerate(sorted(files)[:per_class]):
            items.append((PLACES_DIR / "val_256" / file, names[label], i % 2))
    return items


def _photos(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGES)


def codan_items() -> list[tuple[Path, str, int]]:
    """(photo, 'day' | 'night', half), alternating by file name within each class folder."""
    items: list[tuple[Path, str, int]] = []
    for split, label in (("test_day", "day"), ("test_night", "night")):
        folders = sorted({p.parent for p in (CODAN_DIR / split).rglob("*") if p.is_file()})
        for folder in folders:
            for i, photo in enumerate(_photos(folder)):
                items.append((photo, label, i % 2))
    return items


def embed_all(model: str, paths: list[Path], batch: int) -> Any:
    settings = get_settings()
    spec = VISUAL_MODELS[model]
    out: list[Any] = []
    for start in range(0, len(paths), batch):
        frames = [cv2.imread(str(p)) for p in paths[start : start + batch]]
        missing = [
            str(p) for p, f in zip(paths[start : start + batch], frames, strict=True) if f is None
        ]
        if missing:
            sys.exit(f"unreadable photos: {missing[:3]}")
        out.append(embedder.embed_images(spec, settings, frames))
        if start // batch % 20 == 0:
            print(f"  embedded {start + len(frames)} / {len(paths)}", flush=True)
    return np.concatenate(out)


def cached_vectors(model: str, paths: list[Path], batch: int) -> Any:
    """Photo vectors, kept in data/eval/ so a re-run with other thresholds needs no model run.
    The cache is keyed by model revision, image preparation code and the exact photo list."""
    spec = VISUAL_MODELS[model]
    basis = json.dumps(
        [spec.revision, embedder.engine_version(), inspect.getsource(embedder.VisualModel.prepare)]
        + [str(p.relative_to(EVAL_DIR)) for p in paths]
    )
    path = EVAL_DIR / "cache" / f"{model}-{hashlib.sha256(basis.encode()).hexdigest()[:16]}.npy"
    if path.is_file():
        print(f"  reusing photo vectors {path.relative_to(REPO_ROOT)}")
        return np.load(path)
    vectors = embed_all(model, paths, batch)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, vectors)
    return vectors


# --- thresholds -------------------------------------------------------------------------------


def choose_threshold(scores: Any, truth: Any) -> float | None:
    """Lowest score whose photos at or above it reach TARGET_PRECISION (first half only)."""
    order = np.argsort(-scores)
    hits = np.cumsum(truth[order])
    shown = np.arange(1, len(order) + 1)
    precision = hits / shown
    ok = np.where((precision >= TARGET_PRECISION) & (shown >= MIN_SHOWN))[0]
    if len(ok) == 0:
        return None
    return float(scores[order][ok.max()])


def wilson(hits: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(float(centre - half), 3), round(float(centre + half), 3)]


def evaluate(name: str, scores: Any, truth: Any, half: Any, dataset: str) -> dict[str, Any]:
    tune, test = half == 0, half == 1
    threshold = choose_threshold(scores[tune], truth[tune])
    floor = tagger.threshold_floor(name)
    if threshold is not None and threshold < floor:
        threshold = floor  # the app never shows both tags of a two-way group (see tagger)
    result: dict[str, Any] = {
        "dataset": dataset,
        "positives_tuning": int(truth[tune].sum()),
        "positives_heldout": int(truth[test].sum()),
        "photos_heldout": int(test.sum()),
        "average_precision_heldout": round(
            float(average_precision_score(truth[test], scores[test])), 4
        )
        if truth[test].any()
        else None,
        "threshold": None if threshold is None else round(threshold, 4),
    }
    if threshold is None and int(truth[tune].sum()) < 2 * MIN_SHOWN:
        reason = f"too few labelled photos ({int(truth[tune].sum())} in the tuning half)"
        return {**result, "enabled": False, "reason": reason}
    if threshold is None:
        return {
            **result,
            "enabled": False,
            "reason": f"never reached {TARGET_PRECISION} precision on the tuning half",
        }
    shown = scores[test] >= threshold
    hits = int((shown & truth[test]).sum())
    n_shown = int(shown.sum())
    precision = hits / n_shown if n_shown else 0.0
    recall = hits / max(int(truth[test].sum()), 1)
    enabled = precision >= ENABLE_MIN and n_shown >= MIN_SHOWN
    reason = None
    if not enabled:
        reason = (
            f"held-out precision {precision:.3f} < {ENABLE_MIN}"
            if precision < ENABLE_MIN
            else f"only {n_shown} held-out photos above the threshold"
        )
    return {
        **result,
        "shown_heldout": n_shown,
        "precision": round(precision, 4),
        "precision_ci95": wilson(hits, n_shown),
        "recall": round(recall, 4),
        "enabled": enabled,
        "reason": reason,
    }


def run(model: str, per_class: int, install: bool) -> None:
    spec = VISUAL_MODELS[model]
    settings = get_settings()
    if not spec.ready(settings.models_path):
        sys.exit(f"The model '{model}' is not downloaded: uv run cinemind models pull visual")
    if not (PLACES_DIR / "places365_val.txt").is_file() or not (CODAN_DIR / "test_night").is_dir():
        sys.exit("The evaluation photos are missing: uv run python eval/tag_calibration.py fetch")
    places = places_items(per_class)
    codan = codan_items()
    started = time.perf_counter()
    batch = settings.embed.batch_size * 4
    vec_p = cached_vectors(model, [p for p, _, _ in places], batch)
    vec_c = cached_vectors(model, [p for p, _, _ in codan], batch)
    embed_s = time.perf_counter() - started
    tag_v, cat_v, scale = tag_stage.vocabulary(spec, settings)  # what the app uses
    s_p, cat_probs = tagger.score(vec_p, tag_v, cat_v, scale)
    s_c, _ = tagger.score(vec_c, tag_v, cat_v, scale)

    io = dict(tagger.places())
    cats = np.array([c for _, c, _ in places])
    half_p = np.array([h for _, _, h in places])
    half_c = np.array([h for _, _, h in codan])
    light = np.array([label for _, label, _ in codan])
    results: dict[str, Any] = {}
    results["indoor"] = evaluate(
        "indoor", s_p["indoor"], np.array([io[c] == 1 for c in cats]), half_p, "places365"
    )
    results["outdoor"] = evaluate(
        "outdoor", s_p["outdoor"], np.array([io[c] == 2 for c in cats]), half_p, "places365"
    )
    results["day"] = evaluate("day", s_c["day"], light == "day", half_c, "codan")
    results["night"] = evaluate("night", s_c["night"], light == "night", half_c, "codan")
    for tag in tagger.PLACE_TAGS:
        truth = np.isin(cats, tag.texts)
        results[tag.name] = evaluate(tag.name, s_p[tag.name], truth, half_p, "places365")
    top1 = float(
        (np.array([tagger.places()[i][0] for i in cat_probs.argmax(1)]) == cats)[half_p == 1].mean()
    )

    hw = detect_hardware()
    report = {
        "model": model,
        "revision": spec.revision,
        "calibration_key": tagger.calibration_key(spec),
        "vocabulary_version": tagger.VOCAB_VERSION,
        "date": date.today().isoformat(),
        "target_precision": TARGET_PRECISION,
        "enable_min": ENABLE_MIN,
        "min_shown": MIN_SHOWN,
        "photos": {"places365": len(places), "codan": len(codan)},
        "per_class": per_class,
        "places365_top1_heldout": round(top1, 4),
        "embed_seconds": round(embed_s, 1),
        "engine": embedder.engine_version(),
        "device": embedder.pick_device(settings.embed.device),
        "machine": f"{platform.system()} {hw.arch}, {hw.cpu_name}, {hw.ram_gb} GB RAM, "
        f"GPU {hw.gpu.kind}",
        "not_evaluated": [t.name for t in tagger.PROMPT_TAGS if t.group == "shot_size"],
        "tags": results,
    }
    out = REPO_ROOT / "eval" / "results" / f"tag_calibration_{model}_{report['date']}"
    out.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    out.with_suffix(".txt").write_text(text_report(report))
    print(text_report(report))
    print(f"wrote {out.relative_to(REPO_ROOT)}.txt/.json")
    if install:
        current = tagger.load_thresholds(THRESHOLD_FILE)
        models = current.get("models", {})
        keep = (
            "dataset",
            "threshold",
            "enabled",
            "reason",
            "precision",
            "precision_ci95",
            "recall",
            "shown_heldout",
            "positives_heldout",
        )
        models[report["calibration_key"]] = {
            "date": report["date"],
            "source": f"eval/results/{out.name}.json",
            "target_precision": TARGET_PRECISION,
            "tags": {name: {k: r.get(k) for k in keep} for name, r in results.items()},
        }
        THRESHOLD_FILE.write_text(json.dumps({"models": models}, indent=2, sort_keys=True) + "\n")
        print(f"installed thresholds into {THRESHOLD_FILE.relative_to(REPO_ROOT)}")


def _dash(value: Any) -> Any:
    return "-" if value is None else value


def text_report(r: dict[str, Any]) -> str:
    photos = r["photos"]
    lines = [
        f"Tag calibration, {r['date']}: {r['model']} ({r['revision'][:12]}), "
        f"vocabulary v{r['vocabulary_version']}",
        f"Photos: Places365 {photos['places365']} ({r['per_class']} per category), "
        f"CODaN {photos['codan']}; threshold set on one half, figures from the other half.",
        f"Target precision {r['target_precision']}; a tag is switched off below "
        f"{r['enable_min']} held-out precision or under {r['min_shown']} held-out photos shown.",
        f"Places365 365-way top-1 accuracy (held-out half): {r['places365_top1_heldout']:.3f}",
        f"Machine: {r['machine']}; {r['engine']} on {r['device']}; "
        f"embedding took {r['embed_seconds']} s.",
        "",
        f"{'tag':<12} {'set':<10} {'thresh':>7} {'shown':>6} {'prec':>6} {'95% CI':>11} "
        f"{'recall':>7} {'AP':>6} {'pos':>5}  state",
    ]
    for name, t in r["tags"].items():
        ci = t.get("precision_ci95")
        state = "on" if t["enabled"] else f"off ({t['reason']})"
        lines.append(
            f"{name:<12} {t['dataset']:<10} {_dash(t['threshold']):>7} "
            f"{_dash(t.get('shown_heldout')):>6} {_dash(t.get('precision')):>6} "
            f"{(f'{ci[0]:.2f}-{ci[1]:.2f}' if ci else '-'):>11} {_dash(t.get('recall')):>7} "
            f"{_dash(t['average_precision_heldout']):>6} {t['positives_heldout']:>5}  {state}"
        )
    lines.append("")
    lines.append(
        f"Not evaluated (no labelled set; hidden in the app): {', '.join(r['not_evaluated'])}"
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch")
    run_p = sub.add_parser("run")
    run_p.add_argument("--model", default="clip-vit-b32", choices=sorted(VISUAL_MODELS))
    run_p.add_argument("--per-class", type=int, default=50)
    run_p.add_argument("--install", action="store_true")
    args = parser.parse_args()
    if args.command == "fetch":
        fetch()
    else:
        run(args.model, args.per_class, args.install)


if __name__ == "__main__":
    main()
