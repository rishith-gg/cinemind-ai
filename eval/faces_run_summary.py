"""Faces and actors of one processed data directory: what the pipeline reported per clip, how
the tracks were grouped and how long the stage took. Not an accuracy figure (nobody labelled
who is who).

Usage: uv run python eval/faces_run_summary.py data
"""

import json
import sqlite3
import sys
from pathlib import Path

CLIPS = """
    select m.filename, m.duration_s, s.status, s.frames_sampled, s.faces_detected, s.faces_used,
           s.max_in_frame, s.details,
           (select count(*) from face_tracks t where t.media_id = m.id),
           (select count(distinct t.actor_id) from face_tracks t where t.media_id = m.id),
           (select round((julianday(st.finished_at) - julianday(st.started_at)) * 86400, 1)
              from job_stages st join jobs j on j.id = st.job_id
             where j.media_id = m.id and st.name = 'faces' and st.status = 'succeeded'
             order by st.finished_at desc limit 1)
    from media_assets m left join face_scans s on s.media_id = m.id
    where m.probed order by m.filename
"""
ACTORS = """
    select a.name, count(t.id), sum(t.face_count), count(distinct t.media_id),
           round(sum(t.end_s - t.start_s), 1)
    from actors a join face_tracks t on t.actor_id = a.id
    group by a.id order by sum(t.face_count) desc, a.number
"""


def main(data_dir: Path) -> None:
    db = sqlite3.connect(f"file:{data_dir / 'cinemind.db'}?mode=ro", uri=True)
    rows = db.execute(CLIPS).fetchall()
    print(f"data directory: {data_dir}")
    print(f"clips: {len(rows)}")
    for status, count in db.execute(
        "select status, count(*) from face_scans group by status order by status"
    ):
        print(f"  {status}: {count}")
    rejected: dict[str, int] = {}
    for row in rows:
        for reason, count in (json.loads(row[7] or "{}").get("rejected") or {}).items():
            rejected[reason] = rejected.get(reason, 0) + count
    print(
        f"frames sampled: {sum(r[3] or 0 for r in rows)}  faces detected: "
        f"{sum(r[4] or 0 for r in rows)}  used: {sum(r[5] or 0 for r in rows)}  "
        f"left out: {rejected}"
    )
    timed = [r for r in rows if r[10] is not None and r[1]]
    if timed:
        footage, wall = sum(r[1] for r in timed), sum(r[10] for r in timed)
        print(
            f"faces stage, fresh runs: {wall:.1f} s for {footage:.1f} s of footage "
            f"({len(timed)} clips, {wall / footage:.3f} s per footage second)"
        )
    for (details,) in db.execute("select details from actor_runs"):
        print(f"grouping: {details}")
    actors = db.execute(ACTORS).fetchall()
    tracks = sum(a[1] for a in actors)
    print(f"actors: {len(actors)} from {tracks} tracks; seen in one track only: "
          f"{sum(1 for a in actors if a[1] == 1)}")  # fmt: skip
    for state, count in db.execute("select state, count(*) from face_tracks group by state"):
        print(f"  tracks {state}: {count}")
    print("actors (tracks, faces, clips, seconds seen):")
    for name, n_tracks, faces, clips, seen in actors:
        print(f"  {name[:20]:<20} {n_tracks:3d} {faces:4d} {clips:2d} {seen:6.1f}")
    print("per clip (duration s, status, sampled, detected, used, max in frame, tracks, actors,")
    print("          stage s):")
    for name, duration, status, sampled, detected, used, most, _, n_tracks, people, wall in rows:
        print(
            f"  {name[:28]:<28} {duration or 0:6.1f}  {status or '-':<13} {sampled or 0:4d} "
            f"{detected or 0:4d} {used or 0:4d} {most or 0:2d} {n_tracks:3d} {people:2d}  "
            f"{wall if wall is not None else '-'}"
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
