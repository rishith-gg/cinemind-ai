"""Take groups for a project (SPEC P1-B): reads what the grouping needs from the database, runs
`take_signals.py`, stores the groups, and applies the user's corrections.

Like scenes and actors, grouping is project-wide: it runs after the last queued job, on request,
and after every correction. Corrections are stored by shot id (`take_edits`), so they come back
however often the project is grouped again. The groups are rewritten only when the result
changed (hash of the result and the settings)."""

import hashlib
import json
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, selectinload

from cinemind.ai import embedder
from cinemind.core.config import Settings
from cinemind.core.errors import InvalidInputError, NotFoundError
from cinemind.core.transcribe_config import is_uncertain
from cinemind.db.base import utcnow
from cinemind.db.models import AudioMetric, MediaAsset, QualityMetric, TranscriptSegment
from cinemind.db.people import FeedbackEvent
from cinemind.db.takes import TakeEdit, TakeGroup, TakeMember, TakeRun
from cinemind.pipeline import shot_marks
from cinemind.pipeline.actors import lock
from cinemind.pipeline.scenes import ordered_shots, shot_signals
from cinemind.pipeline.shot_stages import stable_id
from cinemind.pipeline.take_signals import ShotInfo, group, rank_takes, words_in
from cinemind.search.spoken import Word


def project_infos(session: Session, settings: Settings, project_id: str) -> list[ShotInfo]:
    """Every shot of the project in project order, with the signals take detection uses."""
    shots = ordered_shots(session, project_id)
    model = embedder.choose_visual(settings).key
    pictures = shot_signals(session, project_id, model)
    assets = {
        a.id: a
        for a in session.scalars(select(MediaAsset).where(MediaAsset.project_id == project_id))
    }
    words: dict[str, list[Word]] = {}
    unclear: dict[str, list[float]] = {}
    query = (
        select(TranscriptSegment)
        .where(TranscriptSegment.media_id.in_(assets))
        .options(selectinload(TranscriptSegment.words))
        .order_by(TranscriptSegment.media_id, TranscriptSegment.start_s)
    )
    for seg in session.scalars(query):
        if is_uncertain(seg.avg_logprob, seg.compression_ratio):
            unclear.setdefault(seg.media_id, []).append((seg.start_s + seg.end_s) / 2)
        else:
            words.setdefault(seg.media_id, []).extend(
                Word(w.start_s, w.end_s, w.word) for w in seg.words
            )
    quality = {
        q.shot_id: q
        for q in session.scalars(select(QualityMetric).where(QualityMetric.media_id.in_(assets)))
    }
    audio = dict(
        session.execute(
            select(AudioMetric.media_id, AudioMetric.score).where(AudioMetric.media_id.in_(assets))
        ).all()
    )
    rejected = shot_marks.rejected(session, project_id)
    infos: list[ShotInfo] = []
    for position, shot in enumerate(shots):
        q = quality.get(shot.id)
        infos.append(
            ShotInfo(
                id=shot.id,
                media_id=shot.media_id,
                filename=assets[shot.media_id].filename if shot.media_id in assets else "",
                position=position,
                start_s=shot.start_s,
                end_s=shot.end_s,
                picture=pictures.get(shot.id, (None, None))[0],
                words=words_in(words.get(shot.media_id, []), shot.start_s, shot.end_s),
                uncertain=sum(
                    1 for mid in unclear.get(shot.media_id, []) if shot.start_s <= mid < shot.end_s
                ),
                focus=q.sharpness_score if q else None,
                exposure=q.exposure_score if q else None,
                audio=audio.get(shot.media_id),
                rejected=shot.id in rejected,
            )
        )
    return infos


def _edits(session: Session, project_id: str) -> tuple[dict[str, int], set[frozenset[str]]]:
    """The user's best-take picks (shot id -> order of the edit) and pairs kept apart."""
    best: dict[str, int] = {}
    apart: set[frozenset[str]] = set()
    for e in session.scalars(select(TakeEdit).where(TakeEdit.project_id == project_id)):
        if e.kind == "best":
            best[e.shot_id] = e.id
        else:
            apart.add(frozenset((e.shot_id, e.other_id)))
    return best, apart


