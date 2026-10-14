"""Where the actor grouping limit should sit, from the user's "same person?" answers.

Each answer stores the average-linkage distance the two people had when asked (mean of
1 - cosine similarity over their tracks). The grouping joins two groups below `[faces]
cluster_distance`, so for any limit we can count, among the answered pairs, the people it
would join wrongly (answered "different" but below the limit) and the splits it would leave
(answered "same" but at or above it).

Read the result with its bias in mind: the app asks about the closest pairs it kept apart, so
the answers cover the region just above the limit in use, not all pairs of people.

Usage: uv run python eval/actor_pairs.py data
"""

import sqlite3
import sys
from pathlib import Path


def main(data_dir: Path) -> None:
    db = sqlite3.connect(f"file:{data_dir / 'cinemind.db'}?mode=ro", uri=True)
    rows = [
        (float(distance), bool(same))
        for distance, same in db.execute("select distance, same from actor_pair_answers")
    ]
    print(f"data directory: {data_dir}")
    same = sum(s for _, s in rows)
    print(f"answers: {len(rows)} ({same} same person, {len(rows) - same} different)")
    if not rows:
        print("no answers yet: answer some questions on the Actors page first")
        return
    for distance, s in sorted(rows):
        print(f"  distance {distance:.3f}  {'same' if s else 'different'}")
    limits = sorted({0.0, *(d + 1e-4 for d, _ in rows)})
    print("\nlimit   joined wrongly  left split  right")
    for limit in limits:
        wrong_join = sum(1 for d, s in rows if d < limit and not s)
        left_split = sum(1 for d, s in rows if d >= limit and s)
        right = len(rows) - wrong_join - left_split
        print(f"{limit:6.3f}  {wrong_join:14d}  {left_split:10d}  {right:5d}/{len(rows)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
