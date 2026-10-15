"""Timeline builders shared parts, and the "all shots" timeline: every detected shot in source
order (no selection, no AI), which proves the export path into the editor. The AI-assisted rough
cut is built in `engine.py`."""

import re
from collections import Counter
from fractions import Fraction
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemind.core.errors import InvalidInputError
from cinemind.db.models import MediaAsset, Shot, Timeline, TimelineItem
from cinemind.export.sequence import export_rate
from cinemind.utils.timecode import STANDARD_RATES, rate_label

MixedRates = Literal["include", "exclude"]
_DIGITS = re.compile(r"(\d+)")


def natural_key(name: str) -> list[tuple[int, int | str]]:
    """Sort key that orders IMG_2 before IMG_10."""
    parts = _DIGITS.split(name.lower())
    return [(0, int(p)) if p.isdigit() else (1, p) for p in parts]


def shots_by_asset(session: Session, project_id: str) -> list[tuple[MediaAsset, list[Shot]]]:
    assets = session.scalars(select(MediaAsset).where(MediaAsset.project_id == project_id))
    found: list[tuple[MediaAsset, list[Shot]]] = []
    for asset in sorted(assets, key=lambda a: natural_key(a.filename)):
        shots = list(
            session.scalars(select(Shot).where(Shot.media_id == asset.id).order_by(Shot.index))
        )
        if shots:
            found.append((asset, shots))
    return found


def check_rate(fps: Fraction | None) -> None:
    if fps is not None and fps not in STANDARD_RATES:
        raise InvalidInputError(f"{rate_label(fps)} fps is not a supported timeline frame rate.")


def frame_size(assets: list[MediaAsset]) -> tuple[int, int]:
    """The picture size for a timeline of these clips (one entry per cut): the orientation most
    of them have (landscape on a tie), then the most common size of that orientation. Voting on
    the exact size alone would let a minority orientation win when the majority is split over
    sizes (4K and HD phone clips). 1920x1080 when no size is known."""
    known = [(a.width, a.height) for a in assets if a.width and a.height]
    if not known:
        return (1920, 1080)
    portrait = sum(h > w for w, h in known)
    wanted = [(w, h) for w, h in known if (h > w) == (portrait > len(known) - portrait)]
    sizes = Counter(wanted)
    return max(sizes, key=lambda s: (sizes[s], s))


def build_all_shots(
    session: Session,
    project_id: str,
    name: str,
    fps: Fraction | None = None,
    mixed_rates: MixedRates = "include",
) -> Timeline:
    """Every shot of every analysed clip, clips in file-name order, shots in source order.
    The timeline rate defaults to the rate most clips have."""
    clips = shots_by_asset(session, project_id)
    if not clips:
        raise InvalidInputError(
            "There are no shots yet. Import footage and wait for processing to finish."
        )
    check_rate(fps)
    votes = Counter(export_rate(asset) for asset, _ in clips)
    rate = fps or max(votes, key=lambda r: (votes[r], r))
    excluded: list[str] = []
    if mixed_rates == "exclude":
        excluded = [asset.filename for asset, _ in clips if export_rate(asset) != rate]
        clips = [(asset, shots) for asset, shots in clips if export_rate(asset) == rate]
        if not clips:
            raise InvalidInputError(f"No clip has a frame rate of {rate_label(rate)} fps.")
    width, height = frame_size([asset for asset, _ in clips])
    timeline = Timeline(
        project_id=project_id,
        name=name,
        kind="all_shots",
        fps_num=rate.numerator,
        fps_den=rate.denominator,
        width=width,
        height=height,
        params={
            "order": "file name, then shot order",
            "mixed_rates": mixed_rates,
            "rate_chosen_by": "user" if fps else "most common clip rate",
            "clip_rates": {rate_label(r): n for r, n in sorted(votes.items())},
            "excluded": excluded,
        },
    )
    position = 0
    for asset, shots in clips:
        for shot in shots:
            timeline.items.append(
                TimelineItem(
                    position=position,
                    media_id=asset.id,
                    shot_id=shot.id,
                    source_in_s=shot.start_s,
                    source_out_s=shot.end_s,
                )
            )
            position += 1
    timeline.params = {**timeline.params, "built_items": position}
    session.add(timeline)
    session.commit()
    return timeline
