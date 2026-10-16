"""Take selection for the rough cut (SPEC section 11, P1-B): at most one take of each take group
goes into the cut. When a group's best take is among the candidates it takes the place of the
group's highest-ranked take; otherwise that highest-ranked take is used. The other takes become
swap suggestions. Every decision is written into the clip's reason."""

from typing import Any, Protocol, TypeVar

from sqlalchemy.orm import Session

from cinemind.db.models import Shot
from cinemind.pipeline import takes


class _Candidate(Protocol):
    shot: Shot
    rank: int
    slot: int | None
    reason: dict[str, Any]


C = TypeVar("C", bound=_Candidate)


def one_take_per_group(
    session: Session, project_id: str, candidates: list[C]
) -> tuple[list[C], list[C]]:
    """(candidates to use, in rank order with best takes moved up; other takes)."""
    groups = takes.groups_by_shot(session, project_id)
    by_shot = {c.shot.id: c for c in candidates}
    first: dict[str, C] = {}  # group id -> its highest-ranked candidate
    for c in candidates:
        if c.shot.id in groups:
            first.setdefault(groups[c.shot.id].id, c)
    pick = {gid: by_shot.get(groups[c.shot.id].best_shot_id or "") or c for gid, c in first.items()}
    kept: list[C] = []
    others: list[C] = []
    for c in candidates:
        group = groups.get(c.shot.id)
        if group is None:
            kept.append(c)
            continue
        number, count, used = group.index + 1, len(group.members), pick[group.id]
        if c is first[group.id]:
            if used.shot.id == group.best_shot_id:
                how = "chosen by you" if group.best_by == "you" else "suggested from its signals"
                note = f"Best take of take group {number} ({count} takes, {how})"
                if used is not c:
                    note += f", used in place of result {c.rank}"
            else:
                note = (
                    f"Take group {number} ({count} takes): its best take was not among the results"
                )
            used.reason["take"] = {"group": number, "takes": count,
                                   "best": used.shot.id == group.best_shot_id,
                                   "best_by": group.best_by,
                                   "in_place_of": c.rank if used is not c else None}  # fmt: skip
            used.reason["summary"] = f"{used.reason.get('summary', '')} {note}.".strip()
            used.slot = c.rank  # "score" order puts it where the replaced take was
            kept.append(used)
        if c is not used:
            c.reason["take"] = {"group": number, "takes": count, "used": used.shot.id}
            c.reason["summary"] = (
                f"{c.reason.get('summary', '')} Another take of take group {number} "
                f"(result {used.rank}) was chosen instead."
            ).strip()
            others.append(c)
    return kept, others
