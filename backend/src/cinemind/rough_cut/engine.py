"""The AI-assisted rough cut (SPEC section 11): brief -> candidates -> filter -> select -> trim
-> fit duration -> order -> timeline, with the reason for every clip stored on it (rule 6).

- Candidates: the hybrid search and ranking of Phases 9 and 10 with the subject of the brief as
  the query (rejected shots are already left out there; picture duplicates are pushed down by
  MMR). A brief without a subject takes every shot, ranked by the user's marks and quality.
- Filter: shots under `[rough_cut] min_quality` and shots too short to use, each listed with why.
- Select and fit: in ranked order, each shot is trimmed (`trim.py`) and added while the cut
  stays within the target plus the tolerance; a clip without speech may be shortened to fill
  the end. Usable shots not taken are kept as swap suggestions.
- Order: by source (file name, then time), by scene, or by rank.
Nothing here is a learned model: the choices are search, ranking and our rules, and the timeline
is a starting point for the editor, labelled "AI-assisted rough cut. Human review required."
"""

import time
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemind.core.config import Settings
from cinemind.core.errors import InvalidInputError
from cinemind.core.rough_cut_config import Order
from cinemind.db.analysis import Scene
from cinemind.db.models import MediaAsset, QualityMetric, Shot, Timeline, TimelineItem
from cinemind.export.sequence import export_rate
from cinemind.pipeline import shot_marks
from cinemind.rough_cut import BANNER
from cinemind.rough_cut.assembly import check_rate, frame_size, natural_key
from cinemind.rough_cut.brief import parse
from cinemind.rough_cut.trim import Trim, trim_shot
from cinemind.search import hybrid, ranking
from cinemind.search.hybrid import Filters, Fused
from cinemind.search.ranking import Ranked
from cinemind.search.spoken import spoken_lines

LIST_NAMES = {
    "keyword": "spoken words",
    "labels": "labels",
    "text": "meaning of speech",
    "visual": "picture",
}


@dataclass
class Request:
    brief: str
    target_s: float | None = None
    order: Order | None = None
    actor_id: str | None = None
    scene_id: str | None = None
    name: str | None = None
    fps: Fraction | None = None


@dataclass
class Candidate:
    ranked: Ranked
    rank: int
    shot: Shot
    asset: MediaAsset
    quality: float | None
    reason: dict[str, Any] = field(default_factory=lambda: {})


def _ranked(
    session: Session, settings: Settings, project_id: str, query: str, filters: Filters
) -> tuple[list[Ranked], dict[str, Any]]:
    cfg = settings.rough_cut
    weights = settings.ranking.weights
    if query:
        search = settings.search.model_copy(update={"max_results": cfg.candidates})
        outcome, ranked = ranking.run_ranked(
            session,
            settings.model_copy(update={"search": search}),
            project_id,
            hybrid.Query(text=query, filters=filters),
            weights,
        )
        info = {"lists": outcome.lists, "unavailable": outcome.unavailable}
        if not ranked and outcome.unavailable and not any(outcome.lists.values()):
            raise InvalidInputError(
                "The brief could not be searched: " + " ".join(outcome.unavailable.values())
            )
        return ranked, info
    # No subject: every shot the filters keep, best marked and best quality first.
    keep = hybrid.allowed_shots(session, project_id, filters)
    rows = session.execute(
        select(Shot.id, QualityMetric.score)
        .join(MediaAsset, MediaAsset.id == Shot.media_id)
        .outerjoin(QualityMetric, QualityMetric.shot_id == Shot.id)
        .where(MediaAsset.project_id == project_id)
    ).all()
    hidden = shot_marks.rejected(session, project_id)
    chosen = shot_marks.selected(session, project_id)
    ids = [
        str(shot_id)
        for shot_id, _ in sorted(
            rows, key=lambda r: (r[0] not in chosen, -(r[1] or 0.0), str(r[0]))
        )
        if shot_id not in hidden and (keep is None or shot_id in keep)
    ][: cfg.candidates]
    fused = [Fused(shot_id, 1.0) for shot_id in ids]
    return ranking.rank(session, settings, project_id, fused, weights), {"lists": {}}


def _why(c: Candidate, total: int) -> dict[str, Any]:
    r = c.ranked
    found_by = {name: rank for name, (_, rank, _) in r.fused.parts.items()}
    line = next((i.text for i, _, _ in r.fused.parts.values() if i.text), None)
    labels = r.fused.parts["labels"][0].matched if "labels" in r.fused.parts else []
    pieces = [f"Result {c.rank} of {total}"]
    if found_by:
        pieces.append(
            "found by "
            + ", ".join(f"{LIST_NAMES.get(n, n)} (#{k})" for n, k in sorted(found_by.items()))
        )
    pieces.append("quality not measured" if c.quality is None else f"quality {c.quality:.2f}")
    selection = r.breakdown.get("selection", (0.0, 0.0, 0.0))[0]
    if selection >= 1:
        pieces.append("selected by you")
    elif selection > 0:
        pieces.append(f"{round(selection * 5)} star(s)")
    return {
        "rank": c.rank,
        "of": total,
        "final": r.final,
        "breakdown": {
            name: {"value": v, "weight": w, "contribution": x}
            for name, (v, w, x) in r.breakdown.items()
        },
        "found_by": found_by,
        "matched_line": line,
        "matched_labels": labels,
        "duplicate_of": r.duplicate_of,
        "notes": r.notes,
        "jump_s": r.fused.jump_s if r.fused.parts else (c.shot.start_s + c.shot.end_s) / 2,
        "summary": "; ".join(pieces) + ".",
    }


