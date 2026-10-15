"""How long the AI-assisted rough cut takes on a processed project, and what it builds.

Usage: uv run python eval/rough_cut_timing.py data [--project ID] [--out]

Builds a rough cut for each brief below in one process (the first one loads the search models,
as the first rough cut after starting the app does), times it, prints what was built, and
deletes the timelines again, so the project is left as it was. Not an accuracy figure: whether
the chosen clips suit the brief needs an editor's judgement (Phase 13 user study). The briefs
were written by Claude to cover a length in minutes and seconds, an order, and a brief without
a subject; they are not the user's.
"""

import argparse
import datetime
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from sqlalchemy import select  # noqa: E402

from cinemind.core.config import REPO_ROOT, get_settings  # noqa: E402
from cinemind.core.hardware import detect_hardware  # noqa: E402
from cinemind.db.base import make_engine, make_session_factory  # noqa: E402
from cinemind.db.models import Project  # noqa: E402
from cinemind.rough_cut import engine  # noqa: E402
from cinemind.search.retrievers import visual_model  # noqa: E402

BRIEFS = (
    "1-minute sequence of people walking outdoors",
    "30 seconds of water and the beach, best first",
    "2 minutes about friends talking, by scene",
    "45 seconds",
)
RESULTS = REPO_ROOT / "eval" / "results"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--project")
    parser.add_argument("--out", action="store_true", help="also write eval/results/...txt")
    args = parser.parse_args()
    settings = get_settings()
    settings.data_dir = args.data_dir
    session = make_session_factory(make_engine(settings.db_path))()
    ids = [args.project] if args.project else list(session.scalars(select(Project.id)))
    if len(ids) != 1:
        raise SystemExit(f"{len(ids)} projects: say which with --project")
    project = ids[0]
    hw = detect_hardware()
    lines = [
        f"rough cut timing, {datetime.date.today()}, project {project}",
        f"machine: {platform.platform()}, {hw.cpu_name}, "
        f"{hw.ram_gb:.0f} GB RAM; picture model {visual_model(session, settings, project).key}",
        f"settings: {settings.rough_cut.model_dump()}",
        "",
    ]
    for n, brief in enumerate(BRIEFS):
        began = time.perf_counter()
        timeline = engine.build_rough_cut(session, settings, project, engine.Request(brief=brief))
        seconds = time.perf_counter() - began
        p = timeline.params
        length = sum(i.source_out_s - i.source_in_s for i in timeline.items)
        speech = sum(
            1 for i in timeline.items if (i.reason or {}).get("trim", {}).get("how") == "speech"
        )
        lines.append(
            f"{brief!r}: {seconds:.1f} s{' (first, loads the models)' if n == 0 else ''}; "
            f"{len(timeline.items)} clips ({speech} with speech), {length:.1f} s for a target of "
            f"{p['target_s']:g} s; {p['candidates']} candidates, {len(p['left_out'])} left out; "
            f"{timeline.width}x{timeline.height} at {timeline.fps_num}/{timeline.fps_den}"
        )
        session.delete(timeline)
        session.commit()
    text = "\n".join(lines)
    print(text)
    if args.out:
        out = RESULTS / f"rough_cut_timing_{datetime.date.today()}.txt"
        out.write_text(text + "\n", encoding="utf-8")
        print(f"written: {out}")


if __name__ == "__main__":
    main()
