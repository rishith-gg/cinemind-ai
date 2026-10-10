"""Transcripts of one processed data directory: what the pipeline reported per clip and how long
the stage took. Not an accuracy figure (nobody checked the words).

Usage: uv run python eval/transcribe_run_summary.py data
"""

import sqlite3
import sys
from pathlib import Path

from cinemind.core.transcribe_config import UNCERTAIN_COMPRESSION_ABOVE, UNCERTAIN_LOGPROB_BELOW

# The two values are constants from our own settings module, not input.
CLIPS = f"""
    select m.filename, m.duration_s, t.status, t.language, t.language_probability, t.speech_s,
           t.model,
           (select count(*) from transcript_segments s where s.media_id = m.id),
           (select count(*) from transcript_segments s where s.media_id = m.id
              and (s.avg_logprob < {UNCERTAIN_LOGPROB_BELOW}
                   or s.compression_ratio > {UNCERTAIN_COMPRESSION_ABOVE})),
           (select count(*) from transcript_words w where w.media_id = m.id),
           (select round((julianday(s.finished_at) - julianday(s.started_at)) * 86400, 1)
              from job_stages s join jobs j on j.id = s.job_id
             where j.media_id = m.id and s.name = 'transcribe' and s.status = 'succeeded'
             order by s.finished_at desc limit 1)
    from media_assets m left join transcripts t on t.media_id = m.id
    where m.probed order by m.filename
"""  # noqa: S608


def main(data_dir: Path) -> None:
    db = sqlite3.connect(f"file:{data_dir / 'cinemind.db'}?mode=ro", uri=True)
    rows = db.execute(CLIPS).fetchall()
    print(f"data directory: {data_dir}")
    print(f"clips: {len(rows)}")
    for status, count in db.execute(
        "select status, count(*) from transcripts group by status order by status"
    ):
        print(f"  {status}: {count}")
    done = [r for r in rows if r[2] == "done"]
    timed = [r for r in rows if r[10] is not None and r[1]]
    print(f"segments: {sum(r[7] for r in done)}  marked uncertain: {sum(r[8] for r in done)}")
    print(f"language probability under 0.5: {sum(1 for r in done if (r[4] or 0) < 0.5)}")
    if timed:
        footage, wall = sum(r[1] for r in timed), sum(r[10] for r in timed)
        print(
            f"transcribe stage, fresh runs: {wall:.1f} s for {footage:.1f} s of footage "
            f"({len(timed)} clips, {wall / footage:.2f} s per footage second)"
        )
    print("per clip (duration s, status, model, language, probability, speech s, segments,")
    print("          uncertain segments, words, stage s):")
    for name, duration, status, lang, prob, speech, model, segs, unsure, words, wall in rows:
        print(
            f"  {name[:28]:<28} {duration or 0:6.1f}  {status or '-':<13} {model or '-':<6} "
            f"{lang or '-':<3} {prob if prob is not None else '-'}  {speech or 0:5.1f}  "
            f"{segs:3d} {unsure:3d} {words:4d}  {wall if wall is not None else '-'}"
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
