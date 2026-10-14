"""Scenes: neighbouring shots grouped by how alike they look (SPEC section 5, stage 4).

Ours, no model of its own: the project's shots are put in order (clips by file name, as for the
"all shots" timeline, D-040; then shots in source order) and each shot is compared with the one
before it. Two signals: the cosine similarity of the shots' mean picture vectors (embed_visual)
and the intersection of their mean colour histograms. Their weighted mean (`[scenes]` weights) at
or above `join_similarity` keeps the shot in the scene of the one before; below it, a new scene
starts. The threshold and weights are conventions (no labelled scenes exist to set them).

The user's edits outrank similarity: `split` starts a scene at a shot, `join` keeps a shot with
the one before, `name` names the scene holding that shot. They are stored by shot id (stable
while the shot's frames do not change, D-039), so they come back however often the project is
grouped again. Grouping is project-wide, like actors: it runs after the last queued job.
"""

import hashlib
import json
from typing import Any

import numpy as np
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from cinemind.ai import embedder
from cinemind.core.config import Settings
from cinemind.core.embed_config import SceneConfig
from cinemind.core.errors import InvalidInputError, NotFoundError
from cinemind.db.analysis import Embedding, EmbeddingSet, Scene, SceneEdit, SceneRun
from cinemind.db.base import utcnow
from cinemind.db.models import MediaAsset, Shot
from cinemind.db.people import FeedbackEvent
from cinemind.pipeline.actors import lock
from cinemind.pipeline.shot_stages import stable_id
from cinemind.rough_cut.assembly import natural_key

Signals = dict[str, tuple[Any, Any]]  # shot id -> (mean picture vector | None, mean colour | None)


def ordered_shots(session: Session, project_id: str) -> list[Shot]:
    query = (
        select(Shot, MediaAsset.filename)
        .join(MediaAsset, MediaAsset.id == Shot.media_id)
        .where(MediaAsset.project_id == project_id)
    )
    rows = [(shot, name) for shot, name in session.execute(query)]
    rows.sort(key=lambda r: (natural_key(r[1]), r[0].media_id, r[0].index))
    return [shot for shot, _ in rows]


def shot_signals(session: Session, project_id: str, model: str) -> Signals:
    query = (
        select(Embedding.shot_id, Embedding.kind, Embedding.vector)
        .join(MediaAsset, MediaAsset.id == Embedding.media_id)
        .where(
            MediaAsset.project_id == project_id,
            Embedding.shot_id.is_not(None),
            ((Embedding.kind == "keyframe") & (Embedding.model == model))
            | (Embedding.kind == "color"),
        )
    )
    collected: dict[str, dict[str, list[Any]]] = {}
    for shot_id, kind, raw in session.execute(query):
        collected.setdefault(str(shot_id), {}).setdefault(kind, []).append(
            np.frombuffer(raw, dtype=np.float32)
        )
    out: Signals = {}
    for shot_id, kinds in collected.items():
        visual = None
        if kinds.get("keyframe"):
            mean = np.mean(kinds["keyframe"], axis=0)
            visual = mean / max(float(np.linalg.norm(mean)), 1e-12)
        color = np.mean(kinds["color"], axis=0) if kinds.get("color") else None
        out[shot_id] = (visual, color)
    return out


def similarity(a: tuple[Any, Any], b: tuple[Any, Any], cfg: SceneConfig) -> dict[str, Any]:
    """Both signals and their weighted mean (needs picture vectors; colour if both have it)."""
    parts: dict[str, Any] = {"visual": None, "color": None, "combined": None}
    total = weight = 0.0
    if a[0] is not None and b[0] is not None:
        parts["visual"] = round(float(np.dot(a[0], b[0])), 4)
        total += cfg.visual_weight * parts["visual"]
        weight += cfg.visual_weight
    if a[1] is not None and b[1] is not None:
        parts["color"] = round(float(np.minimum(a[1], b[1]).sum()), 4)
        total += cfg.color_weight * parts["color"]
        weight += cfg.color_weight
    # Colour alone is on another scale (0.1 to 0.4 inside one place on the user's footage), so
    # without picture vectors there is no combined value and no automatic join.
    if parts["visual"] is not None:
        parts["combined"] = round(total / weight, 4)
    return parts


