"""Scenes (editable), tag suggestions with the user's reviews, embedding state and vector
indexes. Scenes and tags are suggestions; every response carries the numbers behind them."""

from typing import Any, cast

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemind.ai import embedder, tagger
from cinemind.ai.embedder import PULL_HINT
from cinemind.api.analysis_schemas import (
    BoundaryIn,
    EmbeddingStatusOut,
    EmbedStatus,
    MediaTagsOut,
    SceneOut,
    SceneRename,
    SceneSettingsOut,
    SceneShotOut,
    ScenesOut,
    ShotTagsOut,
    TagCountOut,
    TagDecision,
    TagOut,
    TagReviewIn,
    TagSource,
    TagStatus,
    VectorIndexOut,
)
from cinemind.api.deps import SessionDep, SettingsDep
from cinemind.api.media import ERRORS, get_asset, get_project
from cinemind.core.config import Settings
from cinemind.core.embed_config import VISUAL_MODELS
from cinemind.core.errors import NotFoundError
from cinemind.db.analysis import EmbeddingSet, Scene, SceneEdit, SceneRun, Tag, VectorIndexRow
from cinemind.db.models import Keyframe, MediaAsset, Shot
from cinemind.pipeline import scenes as scene_service
from cinemind.pipeline import shot_marks, tag_review
from cinemind.search import vector_index

router = APIRouter(tags=["analysis"])

_EMBED_MESSAGES = {
    "model_missing": f"The picture and text models are not downloaded. {PULL_HINT}",
    "no_video": "This clip has no picture, so it has no tags.",
    "no_speech": "No speech was transcribed in this clip.",
    "no_transcript": "There is no transcript yet (see the Transcript panel).",
    "pending": "Not analysed yet. Press Reprocess to add tags.",
}


# --- scenes -----------------------------------------------------------------------------------


def _scenes_out(session: Session, settings: Settings, project_id: str) -> ScenesOut:
    shots = scene_service.ordered_shots(session, project_id)
    names = dict(
        session.execute(
            select(MediaAsset.id, MediaAsset.filename).where(MediaAsset.project_id == project_id)
        ).all()
    )
    first_keyframe: dict[str, str] = {}
    shot_ids = [s.id for s in shots]
    if shot_ids:
        query = select(Keyframe.shot_id, Keyframe.id).where(Keyframe.shot_id.in_(shot_ids))
        for shot_id, keyframe_id in session.execute(query.order_by(Keyframe.slot.desc())):
            first_keyframe[shot_id] = keyframe_id  # last write wins: the lowest slot
    edits = {
        e.shot_id: e.kind
        for e in session.scalars(
            select(SceneEdit).where(
                SceneEdit.project_id == project_id, SceneEdit.kind.in_(("split", "join"))
            )
        )
    }
    steps: dict[str, dict[str, Any]] = {}
    scene_rows = list(
        session.scalars(select(Scene).where(Scene.project_id == project_id).order_by(Scene.index))
    )
    for scene in scene_rows:
        for step in scene.details.get("steps", []):
            steps[str(step["shot_id"])] = step
    marks = shot_marks.marks_for(session, shot_ids)
    by_scene: dict[str, list[SceneShotOut]] = {}
    for shot in shots:
        step = steps.get(shot.id, {})
        edit = edits.get(shot.id)
        by_scene.setdefault(shot.scene_id or "", []).append(
            SceneShotOut(
                shot_id=shot.id,
                media_id=shot.media_id,
                filename=names.get(shot.media_id, ""),
                index=shot.index,
                start_s=shot.start_s,
                end_s=shot.end_s,
                keyframe_id=first_keyframe.get(shot.id),
                visual=step.get("visual"),
                color=step.get("color"),
                combined=step.get("combined"),
                decision=str(step.get("decision", "not grouped yet")),
                edit=edit if edit in ("split", "join") else None,
                mark=marks[shot.id].mark if shot.id in marks else None,  # pyright: ignore[reportArgumentType]
                stars=marks[shot.id].stars if shot.id in marks else 0,
            )
        )
    run = session.get(SceneRun, project_id)
    spec = embedder.choose_visual(settings)
    missing = not spec.ready(settings.models_path)
    return ScenesOut(
        scenes=[
            SceneOut(
                id=s.id,
                index=s.index,
                name=s.name,
                named=s.named,
                shot_count=s.shot_count,
                duration_s=s.duration_s,
                shots=by_scene.get(s.id, []),
            )
            for s in scene_rows
        ],
        ungrouped=by_scene.get("", []),
        grouped_at=run.grouped_at if run else None,
        details=run.details if run else {},
        settings=SceneSettingsOut(**settings.scenes.model_dump()),
        model_missing=missing,
        message=(
            f"The picture model '{spec.key}' is not downloaded, so shots cannot be compared. "
            f"{PULL_HINT}"
            if missing
            else None
        ),
    )


