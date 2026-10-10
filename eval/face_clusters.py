"""How well the app groups faces into people, on a labelled set of face photos.

It calls the same code the app uses (YuNet + SFace through `FaceEngine` with the `[faces]`
checks, then `face_cluster.cluster`), so the numbers describe that code on single photos; the
limits of that are listed at the end of this text.

  uv run python eval/face_clusters.py fetch
      Download Labeled Faces in the Wild (173 MB, web photos of public figures collected for
      research, http://vis-www.cs.umass.edu/lfw/) into data/eval/lfw. Setup step; needs internet.
  uv run python eval/face_clusters.py run <folder> [--min-photos 5] [--max-photos 20]
                                                  [--singles 200]
      <folder> holds one sub-folder per person with that person's photos (LFW's layout; your own
      labelled crops work the same way). Writes eval/results/face_clusters_<folder>_<date>.txt
      and .json.

Design: people are split in two halves by name order (every other person). The grouping
distance is chosen on the first half (best B-cubed F1) and every reported figure for it comes
from the second half, which the choice never saw. Each half also gets `--singles` people who
have one photo only, because most people in real footage are seen once.

Each photo counts as one track here. In the app a track is the mean of several faces of one
shot, and faces in one frame are kept apart; neither exists in a set of single photos.
"""

# scikit-learn's metric functions are untyped.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tarfile
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

from cinemind.ai import face_cluster
from cinemind.ai.faces import FaceEngine, engine_version
from cinemind.core import face_config
from cinemind.core.config import REPO_ROOT, get_settings
from cinemind.core.hardware import detect_hardware

# Source and checksum as listed by scikit-learn's own LFW loader (sklearn/datasets/_lfw.py).
DATASET_URL = "https://ndownloader.figshare.com/files/5976018"
DATASET_SHA256 = "055f7d9c632d7370e6fb4afc7468d40f970c34a80d4c6f50ffec63f5a8d536c0"
DATASET_DIR = REPO_ROOT / "data" / "eval" / "lfw"
IMAGES = {".jpg", ".jpeg", ".png"}
DISTANCES = [round(0.30 + 0.05 * i, 2) for i in range(13)]  # 0.30 .. 0.90


def fetch() -> None:
    if any(DATASET_DIR.rglob("*.jpg")):
        print(f"already there: {DATASET_DIR}")
        return
    DATASET_DIR.parent.mkdir(parents=True, exist_ok=True)
    archive = DATASET_DIR.parent / "lfw.tgz"
    print(f"downloading {DATASET_URL} ...")
    cmd = ["curl", "--fail", "--location", "--silent", "--show-error", "-o", str(archive)]
    subprocess.run([*cmd, DATASET_URL], check=True, timeout=3600)  # noqa: S603
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != DATASET_SHA256:
        archive.unlink()
        sys.exit("The download does not match its checksum; nothing was unpacked. Try again.")
    with tarfile.open(archive) as tar:
        tar.extractall(DATASET_DIR.parent, filter="data")
    archive.unlink()
    print(f"ready: {DATASET_DIR}")


def pick(
    folder: Path, min_photos: int, max_photos: int, singles: int
) -> list[list[tuple[str, Path]]]:
    """Two halves of (person, photo): people with at least `min_photos` (at most `max_photos`
    used, in name order), alternating between the halves, plus `singles` one-photo people each."""
    people = {
        d.name: sorted(p for p in d.iterdir() if p.suffix.lower() in IMAGES)
        for d in sorted(folder.iterdir())
        if d.is_dir()
    }
    many = [name for name, photos in people.items() if len(photos) >= min_photos]
    once = [name for name, photos in people.items() if len(photos) == 1]
    halves: list[list[tuple[str, Path]]] = [[], []]
    for i, name in enumerate(many):
        halves[i % 2] += [(name, photo) for photo in people[name][:max_photos]]
    for i, name in enumerate(once[: 2 * singles]):
        halves[i % 2].append((name, people[name][0]))
    return halves


def embed(
    engine: FaceEngine, cfg: face_config.FaceConfig, items: list[tuple[str, Path]]
) -> tuple[list[str], Any, Counter[str]]:
    """The vector of the usable face nearest the centre of each photo (LFW centres its subject).
    Photos without a usable face are left out and counted by reason."""
    names: list[str] = []
    vectors: list[Any] = []
    left_out: Counter[str] = Counter()
    for name, path in items:
        image = cv2.imread(str(path))
        if image is None:
            left_out["unreadable"] += 1
            continue
        height, width = image.shape[:2]

        def off_centre(face: Any, width: int = width, height: int = height) -> float:
            x, y, w, h = face.box
            return abs(x + w / 2 - width / 2) + abs(y + h / 2 - height / 2)

        found = sorted(engine.find(image, cfg), key=off_centre)
        usable = [face for face in found if face.reason is None]
        if not usable:
            left_out[found[0].reason or "none" if found else "no face found"] += 1
            continue
        names.append(name)
        vectors.append(usable[0].vector)
    return names, np.stack(vectors), left_out


