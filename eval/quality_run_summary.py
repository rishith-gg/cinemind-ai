"""Quality scores and QC flags of one processed data directory (what the pipeline reported, not
whether it is right).

Usage: uv run python eval/quality_run_summary.py data/phase4-verify
"""

import sqlite3
import sys
from pathlib import Path
from statistics import median

CLIPS = """
    select m.filename, m.quality_score, a.integrated_lufs, a.clipped_pct, a.silence_pct,
           (select group_concat(distinct f.kind) from qc_flags f where f.media_id = m.id)
    from media_assets m left join audio_metrics a on a.media_id = m.id
    where m.probed order by m.quality_score
"""
STAGES = """
    select s.name, count(*),
           round(sum((julianday(s.finished_at) - julianday(s.started_at)) * 86400), 1)
    from job_stages s where s.status = 'succeeded' and s.name in ('quality', 'audio_qc')
    group by s.name order by min(s.ordinal)
"""


def main(data_dir: Path) -> None:
    db = sqlite3.connect(f"file:{data_dir / 'cinemind.db'}?mode=ro", uri=True)
    rows = db.execute(CLIPS).fetchall()
    scored = [r[1] for r in rows if r[1] is not None]
    print(f"data directory: {data_dir}")
    print(f"clips: {len(rows)}  with a score: {len(scored)}")
    if scored:
        middle = median(scored)
        print(f"score min {min(scored):.2f}  median {middle:.2f}  max {max(scored):.2f}")
    shots = db.execute("select count(*) from quality_metrics").fetchone()[0]
    print(f"shots measured: {shots}")
    print(f"clips with at least one QC flag: {sum(1 for r in rows if r[5])}")
    for kind, count in db.execute(
        "select kind, count(*) from qc_flags group by kind order by kind"
    ):
        print(f"  flag {kind}: {count}")
    print("stage wall time, summed over fresh (uncached) runs:")
    for name, runs, seconds in db.execute(STAGES):
        print(f"  {name}: {seconds} s over {runs} runs")
    print("per clip (score, LUFS, clipped %, silent %, flags):")
    for name, score, lufs, clipped, silent, flags in rows:
        print(f"  {name[:28]:<28} {score}  {lufs}  {clipped}  {silent}  {flags or '-'}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
