"""Calibrate the picture-quality flag thresholds on real frames with synthetic degradations.

Usage: uv run python eval/calibrate_quality.py <data dir> [--out eval/results/NAME]

What it does
- Reads every keyframe of a processed data directory (real footage; keyframes are the sharpest
  frames of each shot, so they are the "acceptable" pool).
- Makes degraded copies with a KNOWN cause: Gaussian blur (sigma 1.5 / 3 / 6 / 12 px on the
  stored frame), exposure pushed up (+1.5 / +3 stops) and down (-2 / -4 stops) in linear light.
- Measures every image with the app's own `frame_metrics`.
- Picks each threshold on 4/5 of the CLIPS and tests it on the held-out 1/5 (grouped 5-fold, so
  frames of one clip are never on both sides), then fits the final value on all clips.

What it is not: the labels say how a frame was degraded, not what a person thinks of naturally
soft or badly exposed footage, and the "acceptable" pool is not hand-checked. Treat the numbers
as "can the metric tell a known degradation from the original", not as human-level accuracy.
"""
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import argparse
import json
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))
from cinemind.core.quality_config import QualityConfig  # noqa: E402
from cinemind.pipeline.quality import (  # noqa: E402
    METRICS_VERSION,
    frame_metrics,
    picture_flags,
)

FOLDS = 5
QUANTILES = [0, 10, 25, 50, 75, 90, 100]
Image = Any


def expose(image: Image, stops: float) -> Image:
    linear = (image.astype(np.float32) / 255.0) ** 2.2 * (2.0**stops)
    return (np.clip(linear, 0.0, 1.0) ** (1 / 2.2) * 255.0).astype(np.uint8)


def blur(image: Image, sigma: float) -> Image:
    return cv2.GaussianBlur(image, (0, 0), sigma)


VARIANTS: dict[str, Callable[[Image], Image]] = {
    "original": lambda i: i,
    "blur_1.5": lambda i: blur(i, 1.5),
    "blur_3": lambda i: blur(i, 3.0),
    "blur_6": lambda i: blur(i, 6.0),
    "blur_12": lambda i: blur(i, 12.0),
    "over_1.5": lambda i: expose(i, 1.5),
    "over_3": lambda i: expose(i, 3.0),
    "under_2": lambda i: expose(i, -2.0),
    "under_4": lambda i: expose(i, -4.0),
}
# Which degradations a flag is meant to catch (the milder ones are reported, not targeted).
TARGETS = {
    "out_of_focus": ["blur_3", "blur_6", "blur_12"],
    "overexposed": ["over_3"],
    "underexposed": ["under_4"],
}


def load(data_dir: Path) -> list[dict[str, Any]]:
    db = sqlite3.connect(f"file:{data_dir / 'cinemind.db'}?mode=ro", uri=True)
    query = (
        "select k.path, m.id, m.filename, m.project_id from keyframes k "
        "join media_assets m on m.id = k.media_id order by m.filename, k.path"
    )
    rows: list[dict[str, Any]] = []
    for path, media_id, filename, project_id in db.execute(query):
        image = cv2.imread(str(data_dir / "projects" / project_id / path))
        if image is None:
            continue
        for variant, make in VARIANTS.items():
            metrics = asdict(frame_metrics(make(image)))
            rows.append({"clip": media_id, "file": filename, "variant": variant, **metrics})
    return rows


def auc(positive: list[float], negative: list[float]) -> float:
    """Probability that a positive scores above a negative (ties count half)."""
    pos, neg = np.array(positive), np.array(negative)
    wins = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(wins / (len(pos) * len(neg)))


def best_threshold(positive: list[float], negative: list[float]) -> float:
    """Cut between the classes with the best balanced accuracy (positives are ABOVE it)."""
    values = np.unique(np.array(positive + negative))
    cuts = (values[:-1] + values[1:]) / 2 if len(values) > 1 else values
    pos, neg = np.array(positive), np.array(negative)
    scores = [((pos > c).mean() + (neg <= c).mean()) / 2 for c in cuts]
    return float(cuts[int(np.argmax(scores))])


def confusion(predicted: list[bool], actual: list[bool]) -> dict[str, float]:
    tp = sum(p and a for p, a in zip(predicted, actual, strict=True))
    fp = sum(p and not a for p, a in zip(predicted, actual, strict=True))
    fn = sum(a and not p for p, a in zip(predicted, actual, strict=True))
    tn = len(actual) - tp - fp - fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "accuracy": round((tp + tn) / len(actual), 3),
    }


class Rule:
    """flag = primary beyond its threshold OR (optional) secondary beyond its threshold.
    A sign is +1 when larger values mean "degraded", -1 when smaller ones do."""

    def __init__(
        self, primary: str, sign: int, secondary: str | None = None, secondary_sign: int = 1
    ) -> None:
        self.primary, self.sign, self.secondary = primary, sign, secondary
        self.secondary_sign = secondary_sign
        self.t_primary = 0.0
        self.t_secondary = 0.0

    def fit(self, positive: list[dict[str, Any]], negative: list[dict[str, Any]]) -> None:
        pos = [self.sign * r[self.primary] for r in positive]
        neg = [self.sign * r[self.primary] for r in negative]
        self.t_primary = self.sign * best_threshold(pos, neg)
        if self.secondary:
            # Conservative: just beyond anything seen on an acceptable training frame.
            sign = self.secondary_sign
            self.t_secondary = sign * max(sign * r[self.secondary] for r in negative)

    def predict(self, row: dict[str, Any]) -> bool:
        hit = self.sign * row[self.primary] > self.sign * self.t_primary
        if hit or not self.secondary:
            return hit
        sign = self.secondary_sign
        return sign * row[self.secondary] > sign * self.t_secondary