def scores(truth: list[str], labels: list[int]) -> dict[str, float]:
    """Purity, adjusted Rand index, normalised mutual information and B-cubed
    precision/recall/F1 of `labels` against the true names."""
    total = len(truth)
    pairs = Counter(zip(labels, truth, strict=True))
    groups, people = Counter(labels), Counter(truth)
    purity = sum(max(n for (g, _), n in pairs.items() if g == group) for group in groups) / total
    precision = sum(n * n / groups[g] for (g, _), n in pairs.items()) / total
    recall = sum(n * n / people[p] for (_, p), n in pairs.items()) / total
    return {
        "groups": len(groups),
        "purity": round(purity, 4),
        "ari": round(float(adjusted_rand_score(truth, labels)), 4),
        "nmi": round(float(normalized_mutual_info_score(truth, labels)), 4),
        "bcubed_precision": round(precision, 4),
        "bcubed_recall": round(recall, 4),
        "bcubed_f1": round(2 * precision * recall / (precision + recall), 4),
    }


def _line(label: str, s: dict[str, float]) -> str:
    return (
        f"  {label:<22} groups {s['groups']:5d}  purity {s['purity']:.3f}  ARI {s['ari']:.3f}  "
        f"NMI {s['nmi']:.3f}  B3 P {s['bcubed_precision']:.3f} R {s['bcubed_recall']:.3f} "
        f"F1 {s['bcubed_f1']:.3f}"
    )


def run(folder: Path, min_photos: int, max_photos: int, singles: int) -> None:
    settings = get_settings()
    cfg = settings.faces
    engine = FaceEngine(settings.models_path)
    halves = pick(folder, min_photos, max_photos, singles)
    if not halves[0] or not halves[1]:
        sys.exit(f"No people with at least {min_photos} photos found under {folder}.")
    hw = detect_hardware()
    out: list[str] = [
        f"face grouping on {folder.name}, {date.today().isoformat()}",
        f"machine: {platform.platform()}, {hw.cpu_name}, {hw.ram_gb} GB RAM",
        f"engine: {face_config.ENGINE} ({engine_version()}), revisions "
        + ", ".join(spec.revision[:12] for spec in face_config.FACE_MODELS),
        f"face checks: min_score {cfg.min_score}, min_size_px {cfg.min_size_px}, "
        f"min_sharpness {cfg.min_sharpness}, max_turn {cfg.max_turn}",
        f"selection: people with >= {min_photos} photos (first {max_photos} each) + "
        f"{singles} one-photo people per half; halves = every other person by name",
    ]
    data: dict[str, Any] = {"folder": folder.name, "date": date.today().isoformat(), "halves": []}
    sets: list[tuple[list[str], Any]] = []
    for label, items in zip(("tuning half", "held-out half"), halves, strict=True):
        started = time.perf_counter()
        names, vectors, left_out = embed(engine, cfg, items)
        took = time.perf_counter() - started
        sets.append((names, vectors))
        out.append(
            f"{label}: {len(items)} photos of {len({n for n, _ in items})} people; "
            f"{len(names)} with a usable face ({len(set(names))} people), left out: "
            f"{dict(left_out) or 'none'}; {took / len(items) * 1000:.0f} ms per photo"
        )
        data["halves"].append(
            {"name": label, "photos": len(items), "used": len(names), "left_out": dict(left_out)}
        )
    tune_names, tune_vectors = sets[0]
    held_names, held_vectors = sets[1]

    out.append("tuning half, agglomerative (average linkage), by cosine distance:")
    sweep: dict[float, dict[str, float]] = {}
    for distance in DISTANCES:
        labels = face_cluster.cluster(tune_vectors, distance, "agglomerative")
        sweep[distance] = scores(tune_names, labels)
        out.append(_line(f"distance {distance:.2f}", sweep[distance]))
    best = max(DISTANCES, key=lambda d: (sweep[d]["bcubed_f1"], -d))
    out.append(f"chosen on the tuning half (best B-cubed F1): distance {best:.2f}")
    data["sweep_tuning"] = {str(d): s for d, s in sweep.items()}
    data["chosen_distance"] = best

    out.append("held-out half (never used for the choice):")
    held: dict[str, dict[str, float]] = {}
    variants = [
        (f"agglomerative {best:.2f}", "agglomerative", best),
        (f"configured {cfg.cluster_distance:.2f}", "agglomerative", cfg.cluster_distance),
        ("hdbscan", "hdbscan", best),
    ]
    for label, method, distance in variants:
        started = time.perf_counter()
        labels = face_cluster.cluster(held_vectors, distance, method)  # pyright: ignore[reportArgumentType]
        held[label] = scores(held_names, labels)
        out.append(_line(label, held[label]) + f"  ({time.perf_counter() - started:.1f} s)")
    out.append(f"  true people in the held-out half: {len(set(held_names))}")
    data["held_out"] = held
    data["held_out_people"] = len(set(held_names))

    text = "\n".join(out) + "\n"
    print(text)
    results = REPO_ROOT / "eval" / "results"
    stem = f"face_clusters_{folder.name}_{date.today().isoformat()}"
    (results / f"{stem}.txt").write_text(text)
    (results / f"{stem}.json").write_text(json.dumps(data, indent=2) + "\n")
    print(f"wrote eval/results/{stem}.txt and .json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch")
    runner = sub.add_parser("run")
    runner.add_argument("folder", type=Path)
    runner.add_argument("--min-photos", type=int, default=5)
    runner.add_argument("--max-photos", type=int, default=20)
    runner.add_argument("--singles", type=int, default=200)
    args = parser.parse_args()
    if args.command == "fetch":
        fetch()
    else:
        run(args.folder.resolve(), args.min_photos, args.max_photos, args.singles)


if __name__ == "__main__":
    main()
