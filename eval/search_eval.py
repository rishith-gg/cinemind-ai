"""Search evaluation: P@5, P@10, nDCG@10 and MRR of every result list alone, of the fused
ranking, and of the fused ranking without each list (ablations), against relevance judgments.

Judgments are stored in the project's database (`search_judgments`): made in the app with the
"good result / not" buttons (judge "user"), or imported from a file (`import`, with the judge's
name). Pooling, as in TREC: only shots someone judged count as relevant; an unjudged shot in the
top 10 counts as not relevant, and how many there were is printed next to the figures. Relevance
is binary. The queries are whatever was judged; their number is printed, and with few queries the
averages are rough.

Usage:
  uv run python eval/search_eval.py run data [--project ID] [--judge user] [--lists a,b] [--out]
  uv run python eval/search_eval.py pool data --project ID --queries q.txt --out DIR
  uv run python eval/search_eval.py import data --project ID --judge NAME judgments.json
  uv run python eval/search_eval.py export data --project ID --judge NAME judgments.json

`pool` writes, per query, a contact sheet of the shots the lists and the fused ranking put in
their top 10 (numbered) and a JSON of what each number is, for judging by eye. The import file
is {"query": {"relevant": [shot ids], "not": [shot ids]}}.
"""

# numpy and OpenCV are untyped.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import argparse
import datetime
import json
import platform
import statistics
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from cinemind.ai import embedder  # noqa: E402
from cinemind.core.config import REPO_ROOT, Settings, get_settings  # noqa: E402
from cinemind.core.search_config import RETRIEVERS  # noqa: E402
from cinemind.db.analysis import SearchJudgment, normal_query  # noqa: E402
from cinemind.db.base import make_engine, make_session_factory  # noqa: E402
from cinemind.db.models import Keyframe, MediaAsset, Project, Shot  # noqa: E402
from cinemind.pipeline import shot_marks  # noqa: E402
from cinemind.search import hybrid, ranking  # noqa: E402
from cinemind.search.metrics import ndcg_at, precision_at, reciprocal_rank  # noqa: E402

K = 10
RESULTS = REPO_ROOT / "eval" / "results"


# --- helpers ----------------------------------------------------------------------------------


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