def _edits(session: Session, project_id: str) -> dict[tuple[str, str], str]:
    rows = session.scalars(select(SceneEdit).where(SceneEdit.project_id == project_id))
    return {(e.shot_id, e.kind): e.value for e in rows}


def _basis(
    session: Session, settings: Settings, project_id: str, shots: list[Shot], model: str
) -> str:
    sets = session.execute(
        select(EmbeddingSet.media_id, EmbeddingSet.digest)
        .join(MediaAsset, MediaAsset.id == EmbeddingSet.media_id)
        .where(MediaAsset.project_id == project_id, EmbeddingSet.kind == "visual")
        .order_by(EmbeddingSet.media_id)
    ).all()
    edits = sorted([*key, value] for key, value in _edits(session, project_id).items())
    basis = [
        settings.scenes.model_dump(),
        model,
        [s.id for s in shots],
        [list(row) for row in sets],
        edits,
    ]
    return hashlib.sha256(json.dumps(basis).encode()).hexdigest()


def _decide(
    shot: Shot, parts: dict[str, Any], edits: dict[tuple[str, str], str], cfg: SceneConfig
) -> tuple[bool, str]:
    """(starts a new scene?, why) for a shot compared with the one before it."""
    if (shot.id, "split") in edits:
        return True, "split by you"
    if (shot.id, "join") in edits:
        return False, "joined by you"
    combined = parts["combined"]
    if combined is None:
        return True, "no picture vectors to compare"
    if combined >= cfg.join_similarity:
        return False, f"similar ({combined:.2f} ≥ {cfg.join_similarity})"
    return True, f"different ({combined:.2f} < {cfg.join_similarity})"


def group(session: Session, settings: Settings, project_id: str, force: bool = False) -> SceneRun:
    """Group the project's shots into scenes. Skipped when nothing it depends on changed (shots,
    picture vectors, edits, settings) unless `force`. The caller commits."""
    lock(session)
    cfg = settings.scenes
    model = embedder.choose_visual(settings).key
    shots = ordered_shots(session, project_id)
    digest = _basis(session, settings, project_id, shots, model)
    run = session.get(SceneRun, project_id)
    if run is not None:
        session.refresh(run)
    if run is not None and run.digest == digest and not force:
        return run
    signals = shot_signals(session, project_id, model)
    edits = _edits(session, project_id)
    groups: list[list[tuple[Shot, dict[str, Any]]]] = []
    previous: Shot | None = None
    for shot in shots:
        step: dict[str, Any] = {"shot_id": shot.id}
        if previous is None:
            starts, why = True, "first shot"
        else:
            parts = similarity(
                signals.get(previous.id, (None, None)), signals.get(shot.id, (None, None)), cfg
            )
            starts, why = _decide(shot, parts, edits, cfg)
            step |= parts
        step["decision"] = why
        if starts:
            groups.append([])
        groups[-1].append((shot, step))
        previous = shot

    session.execute(delete(Scene).where(Scene.project_id == project_id))
    session.flush()
    for index, members in enumerate(groups):
        names = [edits[(s.id, "name")] for s, _ in members if (s.id, "name") in edits]
        scene = Scene(
            id=stable_id(project_id, "scene", members[0][0].id),
            project_id=project_id,
            index=index,
            name=names[0] if names else f"Scene {index + 1:03d}",
            named=bool(names),
            shot_count=len(members),
            duration_s=round(sum(s.end_s - s.start_s for s, _ in members), 3),
            details={"steps": [step for _, step in members]},
        )
        session.add(scene)
        session.flush()
        # An explicit UPDATE: deleting the scenes above cleared `scene_id` in the database
        # (ON DELETE SET NULL) but not on the loaded shots, so assigning the same id again
        # would look like no change and never be written.
        session.execute(
            update(Shot).where(Shot.id.in_([s.id for s, _ in members])).values(scene_id=scene.id)
        )
    if run is None:
        run = SceneRun(project_id=project_id, digest=digest)
        session.add(run)
    run.digest, run.grouped_at = digest, utcnow()
    run.details = {
        "model": model,
        "settings": cfg.model_dump(),
        "order": "clips by file name, then shots in source order",
        "shots": len(shots),
        "scenes": len(groups),
        "shots_without_vectors": sum(1 for s in shots if signals.get(s.id, (None,))[0] is None),
        "edits": len(edits),
    }
    return run