def _candidates(session: Session, ranked: list[Ranked]) -> list[Candidate]:
    ids = [r.fused.shot_id for r in ranked]
    shots = {s.id: s for s in session.scalars(select(Shot).where(Shot.id.in_(ids)))}
    assets = {
        a.id: a
        for a in session.scalars(
            select(MediaAsset).where(MediaAsset.id.in_({s.media_id for s in shots.values()}))
        )
    }
    quality = dict(
        session.execute(
            select(QualityMetric.shot_id, QualityMetric.score).where(QualityMetric.shot_id.in_(ids))
        ).all()
    )
    found: list[Candidate] = []
    for position, r in enumerate(ranked, start=1):
        shot = shots.get(r.fused.shot_id)
        if shot is None or shot.media_id not in assets:
            continue
        found.append(Candidate(r, position, shot, assets[shot.media_id], quality.get(shot.id)))
    for c in found:
        c.reason = _why(c, len(found))
    return found


def _order_key(order: Order, scenes: dict[str, int]) -> Any:
    def key(pair: tuple[Candidate, Trim]) -> tuple[Any, ...]:
        c, trim = pair
        source = (natural_key(c.asset.filename), c.asset.id, trim.in_s)
        if order == "score":
            return (c.rank,)
        if order == "scene":
            return (scenes.get(c.shot.scene_id or "", 1 << 30), *source)
        return source

    return key


def _left(c: Candidate, why: str) -> dict[str, Any]:
    return {"shot_id": c.shot.id, "filename": c.asset.filename, "start_s": c.shot.start_s,
            "rank": c.rank, "why": why}  # fmt: skip


def build_rough_cut(
    session: Session, settings: Settings, project_id: str, req: Request
) -> Timeline:
    began = time.perf_counter()
    cfg = settings.rough_cut
    check_rate(req.fps)
    brief = parse(req.brief)
    target = req.target_s or brief.target_s or cfg.default_target_s
    if not 1 <= target <= 3600:
        raise InvalidInputError("The length must be between 1 second and 60 minutes.")
    order = req.order or brief.order or cfg.order
    filters = Filters(actor_id=req.actor_id, scene_id=req.scene_id)
    ranked, search_info = _ranked(session, settings, project_id, brief.query, filters)
    candidates = _candidates(session, ranked)
    if not candidates:
        raise InvalidInputError(
            "Nothing in the footage matched the brief. Try other words, or remove the person "
            "or scene filter."
        )
    lines = spoken_lines(session, {c.asset.id for c in candidates})

    picks: list[tuple[Candidate, Trim]] = []
    left_out: list[dict[str, Any]] = []
    spare: list[Candidate] = []
    total = 0.0
    most = target * (1 + cfg.tolerance)
    for c in candidates:
        if c.quality is not None and c.quality < cfg.min_quality:
            left_out.append(_left(c, f"quality {c.quality:.2f} is below {cfg.min_quality:g}"))
            continue
        if c.shot.end_s - c.shot.start_s < cfg.min_clip_s:
            left_out.append(_left(c, f"shorter than {cfg.min_clip_s:g} s"))
            continue
        if total >= target * (1 - cfg.tolerance):
            spare.append(c)
            continue
        shot_lines = lines.get(c.asset.id, [])
        jump = float(c.reason["jump_s"])
        trim = trim_shot(c.shot.start_s, c.shot.end_s, jump, shot_lines, cfg, most - total)
        if trim is None:
            spare.append(c)
            continue
        c.reason["trim"] = trim.as_dict()
        picks.append((c, trim))
        total += trim.length
    if not picks:
        raise InvalidInputError(
            "No matching shot was usable: they were all below the quality limit, too short, or "
            "too long for the length asked for. See the settings under [rough_cut]."
        )

    scenes = {
        s.id: s.index for s in session.scalars(select(Scene).where(Scene.project_id == project_id))
    }
    picks.sort(key=_order_key(order, scenes))
    votes = Counter(export_rate(c.asset) for c, _ in picks)
    rate = req.fps or max(votes, key=lambda r: (votes[r], r))
    width, height = frame_size([c.asset for c, _ in picks])
    alternatives = [
        {"shot_id": c.shot.id, "filename": c.asset.filename, "reason": c.reason}
        for c in spare[: cfg.alternatives]
    ]
    timeline = Timeline(
        project_id=project_id,
        name=(req.name or "").strip() or f"Rough cut: {' '.join(brief.text.split())[:80]}",
        kind="rough_cut",
        fps_num=rate.numerator,
        fps_den=rate.denominator,
        width=width,
        height=height,
        params={
            "banner": BANNER,
            "brief": brief.text,
            "understood": brief.understood,
            "query": brief.query,
            "target_s": target,
            "target_from": "you" if req.target_s else "brief" if brief.target_s else "default",
            "order": order,
            "filters": {"actor_id": req.actor_id, "scene_id": req.scene_id},
            "search": search_info,
            "weights": settings.ranking.weights,
            "settings": cfg.model_dump(),
            "candidates": len(candidates),
            "left_out": left_out,
            "alternatives": alternatives,
            "rate_chosen_by": "user" if req.fps else "most common rate among the chosen clips",
            "built_items": len(picks),
            "built_s": round(time.perf_counter() - began, 3),
        },
    )
    for position, (c, trim) in enumerate(picks):
        timeline.items.append(
            TimelineItem(
                position=position,
                media_id=c.asset.id,
                shot_id=c.shot.id,
                source_in_s=trim.in_s,
                source_out_s=trim.out_s,
                reason=c.reason,
            )
        )
    session.add(timeline)
    session.commit()
    return timeline