def regroup(session: Session, settings: Settings, project_id: str) -> TakeRun:
    """Group the project's shots into takes; rewrites the groups only when the result changed.
    The caller commits."""
    lock(session)
    cfg = settings.takes
    infos = project_infos(session, settings, project_id)
    best_edits, apart = _edits(session, project_id)
    groups, pairs = group(infos, cfg, apart)
    result: list[dict[str, Any]] = []
    for members in groups:
        picks = [infos[i].id for i in members if infos[i].id in best_edits]
        user_best = max(picks, key=lambda s: best_edits[s]) if picks else None
        kind, ranked, best_by = rank_takes(members, infos, pairs, cfg, user_best)
        links = [
            pairs[(i, j)].as_dict(infos) for x, i in enumerate(members) for j in members[x + 1 :]
        ]
        result.append(
            {
                "id": stable_id(project_id, "take", infos[members[0]].id),
                "kind": kind,
                "best": ranked[0].info.id if best_by != "none" else None,
                "best_by": best_by,
                "pairs": links,
                "members": [
                    {
                        "shot_id": r.info.id,
                        "score": r.score,
                        "signals": r.signals,
                        "notes": r.notes,
                        "text": r.info.text,
                    }  # fmt: skip
                    for r in ranked
                ],
            }
        )
    model = embedder.choose_visual(settings).key
    digest = hashlib.sha256(
        json.dumps([cfg.model_dump(), model, result], sort_keys=True).encode()
    ).hexdigest()
    run = session.get(TakeRun, project_id)
    if run is not None:
        session.refresh(run)
        if run.digest == digest:
            return run
    # Through the ORM, so members loaded earlier in this session leave its identity map too.
    for old in session.scalars(select(TakeGroup).where(TakeGroup.project_id == project_id)):
        session.delete(old)
    session.flush()
    for index, g in enumerate(result):
        row = TakeGroup(
            id=g["id"],
            project_id=project_id,
            index=index,
            kind=g["kind"],
            best_shot_id=g["best"],
            best_by=g["best_by"],
            details={"pairs": g["pairs"]},
        )
        for rank, m in enumerate(g["members"], start=1):
            row.members.append(
                TakeMember(
                    shot_id=m["shot_id"],
                    rank=rank,
                    score=m["score"],
                    signals=m["signals"],
                    notes=m["notes"],
                    text=m["text"],
                )
            )
        session.add(row)
    if run is None:
        run = TakeRun(project_id=project_id, digest=digest)
        session.add(run)
    run.digest, run.grouped_at = digest, utcnow()
    run.details = {
        "picture_model": model,
        "settings": cfg.model_dump(),
        "order": "clips by file name, then shots in source order",
        "shots": len(infos),
        "shots_with_speech": sum(1 for i in infos if len(i.norm) >= cfg.min_words),
        "shots_without_vectors": sum(1 for i in infos if i.picture is None),
        "groups": len(result),
        "shots_in_groups": sum(len(g["members"]) for g in result),
        "edits": {"best": len(best_edits), "apart": len(apart)},
    }
    session.flush()
    return run


# --- what other parts of the app read --------------------------------------------------------


def groups_by_shot(session: Session, project_id: str) -> dict[str, TakeGroup]:
    """Each grouped shot's take group."""
    query = (
        select(TakeGroup)
        .where(TakeGroup.project_id == project_id)
        .options(selectinload(TakeGroup.members))
    )
    return {m.shot_id: g for g in session.scalars(query) for m in g.members}


def project_of_grouped_shot(session: Session, shot_id: str) -> str | None:
    """The project of the take group holding `shot_id`, or None when it is in none."""
    return session.scalar(
        select(TakeGroup.project_id)
        .join(TakeMember, TakeMember.group_id == TakeGroup.id)
        .where(TakeMember.shot_id == shot_id)
    )


# --- user corrections ------------------------------------------------------------------------


def _group_of(session: Session, project_id: str, shot_id: str) -> TakeGroup:
    found = groups_by_shot(session, project_id).get(shot_id)
    if found is None:
        raise NotFoundError("That shot is not in a take group any more. Reload the page.")
    return found


def set_best(
    session: Session, settings: Settings, project_id: str, shot_id: str, best: bool
) -> TakeRun:
    """Make `shot_id` the best take of its group (`best`), or let the signals decide again for
    that group. Regroups; the caller commits."""
    lock(session)
    take_group = _group_of(session, project_id, shot_id)
    if best and shot_id in shot_marks.rejected(session, project_id):
        raise InvalidInputError(
            "This take is rejected. Clear the reject first to make it the best."
        )
    session.execute(
        delete(TakeEdit).where(
            TakeEdit.project_id == project_id,
            TakeEdit.kind == "best",
            TakeEdit.shot_id.in_([m.shot_id for m in take_group.members]),
        )
    )
    if best:
        session.add(TakeEdit(project_id=project_id, shot_id=shot_id, kind="best"))
    session.add(
        FeedbackEvent(
            project_id=project_id,
            kind="take_best",
            payload={
                "shot_id": shot_id,
                "best": best,
                "group": take_group.id,
                "was": take_group.best_shot_id,
                "was_by": take_group.best_by,
            },  # fmt: skip
        )
    )
    session.flush()
    return regroup(session, settings, project_id)


def set_apart(
    session: Session, settings: Settings, project_id: str, shot_id: str, apart: bool
) -> TakeRun:
    """`apart`: the shot is not a take of the others in its group (kept apart from each of them
    from now on). Not `apart`: forget every such answer about the shot. Regroups; the caller
    commits."""
    lock(session)
    if apart:
        take_group = _group_of(session, project_id, shot_id)
        others = [m.shot_id for m in take_group.members if m.shot_id != shot_id]
        _, known = _edits(session, project_id)
        for other in others:
            if frozenset((shot_id, other)) not in known:
                session.add(
                    TakeEdit(project_id=project_id, shot_id=shot_id, kind="apart", other_id=other)
                )
        payload: dict[str, Any] = {"shot_id": shot_id, "apart_from": others, "group": take_group.id}
    else:
        session.execute(
            delete(TakeEdit).where(
                TakeEdit.project_id == project_id,
                TakeEdit.kind == "apart",
                or_(TakeEdit.shot_id == shot_id, TakeEdit.other_id == shot_id),
            )
        )
        payload = {"shot_id": shot_id, "undo": True}
    session.add(FeedbackEvent(project_id=project_id, kind="take_apart", payload=payload))
    session.flush()
    return regroup(session, settings, project_id)


def kept_apart(session: Session, project_id: str) -> list[str]:
    """Shots the user took out of a take group, oldest first."""
    query = (
        select(TakeEdit.shot_id)
        .where(TakeEdit.project_id == project_id, TakeEdit.kind == "apart")
        .order_by(TakeEdit.id)
    )
    return list(dict.fromkeys(session.scalars(query)))