# --- user edits -------------------------------------------------------------------------------


def _shot_in(session: Session, project_id: str, shot_id: str) -> Shot:
    shot = session.get(Shot, shot_id)
    asset = session.get(MediaAsset, shot.media_id) if shot else None
    if shot is None or asset is None or asset.project_id != project_id:
        raise NotFoundError("That shot is not in this project any more. Reload the page.")
    return shot


def set_boundary(
    session: Session, settings: Settings, project_id: str, shot_id: str, decision: str
) -> SceneRun:
    """Before `shot_id`: `split` (a scene starts here), `join` (stays with the shot before) or
    `auto` (the similarity decides again). Regroups; the caller commits."""
    if decision not in ("split", "join", "auto"):
        raise InvalidInputError("The decision must be split, join or auto.")
    lock(session)
    shots = ordered_shots(session, project_id)
    shot = _shot_in(session, project_id, shot_id)
    if shots and shots[0].id == shot.id and decision == "join":
        raise InvalidInputError("The first shot of the project has no shot before it to join.")
    session.execute(
        delete(SceneEdit).where(
            SceneEdit.project_id == project_id,
            SceneEdit.shot_id == shot.id,
            SceneEdit.kind.in_(("split", "join")),
        )
    )
    if decision != "auto":
        session.add(SceneEdit(project_id=project_id, shot_id=shot.id, kind=decision))
    session.add(
        FeedbackEvent(
            project_id=project_id,
            kind="scene_boundary",
            payload={"shot_id": shot.id, "decision": decision},
        )
    )
    session.flush()
    return group(session, settings, project_id, force=True)


def rename(
    session: Session, settings: Settings, project_id: str, scene_id: str, name: str
) -> Scene:
    """Name a scene (an empty name goes back to the number). Kept on the scene's shots, so it
    follows them through later groupings. The caller commits."""
    lock(session)
    scene = session.get(Scene, scene_id)
    if scene is None or scene.project_id != project_id:
        raise NotFoundError("That scene does not exist any more. Reload the page.")
    name = " ".join(name.split())
    if len(name) > 100:
        raise InvalidInputError("A scene name can have at most 100 characters.")
    # In project order, so the name sits on the scene's first shot and stays with that part of
    # the scene if it is split later.
    shot_ids = [s.id for s in ordered_shots(session, project_id) if s.scene_id == scene.id]
    session.execute(
        delete(SceneEdit).where(
            SceneEdit.project_id == project_id,
            SceneEdit.kind == "name",
            SceneEdit.shot_id.in_(shot_ids),
        )
    )
    if name and shot_ids:
        session.add(SceneEdit(project_id=project_id, shot_id=shot_ids[0], kind="name", value=name))
    session.add(
        FeedbackEvent(
            project_id=project_id, kind="scene_rename", payload={"scene_id": scene_id, "name": name}
        )
    )
    session.flush()
    group(session, settings, project_id, force=True)
    renamed = session.get(Scene, scene_id)
    if renamed is None:  # pragma: no cover - the first shot did not change, so neither did the id
        raise NotFoundError("That scene does not exist any more. Reload the page.")
    return renamed
