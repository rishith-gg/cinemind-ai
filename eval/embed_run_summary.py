"""Embeddings, tags and scenes of one processed data directory: what the pipeline stored, which
tags are shown, how shots were grouped into scenes and how long the stages took. Not an accuracy
figure (nobody labelled tags or scenes in this footage); see tag_calibration.py for that.

Usage: uv run python eval/embed_run_summary.py data
"""

import json
import sqlite3
import sys
from pathlib import Path

STAGES = ("embed_visual", "embed_text", "tags")
TIMING = """
    select st.name, m.duration_s,
           (julianday(st.finished_at) - julianday(st.started_at)) * 86400
    from job_stages st join jobs j on j.id = st.job_id join media_assets m on m.id = j.media_id
    where st.status = 'succeeded' and st.name in ('embed_visual', 'embed_text', 'tags')
      and st.id = (select max(s2.id) from job_stages s2 join jobs j2 on j2.id = s2.job_id
                   where j2.media_id = j.media_id and s2.name = st.name and s2.status = 'succeeded')
"""


def main(data_dir: Path) -> None:
    db = sqlite3.connect(f"file:{data_dir / 'cinemind.db'}?mode=ro", uri=True)
    print(f"data directory: {data_dir}")
    for kind, status, model, count, n in db.execute(
        "select kind, status, model, sum(count), count(*) from embedding_sets "
        "group by kind, status, model order by kind, status"
    ):
        print(f"embeddings {kind}: {n} clips {status} ({model or '-'}), {count} vectors")
    for kind, model, n, dim in db.execute(
        "select kind, model, count(*), max(dim) from embeddings group by kind, model"
    ):
        print(f"  rows {kind:<9} {model:<16} {n:5d} x {dim}")
    timings: dict[str, list[tuple[float, float]]] = {}
    for name, duration, wall in db.execute(TIMING):
        timings.setdefault(name, []).append((duration or 0.0, wall or 0.0))
    for name in STAGES:
        rows = timings.get(name, [])
        if rows:
            footage, wall = sum(r[0] for r in rows), sum(r[1] for r in rows)
            print(
                f"stage {name}: {wall:.1f} s over {len(rows)} clips "
                f"({footage:.1f} s of footage; last succeeded run per clip, cached runs included)"
            )
    print("tags by status (shots):")
    for status, n in db.execute(
        "select status, count(*) from tags group by status order by status"
    ):
        print(f"  {status:<14} {n}")
    print("tags shown (approved, or above the threshold and not rejected), shots per tag:")
    shown = db.execute(
        "select t.label, count(*) from tags t left join tag_reviews r "
        "on r.shot_id = t.shot_id and r.name = t.name "
        "where (r.decision = 'approved') or (r.decision is null and t.status = 'shown') "
        "group by t.name order by count(*) desc, t.label"
    ).fetchall()
    for label, n in shown:
        print(f"  {label:<22} {n}")
    total = db.execute("select count(*) from shots").fetchone()[0]
    print(f"shots: {total}")
    for details, at in db.execute("select details, grouped_at from scene_runs"):
        print(f"scene grouping ({at}): {json.dumps(json.loads(details), sort_keys=True)}")
    print("scenes (shots, seconds, name):")
    for name, shots, seconds in db.execute(
        'select name, shot_count, duration_s from scenes order by project_id, "index"'
    ):
        print(f"  {shots:3d} {seconds:7.1f}  {name}")
    print("neighbour similarities (combined) and decisions:")
    for (details,) in db.execute('select details from scenes order by project_id, "index"'):
        for step in json.loads(details)["steps"]:
            combined = step.get("combined")
            value = "-" if combined is None else f"{combined:.3f}"
            print(f"  {value:>6}  {step['decision']}")
    for kind, model, backend, count in db.execute(
        "select kind, model, backend, count from vector_indexes order by kind"
    ):
        print(f"index {kind} {model}: {backend}, {count} vectors")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
