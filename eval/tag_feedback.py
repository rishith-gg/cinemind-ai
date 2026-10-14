"""Precision of the shown tags on the user's own footage, from their approve / reject reviews.

Each review is logged with what the app had suggested (`feedback_events`, kind `tag_review`). A
tag that was shown and then approved counts as right, shown and rejected as wrong. Tags the user
never looked at are not counted, so the figure covers reviewed tags only, and only those a user
chose to review; say so next to it.

Usage: uv run python eval/tag_feedback.py data
"""

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path


def main(data_dir: Path) -> None:
    db = sqlite3.connect(f"file:{data_dir / 'cinemind.db'}?mode=ro", uri=True)
    last: dict[tuple[str, str], dict[str, object]] = {}
    for (payload,) in db.execute(
        "select payload from feedback_events where kind = 'tag_review' order by id"
    ):
        event = json.loads(payload)
        last[(str(event["shot_id"]), str(event["name"]))] = event  # the latest decision counts
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    approved_hidden = 0
    for event in last.values():
        if event["decision"] == "none":
            continue
        if event.get("status") != "shown":
            approved_hidden += event["decision"] == "approved"
            continue
        counts[str(event["name"])][0 if event["decision"] == "approved" else 1] += 1
    print(f"data directory: {data_dir}")
    decided = sum(1 for event in last.values() if event["decision"] != "none")
    print(f"reviewed tags: {decided} (latest decision per shot and tag; withdrawn ones left out)")
    if not counts:
        print("no reviews of shown tags yet")
    total_right = sum(c[0] for c in counts.values())
    total = sum(sum(c) for c in counts.values())
    for name, (right, wrong) in sorted(counts.items()):
        precision = right / (right + wrong)
        print(f"  {name:<12} approved {right:3d}  rejected {wrong:3d}  precision {precision:.2f}")
    if total:
        print(f"all shown tags reviewed: precision {total_right / total:.2f} over {total} reviews")
    print(f"hidden suggestions the user approved anyway: {approved_hidden}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
