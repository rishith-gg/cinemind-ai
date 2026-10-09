"""Counts and stage timings of one processed data directory (not a benchmark, not accuracy).

Usage: uv run python eval/phase4_run_summary.py data/phase4-verify
Reads the SQLite database read-only and prints what the pipeline produced. Whether a detected
cut is correct cannot be read from the database; that needs labelled footage (Phase 13).
"""

import sqlite3
import sys
from pathlib import Path

QUERIES = {
    "clips": "select count(*) from media_assets where probed",
    "footage seconds": "select round(sum(duration_s), 1) from media_assets where probed",
    "variable-frame-rate clips": "select count(*) from media_assets where is_vfr",
    "failed jobs": "select count(*) from jobs where status = 'failed'",
    "shots": "select count(*) from shots",
    "clips with more than one shot": (
        "select count(*) from (select media_id from shots group by media_id having count(*) > 1)"
    ),
    "detected cuts": (
        "select coalesce(sum(n - 1), 0) from (select count(*) n from shots group by media_id)"
    ),
    "keyframes": "select count(*) from keyframes",
}
STAGE_SECONDS = """
    select s.name, count(*),
           round(sum((julianday(s.finished_at) - julianday(s.started_at)) * 86400), 1)
    from job_stages s where s.status = 'succeeded' group by s.name order by min(s.ordinal)
"""


def main(data_dir: Path) -> None:
    db = sqlite3.connect(f"file:{data_dir / 'cinemind.db'}?mode=ro", uri=True)
    print(f"data directory: {data_dir}")
    for label, query in QUERIES.items():
        print(f"{label}: {db.execute(query).fetchone()[0]}")
    print("stage wall time, summed over fresh (uncached) runs:")
    for name, runs, seconds in db.execute(STAGE_SECONDS):
        print(f"  {name}: {seconds} s over {runs} runs")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