@router.get(
    "/api/projects/{project_id}/scenes",
    response_model=ScenesOut,
    responses=ERRORS,
    operation_id="listScenes",
)
def list_scenes(project_id: str, session: SessionDep, settings: SettingsDep) -> ScenesOut:
    get_project(session, project_id)
    return _scenes_out(session, settings, project_id)


@router.post(
    "/api/projects/{project_id}/scenes/regroup",
    response_model=ScenesOut,
    responses=ERRORS,
    operation_id="regroupScenes",
)
def regroup_scenes(project_id: str, session: SessionDep, settings: SettingsDep) -> ScenesOut:
    get_project(session, project_id)
    scene_service.group(session, settings, project_id, force=True)
    session.commit()
    return _scenes_out(session, settings, project_id)


@router.put(
    "/api/projects/{project_id}/scenes/boundaries",
    response_model=ScenesOut,
    responses=ERRORS,
    operation_id="setSceneBoundary",
)
def set_scene_boundary(
    project_id: str, body: BoundaryIn, session: SessionDep, settings: SettingsDep
) -> ScenesOut:
    """Before a shot: start a scene (`split`), keep it with the shot before (`join`), or let
    the similarity decide again (`auto`)."""
    get_project(session, project_id)
    scene_service.set_boundary(session, settings, project_id, body.shot_id, body.decision)
    session.commit()
    return _scenes_out(session, settings, project_id)


@router.patch(
    "/api/scenes/{scene_id}", response_model=ScenesOut, responses=ERRORS, operation_id="renameScene"
)
def rename_scene(
    scene_id: str, body: SceneRename, session: SessionDep, settings: SettingsDep
) -> ScenesOut:
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise NotFoundError("That scene does not exist any more. Reload the page.")
    project_id = scene.project_id
    scene_service.rename(session, settings, project_id, scene_id, body.name)
    session.commit()
    return _scenes_out(session, settings, project_id)


# --- tags -------------------------------------------------------------------------------------


def _tag_out(tag: Tag, review: str | None) -> TagOut:
    return TagOut(
        name=tag.name,
        label=tag.label,
        group=tag.group,
        group_label=tagger.GROUP_LABELS.get(tag.group, tag.group),
        source=cast(TagSource, tag.source),
        score=tag.score,
        threshold=tag.threshold,
        status=cast(TagStatus, tag.status),
        review=cast(TagDecision | None, review),
        visible=tag_review.visible(tag.status, review),
        details=tag.details,
    )


def _media_tags(session: Session, settings: Settings, media_id: str) -> MediaTagsOut:
    asset = get_asset(session, media_id)
    shots = list(
        session.scalars(select(Shot).where(Shot.media_id == asset.id).order_by(Shot.index))
    )
    tags = list(session.scalars(select(Tag).where(Tag.media_id == asset.id).order_by(Tag.id)))
    reviews = tag_review.reviews_for(session, [s.id for s in shots])
    per_shot: dict[str, list[TagOut]] = {}
    for tag in tags:
        out = _tag_out(tag, reviews.get((tag.shot_id, tag.name)))
        per_shot.setdefault(tag.shot_id, []).append(out)
    state = session.get(EmbeddingSet, (asset.id, "visual"))
    status = state.status if state else "pending"
    stored = state.model if state and state.model in VISUAL_MODELS else None
    spec = embedder.choose_visual(settings, stored)
    calibration = tagger.calibration_for(spec)
    return MediaTagsOut(
        status=cast(EmbedStatus, status),
        model=state.model if state else None,
        message=_EMBED_MESSAGES.get(status),
        calibrated=calibration.get("date") if calibration else None,
        calibration_source=calibration.get("source") if calibration else None,
        shots=[
            ShotTagsOut(
                shot_id=s.id,
                index=s.index,
                start_s=s.start_s,
                end_s=s.end_s,
                tags=per_shot.get(s.id, []),
            )
            for s in shots
        ],
    )


