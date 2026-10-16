"""Take grouping evaluation (SPEC P1-B): pairwise and B-cubed precision / recall / F1 of the
automatic take groups against hand-made labels, plus how often the suggested best take agrees
with the editor's own pick.

The grouping is recomputed from the project's database with the app's own functions
(`pipeline/takes.project_infos` + `take_signals.group`), without the user's corrections, so the
figures describe the automatic suggestion. Labels name shots by file name and shot number
("IMG_0867.MOV#1", numbers from 1 as in the app), so they stay valid when the footage is imported
again; a shot not in any labelled group is a take of nothing. Who made the labels is stored in the
file and printed with the figures.

Usage:
  uv run python eval/take_groups.py sheet DATA [--project ID] --out DIR
  uv run python eval/take_groups.py run DATA --labels FILE [--project ID] [--out] [--sweep]

`sheet` writes contact sheets (three keyframes per shot, file name, shot number, the words heard)
and `shots.json` to label by eye. `--sweep` also prints the figures over a grid of the two main
limits; it uses the same labels, so it shows how sensitive the result is, never a tuned value.
"""

# numpy and OpenCV are untyped.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import argparse
import datetime
import itertools
import json
import platform
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from cinemind.ai import embedder  # noqa: E402
from cinemind.core.config import REPO_ROOT, Settings, get_settings  # noqa: E402
from cinemind.core.takes_config import TakesConfig  # noqa: E402
from cinemind.db.base import make_engine, make_session_factory  # noqa: E402
from cinemind.db.models import Keyframe, Project  # noqa: E402
from cinemind.db.takes import TakeEdit  # noqa: E402
from cinemind.pipeline.take_signals import ShotInfo, all_pairs, group, rank_takes  # noqa: E402
from cinemind.pipeline.takes import project_infos  # noqa: E402

RESULTS = REPO_ROOT / "eval" / "results"


def _settings(data_dir: Path) -> Settings:
    settings = get_settings()
    settings.data_dir = data_dir
    return settings


def _session(settings: Settings) -> Session:
    return make_session_factory(make_engine(settings.db_path))()


def _project(session: Session, wanted: str | None) -> str:
    if wanted:
        return wanted
    ids = list(session.scalars(select(Project.id)))
    if len(ids) != 1:
        raise SystemExit(f"{len(ids)} projects: say which with --project")
    return ids[0]


def label_of(info: ShotInfo, infos: Sequence[ShotInfo]) -> str:
    """'file#n', n counted from 1 within the clip (the app's shot number)."""
    n = sum(1 for i in infos if i.media_id == info.media_id and i.position <= info.position)
    return f"{info.filename}#{n}"


# --- metrics -----------------------------------------------------------------------------------


def _pairs(groups: Iterable[Iterable[str]]) -> set[frozenset[str]]:
    return {frozenset(p) for g in groups for p in itertools.combinations(sorted(g), 2)}


def _prf(tp: float, predicted: float, actual: float) -> dict[str, float | None]:
    p = tp / predicted if predicted else None
    r = tp / actual if actual else None
    f = 2 * p * r / (p + r) if p is not None and r is not None and p + r > 0 else None
    return {"precision": p, "recall": r, "f1": f}


def score(
    predicted: list[list[str]], truth: list[list[str]], items: Sequence[str]
) -> dict[str, Any]:
    """Pairwise P/R/F1 (pairs of shots put together) and B-cubed P/R/F1 (per shot, with every
    shot outside a group as a group of one)."""
    pred_pairs, true_pairs = _pairs(predicted), _pairs(truth)
    pairwise = _prf(len(pred_pairs & true_pairs), len(pred_pairs), len(true_pairs))
    pred_of = {s: frozenset(g) for g in predicted for s in g}
    true_of = {s: frozenset(g) for g in truth for s in g}
    bp = br = 0.0
    for s in items:
        p, t = pred_of.get(s, frozenset((s,))), true_of.get(s, frozenset((s,)))
        bp += len(p & t) / len(p)
        br += len(p & t) / len(t)
    b = _prf(1, 1, 1)
    b["precision"], b["recall"] = bp / len(items), br / len(items)
    b["f1"] = 2 * bp * br / (bp + br) / len(items) if bp + br else 0.0
    return {
        "pairwise": pairwise,
        "bcubed": b,
        "pairs": {
            "predicted": len(pred_pairs),
            "true": len(true_pairs),
            "right": len(pred_pairs & true_pairs),
        },  # fmt: skip
        "groups": {"predicted": len(predicted), "true": len(truth)},
        "wrong_pairs": sorted(sorted(p) for p in pred_pairs - true_pairs),
        "missed_pairs": sorted(sorted(p) for p in true_pairs - pred_pairs),
    }


def _grouping(infos: Sequence[ShotInfo], cfg: TakesConfig) -> tuple[list[list[str]], Any]:
    groups, pairs = group(infos, cfg, (), all_pairs(infos, cfg))
    return [[label_of(infos[i], infos) for i in g] for g in groups], pairs


# --- commands ----------------------------------------------------------------------------------