RULES: dict[str, Callable[[], Rule]] = {
    "out_of_focus (re-blur ratio)": lambda: Rule("blur", +1, "sharpness", -1),
    "out_of_focus (Laplacian variance)": lambda: Rule("sharpness", -1),
    "overexposed": lambda: Rule("luma_mean", +1, "clipped"),
    "underexposed": lambda: Rule("luma_mean", -1, "crushed"),
}


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    clips = sorted({r["clip"] for r in rows})
    fold_of = {clip: i % FOLDS for i, clip in enumerate(clips)}
    by_variant: dict[str, list[dict[str, Any]]] = {v: [] for v in VARIANTS}
    for row in rows:
        by_variant[row["variant"]].append(row)
    clean = by_variant["original"]
    report: dict[str, Any] = {}
    for name, make in RULES.items():
        flag = name.split(" ")[0]
        targeted = [r for v in TARGETS[flag] for r in by_variant[v]]
        predicted: list[bool] = []
        actual: list[bool] = []
        for fold in range(FOLDS):
            rule = make()
            rule.fit(
                [r for r in targeted if fold_of[r["clip"]] != fold],
                [r for r in clean if fold_of[r["clip"]] != fold],
            )
            for label, group in ((True, targeted), (False, clean)):
                held = [r for r in group if fold_of[r["clip"]] == fold]
                predicted += [rule.predict(r) for r in held]
                actual += [label] * len(held)
        final = make()
        final.fit(targeted, clean)
        family = TARGETS[flag][0].split("_")[0]
        report[name] = {
            "rule": {
                "primary": final.primary,
                "direction": "above" if final.sign > 0 else "below",
                "threshold": round(final.t_primary, 4),
                "secondary": final.secondary,
                "secondary_direction": "above" if final.secondary_sign > 0 else "below",
                "secondary_threshold": round(final.t_secondary, 4) if final.secondary else None,
            },
            "held_out": confusion(predicted, actual),
            "auc_primary": round(
                auc(
                    [final.sign * r[final.primary] for r in targeted],
                    [final.sign * r[final.primary] for r in clean],
                ),
                3,
            ),
            # How much of each severity the FINAL rule flags (fitted on all clips: optimistic).
            "flagged_share_by_variant": {
                v: round(float(np.mean([final.predict(r) for r in by_variant[v]])), 3)
                for v in VARIANTS
                if v == "original" or v.startswith(family)
            },
        }
    # The rule that actually ships: `picture_flags` with the default settings (rounded
    # thresholds, plus the "focus is not judged on flat frames" gate). In-sample, so it is a
    # consistency check on the settings rather than a second held-out estimate.
    shipped_cfg = QualityConfig()
    shipped: dict[str, dict[str, str]] = {}
    for flag, variants in TARGETS.items():
        family = variants[0].split("_")[0]
        shipped[flag] = {}
        for variant in VARIANTS:
            if variant != "original" and not variant.startswith(family):
                continue
            group = by_variant[variant]
            hits = sum(any(f["kind"] == flag for f in picture_flags(r, shipped_cfg)) for r in group)
            shipped[flag][variant] = f"{hits}/{len(group)}"
    quantiles = {
        metric: [round(float(q), 4) for q in np.percentile([r[metric] for r in clean], QUANTILES)]
        for metric in ("blur", "sharpness", "luma_mean", "spread", "clipped", "crushed")
    }
    return {
        "original_quantiles": {"percentiles": QUANTILES, **quantiles},
        "shipped_settings_flagged": shipped,
        "metrics_version": METRICS_VERSION,
        "clips": len(clips),
        "frames": len(clean),
        "images_measured": len(rows),
        "folds": FOLDS,
        "targets": TARGETS,
        "results": report,
    }


def render(result: dict[str, Any]) -> str:
    lines = [
        f"clips: {result['clips']}  original frames: {result['frames']}  "
        f"images measured: {result['images_measured']}  grouped folds: {result['folds']}",
        "",
    ]
    spread = result["original_quantiles"]
    lines.append(f"original frames, percentiles {spread['percentiles']}:")
    lines += [
        f"  {metric}: {values}" for metric, values in spread.items() if metric != "percentiles"
    ]
    lines.append("")
    for name, item in result["results"].items():
        rule, held = item["rule"], item["held_out"]
        text = f"{rule['primary']} {rule['direction']} {rule['threshold']}"
        if rule["secondary"]:
            text += (
                f" OR {rule['secondary']} {rule['secondary_direction']} "
                f"{rule['secondary_threshold']}"
            )
        lines += [
            name,
            f"  rule (fitted on all clips): {text}",
            f"  held-out: precision {held['precision']}  recall {held['recall']}  "
            f"F1 {held['f1']}  accuracy {held['accuracy']}  "
            f"(tp {held['tp']} fp {held['fp']} fn {held['fn']} tn {held['tn']})",
            f"  AUC of the primary metric: {item['auc_primary']}",
            f"  share flagged by the final rule: {item['flagged_share_by_variant']}",
            "",
        ]
    lines.append("shipped default settings (picture_flags, all frames, flagged/total):")
    lines += [f"  {flag}: {counts}" for flag, counts in result["shipped_settings_flagged"].items()]
    lines.append("")
    lines.append(
        "Precision, F1 and accuracy above hold only for this constructed mix of degraded and "
        "original frames; in real footage degraded frames are rarer. Recall and the count of "
        "flagged originals are the figures that carry over."
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--out", type=Path, default=None, help="write NAME.json and NAME.txt")
    args = parser.parse_args()
    rows = load(args.data_dir)
    if not rows:
        sys.exit("No keyframes found. Process some footage first.")
    result = evaluate(rows)
    text = render(result)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
        args.out.with_suffix(".txt").write_text(text + "\n")


if __name__ == "__main__":
    main()