@router.get(
    "/api/media/{media_id}/tags",
    response_model=MediaTagsOut,
    responses=ERRORS,
    operation_id="listMediaTags",
)
def list_media_tags(media_id: str, session: SessionDep, settings: SettingsDep) -> MediaTagsOut:
    return _media_tags(session, settings, media_id)


@router.put(
    "/api/tags/review", response_model=MediaTagsOut, responses=ERRORS, operation_id="reviewTag"
)
def review_tag(body: TagReviewIn, session: SessionDep, settings: SettingsDep) -> MediaTagsOut:
    shot = tag_review.set_review(session, body.shot_id, body.name, body.decision)
    session.commit()
    return _media_tags(session, settings, shot.media_id)


@router.get(
    "/api/projects/{project_id}/tags",
    response_model=list[TagCountOut],
    responses=ERRORS,
    operation_id="listProjectTags",
)
def list_project_tags(project_id: str, session: SessionDep) -> list[TagCountOut]:
    """Tags shown somewhere in the project (approved, or above the threshold and not
    rejected), with the number of shots each is shown on."""
    get_project(session, project_id)
    query = (
        select(Tag)
        .join(MediaAsset, MediaAsset.id == Tag.media_id)
        .where(MediaAsset.project_id == project_id)
    )
    tags = list(session.scalars(query))
    reviews = tag_review.reviews_for(session, list({t.shot_id for t in tags}))
    shots: dict[str, set[str]] = {}
    first: dict[str, Tag] = {}
    for tag in tags:
        if tag_review.visible(tag.status, reviews.get((tag.shot_id, tag.name))):
            shots.setdefault(tag.name, set()).add(tag.shot_id)
            first.setdefault(tag.name, tag)
    return [
        TagCountOut(
            name=name,
            label="Clear faces" if name == "faces" else first[name].label,
            group=first[name].group,
            shots=len(ids),
        )
        for name, ids in sorted(shots.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]


# --- embeddings and indexes ---------------------------------------------------------------------


@router.get(
    "/api/media/{media_id}/embeddings",
    response_model=list[EmbeddingStatusOut],
    responses=ERRORS,
    operation_id="listMediaEmbeddings",
)
def list_media_embeddings(media_id: str, session: SessionDep) -> list[EmbeddingStatusOut]:
    asset = get_asset(session, media_id)
    out: list[EmbeddingStatusOut] = []
    for kind in ("visual", "text"):
        row = session.get(EmbeddingSet, (asset.id, kind))
        status = row.status if row else "pending"
        out.append(
            EmbeddingStatusOut(
                kind=kind,
                status=cast(EmbedStatus, status),
                model=row.model if row else None,
                count=row.count if row else 0,
                message=_EMBED_MESSAGES.get(status),
            )
        )
    return out


def _indexes(session: Session, settings: Settings, project_id: str) -> list[VectorIndexOut]:
    out: list[VectorIndexOut] = []
    records = session.scalars(
        select(VectorIndexRow)
        .where(VectorIndexRow.project_id == project_id)
        .order_by(VectorIndexRow.kind, VectorIndexRow.model)
    )
    for record in records:
        current = vector_index.current_digest(session, project_id, record.kind, record.model)
        path = settings.project_dir(project_id) / record.path
        out.append(
            VectorIndexOut(
                kind=record.kind,
                model=record.model,
                backend=record.backend,
                dim=record.dim,
                count=record.count,
                built_at=record.built_at,
                up_to_date=current == record.digest
                and path.is_file()
                and record.backend == vector_index.choose_backend(settings.embed.index_backend),
            )
        )
    return out


@router.get(
    "/api/projects/{project_id}/index",
    response_model=list[VectorIndexOut],
    responses=ERRORS,
    operation_id="listVectorIndexes",
)
def list_vector_indexes(
    project_id: str, session: SessionDep, settings: SettingsDep
) -> list[VectorIndexOut]:
    get_project(session, project_id)
    return _indexes(session, settings, project_id)


@router.post(
    "/api/projects/{project_id}/index/rebuild",
    response_model=list[VectorIndexOut],
    responses=ERRORS,
    operation_id="rebuildVectorIndexes",
)
def rebuild_vector_indexes(
    project_id: str, session: SessionDep, settings: SettingsDep
) -> list[VectorIndexOut]:
    """Rebuild every vector index of the project from the database."""
    get_project(session, project_id)
    vector_index.rebuild_project(session, settings, project_id, force=True)
    session.commit()
    return _indexes(session, settings, project_id)