def sheet(args: argparse.Namespace) -> None:
    settings = _settings(Path(args.data))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with _session(settings) as session:
        project = _project(session, args.project)
        infos = project_infos(session, settings, project)
        frames: dict[str, list[Keyframe]] = {}
        for k in session.scalars(select(Keyframe).order_by(Keyframe.slot)):
            frames.setdefault(k.shot_id, []).append(k)
    root = settings.project_dir(project)
    listing: list[dict[str, Any]] = []
    rows: list[Any] = []
    for info in infos:
        label = label_of(info, infos)
        tiles = []
        for k in frames.get(info.id, [])[:3]:
            image = cv2.imread(str(root / k.path))
            tiles.append(
                cv2.resize(image, (240, 135))
                if image is not None
                else np.zeros((135, 240, 3), np.uint8)
            )
        while len(tiles) < 3:
            tiles.append(np.zeros((135, 240, 3), np.uint8))
        caption = np.zeros((135, 560, 3), np.uint8)
        text = f"{label}  {info.start_s:.1f}-{info.end_s:.1f}s"
        cv2.putText(caption, text, (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        words = info.text or "(no clear speech)"
        for n, start in enumerate(range(0, min(len(words), 400), 80)):
            cv2.putText(
                caption,
                words[start : start + 80],
                (5, 45 + 18 * n),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (220, 220, 220),
                1,
            )
        rows.append(np.hstack([*tiles, caption]))
        listing.append({"label": label, "shot_id": info.id, "start_s": info.start_s,
                        "end_s": info.end_s, "text": info.text})  # fmt: skip
    for n in range(0, len(rows), 8):
        cv2.imwrite(str(out / f"sheet_{n // 8 + 1:02d}.jpg"), np.vstack(rows[n : n + 8]))
    (out / "shots.json").write_text(json.dumps(listing, indent=1))
    print(f"{len(rows)} shots on {(len(rows) + 7) // 8} sheets in {out}")


def _fmt(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.3f}"


def run(args: argparse.Namespace) -> None:
    settings = _settings(Path(args.data))
    labels = json.loads(Path(args.labels).read_text())
    with _session(settings) as session:
        project = _project(session, args.project)
        infos = project_infos(session, settings, project)
        best_edits = {e.shot_id for e in session.scalars(select(TakeEdit).where(
            TakeEdit.project_id == project, TakeEdit.kind == "best"))}  # fmt: skip
    items = [label_of(i, infos) for i in infos]
    unknown = {s for g in labels["groups"] for s in g} - set(items)
    if unknown:
        raise SystemExit(f"labels name shots not in the project: {sorted(unknown)}")
    cfg = settings.takes
    predicted, pairs = _grouping(infos, cfg)
    result = score(predicted, labels["groups"], items)
    # Best take: the suggestion without the editor's pick, against the editor's pick.
    agree = total = 0
    groups, _ = group(infos, cfg, (), pairs)
    for members in groups:
        picked = [infos[i].id for i in members if infos[i].id in best_edits]
        if picked:
            total += 1
            _, ranked, _ = rank_takes(members, infos, pairs, cfg)
            agree += ranked[0].info.id == picked[-1]
    by_label = {label_of(i, infos): n for n, i in enumerate(infos)}

    def why(p: Sequence[str]) -> str:
        a, b = sorted((by_label[p[0]], by_label[p[1]]))
        return pairs[(a, b)].why

    speaking = sum(1 for i in infos if len(i.norm) >= cfg.min_words)
    lines = [
        f"Take grouping evaluation, {datetime.date.today().isoformat()}",
        f"labels: {args.labels} (judge: {labels.get('judge', '?')}; {labels.get('how', '')})",
        f"picture model: {embedder.choose_visual(settings).key}",
        f"settings: {json.dumps(cfg.model_dump())}",
        f"machine: {platform.platform()}, {platform.machine()}",
        f"shots: {len(items)}, with speech: {speaking}",
        f"groups: predicted {result['groups']['predicted']}, labelled {result['groups']['true']}",
        "pairs:  predicted {predicted}, labelled {true}, right {right}".format(**result["pairs"]),
        "pairwise  P {precision}  R {recall}  F1 {f1}".format(
            **{k: _fmt(v) for k, v in result["pairwise"].items()}
        ),
        "B-cubed   P {precision}  R {recall}  F1 {f1}".format(
            **{k: _fmt(v) for k, v in result["bcubed"].items()}
        ),
        f"best take: suggestion = editor's pick in {agree} of {total} groups with a pick",
        "wrong pairs (grouped, labelled apart):",
        *(f"  {a} + {b}: {why((a, b))}" for a, b in result["wrong_pairs"]),
        "missed pairs (labelled together, not grouped):",
        *(f"  {a} + {b}: {why((a, b))}" for a, b in result["missed_pairs"]),
    ]
    if args.sweep:
        lines.append(
            "sensitivity (same labels, NOT a tuning): group_min x picture_min -> pairwise P/R/F1"
        )
        for gm, pm in itertools.product((0.65, 0.7, 0.75, 0.8, 0.85), (0.85, 0.9, 0.95)):
            alt = cfg.model_copy(update={"group_min": gm, "picture_min": pm})
            r = score(_grouping(infos, alt)[0], labels["groups"], items)["pairwise"]
            lines.append(
                f"  {gm:.2f} {pm:.2f}  "
                + "P {precision}  R {recall}  F1 {f1}".format(**{k: _fmt(v) for k, v in r.items()})
            )
    text = "\n".join(lines)
    print(text)
    if args.out:
        stem = (
            RESULTS
            / f"take_groups_{labels.get('judge', 'labels')}_{datetime.date.today().isoformat()}"
        )
        stem.with_suffix(".txt").write_text(text + "\n")
        result |= {"predicted": predicted, "labels": labels["groups"], "best_agree": [agree, total]}
        stem.with_suffix(".json").write_text(json.dumps(result, indent=1))
        print(f"written {stem}.txt/.json")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("data")
    s.add_argument("--project")
    s.add_argument("--out", required=True)
    s.set_defaults(func=sheet)
    r = sub.add_parser("run")
    r.add_argument("data")
    r.add_argument("--labels", required=True)
    r.add_argument("--project")
    r.add_argument("--out", action="store_true")
    r.add_argument("--sweep", action="store_true")
    r.set_defaults(func=run)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