def _ranked(
    session: Session,
    settings: Settings,
    project: str,
    query: str,
    use: Sequence[str],
    weights: dict[str, float] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Shot ids best first: the fused (RRF) order, or with `weights` the ranked order."""
    # Judged shots must be rankable whatever the user marked: rejected shots stay in.
    q = hybrid.Query(text=query, use=use, filters=hybrid.Filters(include_rejected=True))
    if weights is None:
        out = hybrid.run(session, settings, project, q)
        return [r.shot_id for r in out.results], out.unavailable
    out, placed = ranking.run_ranked(session, settings, project, q, weights)
    return [r.fused.shot_id for r in placed], out.unavailable


Config = tuple[str, list[str], dict[str, float] | None]


def configurations(lists: Sequence[str], settings: Settings) -> list[Config]:
    """Each list alone, all of them fused, the fusion without each one, and the ranking (SPEC
    section 10) with its default weights and without each signal that can change the order."""
    found: list[Config] = [(name, [name], None) for name in lists]
    found.append(("hybrid", list(lists), None))
    if len(lists) > 2:
        found += [(f"hybrid - {name}", [n for n in lists if n != name], None) for name in lists]
    weights = dict(settings.ranking.weights)
    found.append(("ranked", list(lists), weights))
    for signal in ("quality", "selection", "duplicate"):
        found.append((f"ranked - {signal}", list(lists), {**weights, signal: 0.0}))
    return found


def _starred(session: Session, project: str) -> bool:
    from cinemind.db.analysis import ShotMark

    query = select(ShotMark.shot_id).where(ShotMark.project_id == project, ShotMark.stars > 0)
    return session.scalar(query.limit(1)) is not None


def picture_similarity(session: Session, settings: Settings, project: str) -> str:
    """Spread of the cosine between the shots' mean picture vectors (what the duplicate
    threshold is compared with)."""
    import numpy as np

    from cinemind.db.analysis import Embedding

    key = embedder.choose_visual(settings).key
    sums: dict[str, Any] = {}
    rows = session.execute(
        select(Embedding.shot_id, Embedding.vector)
        .join(MediaAsset, MediaAsset.id == Embedding.media_id)
        .where(MediaAsset.project_id == project, Embedding.kind == "keyframe",
               Embedding.model == key)
    )  # fmt: skip
    for shot, blob in rows:
        sums[str(shot)] = sums.get(str(shot), 0) + np.frombuffer(blob, dtype=np.float32)
    if len(sums) < 2:
        return "picture similarity between shots: fewer than two shots with vectors"
    matrix = np.stack([v / np.linalg.norm(v) for v in sums.values()])
    pairs = (matrix @ matrix.T)[np.triu_indices(len(sums), 1)]
    cuts = ", ".join(f"p{p} {np.percentile(pairs, p):.3f}" for p in (10, 50, 90, 99))
    return (
        f"Picture similarity between shots ({len(pairs)} pairs): {cuts}, max {pairs.max():.3f}; "
        f"duplicate threshold {settings.ranking.duplicate_threshold}."
    )


# --- run --------------------------------------------------------------------------------------


def _apply_overrides(settings: Settings, args: argparse.Namespace) -> None:
    """Settings to try (for tuning on a development set of queries, never on the test set)."""
    update: dict[str, Any] = {}
    if args.text_floor is not None:
        update["text_min_similarity"] = args.text_floor
    if args.weight:
        weights = dict(settings.search.weights)
        for item in args.weight:
            name, _, value = item.partition("=")
            weights[name] = float(value)
        update["weights"] = weights
    if update:
        settings.search = settings.search.model_copy(update=update)


def run(args: argparse.Namespace) -> None:
    settings = _settings(Path(args.data))
    _apply_overrides(settings, args)
    lists = [n.strip() for n in args.lists.split(",")] if args.lists else list(RETRIEVERS)
    with _session(settings) as session:
        project = _project(session, args.project)
        query = select(SearchJudgment).where(SearchJudgment.project_id == project)
        if args.judge != "any":
            query = query.where(SearchJudgment.judge == args.judge)
        judged: dict[str, dict[str, bool]] = {}
        count = 0
        for j in session.scalars(query.order_by(SearchJudgment.created_at, SearchJudgment.id)):
            judged.setdefault(j.query, {})[j.shot_id] = j.relevant  # the latest one wins
            count += 1
        queries = sorted(q for q, marks in judged.items() if any(marks.values()))
        shots = (
            session.query(Shot).join(MediaAsset).filter(MediaAsset.project_id == project).count()
        )
        relevant_counts = sorted(sum(judged[q].values()) for q in queries)
        median = statistics.median(relevant_counts) if relevant_counts else 0
        cfg = settings.search
        lines = [
            f"Search evaluation, {datetime.date.today()}: project {project} ({shots} shots), judge "
            f"{args.judge}, {count} judgments, {len(queries)} queries with at least one relevant "
            f"shot ({len(judged) - len(queries)} judged queries without any left out); relevant "
            f"shots per query: median {median}, range {relevant_counts[:1] and relevant_counts[0]}"
            f" to {relevant_counts[-1:] and relevant_counts[-1]}.",
            "Unjudged shots count as not relevant; 'unjudged' is their mean number in the "
            f"top {K}. Queries are searched in their stored, normalised form (lower case).",
            f"Models: picture {embedder.choose_visual(settings).key}, text "
            f"{embedder.choose_text(settings).key}. Machine: {platform.system()} "
            f"{platform.machine()}.",
            f"Settings: RRF k={cfg.rrf_k}, depth {cfg.depth}, weights {cfg.weights}, text floor "
            f"{cfg.text_min_similarity}, visual prompt {cfg.visual_prompt!r}.",
            f"Ranking weights: {settings.ranking.weights}; selects in the project: "
            f"{len(shot_marks.selected(session, project))}, rejects (left out): "
            f"{len(shot_marks.rejected(session, project))} (kept in for the evaluation).",
            picture_similarity(session, settings, project),
            "",
            f"{'configuration':<20} {'P@5':>6} {'P@10':>6} {'nDCG@10':>8} {'MRR':>6} "
            f"{'unjudged':>9}",
        ]
        table: dict[str, dict[str, float]] = {}
        per_query: dict[str, dict[str, list[str]]] = {}
        ndcg_by_query: dict[str, dict[str, float]] = {}
        missing: dict[str, str] = {}
        configs = configurations(lists, settings)
        if not shot_marks.selected(session, project) and not _starred(session, project):
            configs = [c for c in configs if c[0] != "ranked - selection"]
            note_selection = True
        else:
            note_selection = False
        for name, use, weights in configs:
            scores: dict[str, list[float]] = {"p5": [], "p10": [], "ndcg": [], "mrr": [], "unj": []}
            for q in queries:
                ranked, unavailable = _ranked(session, settings, project, q, use, weights)
                missing.update(unavailable)
                relevant = {s for s, ok in judged[q].items() if ok}
                scores["p5"].append(precision_at(ranked, relevant, 5))
                scores["p10"].append(precision_at(ranked, relevant, K))
                scores["ndcg"].append(ndcg_at(ranked, relevant, K))
                scores["mrr"].append(reciprocal_rank(ranked, relevant))
                scores["unj"].append(sum(1 for s in ranked[:K] if s not in judged[q]))
                per_query.setdefault(q, {})[name] = ranked[:K]
                ndcg_by_query.setdefault(q, {})[name] = scores["ndcg"][-1]
            mean = {key: (sum(v) / len(v) if v else 0.0) for key, v in scores.items()}
            table[name] = mean
            lines.append(
                f"{name:<20} {mean['p5']:6.3f} {mean['p10']:6.3f} {mean['ndcg']:8.3f} "
                f"{mean['mrr']:6.3f} {mean['unj']:9.1f}"
            )
        if note_selection:
            lines.append("(ranked - selection left out: no selects or stars in the project)")
        names = [n for n, _, _ in configs if n in lists or n in ("hybrid", "ranked")]
        lines += ["", "nDCG@10 per query (first result relevant: *)", f"{'query':<36} " + " ".join(
            f"{n[:13]:>13}" for n in names
        )]  # fmt: skip
        for q in queries:
            relevant = {s for s, ok in judged[q].items() if ok}
            cells = []
            for n in names:
                top = per_query[q][n][:1]
                star = "*" if top and top[0] in relevant else " "
                cells.append(f"{ndcg_by_query[q][n]:12.3f}{star}")
            lines.append(f"{q[:36]:<36} " + " ".join(cells))
        if missing:
            lines += [
                "",
                "Lists that could not run: " + "; ".join(f"{k}: {v}" for k, v in missing.items()),
            ]
    text = "\n".join(lines)
    print(text)
    if args.out:
        RESULTS.mkdir(parents=True, exist_ok=True)
        stem = RESULTS / f"search_eval_{args.judge}_{datetime.date.today()}"
        stem.with_suffix(".txt").write_text(text + "\n")
        record = {"table": table, "queries": queries, "top10": per_query, "judge": args.judge,
                  "ndcg_by_query": ndcg_by_query}  # fmt: skip
        stem.with_suffix(".json").write_text(json.dumps(record, indent=1))
        print(f"\nwrote {stem.relative_to(REPO_ROOT)}.txt/.json")


def export(args: argparse.Namespace) -> None:
    """Write a judge's judgments to a file (the format `import` reads, plus the clip and shot
    number of each shot so a person can check them), so the evaluation can be repeated."""
    settings = _settings(Path(args.data))
    with _session(settings) as session:
        project = _project(session, args.project)
        rows = session.execute(
            select(SearchJudgment, MediaAsset.filename, Shot.index)
            .join(MediaAsset, MediaAsset.id == SearchJudgment.media_id)
            .outerjoin(Shot, Shot.id == SearchJudgment.shot_id)
            .where(SearchJudgment.project_id == project, SearchJudgment.judge == args.judge)
            .order_by(SearchJudgment.query, MediaAsset.filename, Shot.index)
        ).all()
    out: dict[str, Any] = {}
    for judgment, filename, index in rows:
        entry = out.setdefault(judgment.query, {"relevant": [], "not": [], "shots": {}})
        entry["relevant" if judgment.relevant else "not"].append(judgment.shot_id)
        entry["shots"][judgment.shot_id] = (
            f"{filename} shot {index + 1 if index is not None else '?'}"
        )
    path = Path(args.file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"wrote {len(rows)} judgments for {len(out)} queries to {path}")


# --- pool and import --------------------------------------------------------------------------


def pool(args: argparse.Namespace) -> None:
    import cv2
    import numpy as np

    settings = _settings(Path(args.data))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    queries = [q.strip() for q in Path(args.queries).read_text().splitlines() if q.strip()]
    with _session(settings) as session:
        project = _project(session, args.project)
        root = settings.project_dir(project)
        for n, q in enumerate(queries):
            pooled: list[str] = []
            for _, use, _ in configurations(list(RETRIEVERS), settings)[: len(RETRIEVERS) + 1]:
                ranked, _ = _ranked(session, settings, project, q, use)
                pooled += [s for s in ranked[:K] if s not in pooled]
            tiles = []
            for i, shot in enumerate(pooled):
                frames = list(session.scalars(select(Keyframe).where(Keyframe.shot_id == shot)))
                frame = frames[len(frames) // 2] if frames else None
                image = cv2.imread(str(root / frame.path)) if frame else None
                tile = np.zeros((150, 200, 3), np.uint8)
                if image is not None:
                    tile = cv2.resize(image, (200, 150))
                cv2.rectangle(tile, (0, 0), (40, 20), (0, 0, 0), -1)
                cv2.putText(tile, str(i), (3, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                tiles.append(tile)
            while len(tiles) % 8:
                tiles.append(np.zeros((150, 200, 3), np.uint8))
            rows = [np.hstack(tiles[i : i + 8]) for i in range(0, len(tiles), 8)]
            if rows:
                cv2.imwrite(str(out_dir / f"q{n:02d}.jpg"), np.vstack(rows))
            (out_dir / f"q{n:02d}.json").write_text(json.dumps({"query": q, "shots": pooled}))
            print(f"q{n:02d} {q!r}: {len(pooled)} shots pooled")


def import_judgments(args: argparse.Namespace) -> None:
    settings = _settings(Path(args.data))
    entries: dict[str, dict[str, list[str]]] = json.loads(Path(args.file).read_text())
    with _session(settings) as session:
        project = _project(session, args.project)
        media = dict(
            session.execute(
                select(Shot.id, Shot.media_id)
                .join(MediaAsset)
                .where(MediaAsset.project_id == project)
            ).all()
        )
        count = 0
        for raw, marks in entries.items():
            q = normal_query(raw)
            session.execute(
                delete(SearchJudgment).where(
                    SearchJudgment.project_id == project,
                    SearchJudgment.query == q,
                    SearchJudgment.judge == args.judge,
                )
            )
            for relevant, key in ((True, "relevant"), (False, "not")):
                for shot in marks.get(key, []):
                    if shot not in media:
                        raise SystemExit(f"{shot} is not a shot of project {project}")
                    session.add(
                        SearchJudgment(project_id=project, media_id=media[shot], query=q,
                                       shot_id=shot, relevant=relevant, judge=args.judge)
                    )  # fmt: skip
                    count += 1
        session.commit()
    print(f"imported {count} judgments for {len(entries)} queries as judge {args.judge!r}")


def main(argv: list[str] | None = None) -> Any:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run")
    p.add_argument("data")
    p.add_argument("--project")
    p.add_argument("--judge", default="user", help='"user", an imported name, or "any"')
    p.add_argument("--lists", help=f"comma-separated, default {','.join(RETRIEVERS)}")
    p.add_argument("--out", action="store_true", help="also write eval/results/search_eval_*")
    p.add_argument("--text-floor", type=float, help="try another [search] text_min_similarity")
    p.add_argument("--weight", action="append", help="try another weight, e.g. text=0.5")
    p.set_defaults(func=run)
    p = sub.add_parser("export")
    p.add_argument("data")
    p.add_argument("--project")
    p.add_argument("--judge", required=True)
    p.add_argument("file")
    p.set_defaults(func=export)
    p = sub.add_parser("pool")
    p.add_argument("data")
    p.add_argument("--project")
    p.add_argument("--queries", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=pool)
    p = sub.add_parser("import")
    p.add_argument("data")
    p.add_argument("--project")
    p.add_argument("--judge", required=True)
    p.add_argument("file")
    p.set_defaults(func=import_judgments)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    main()
