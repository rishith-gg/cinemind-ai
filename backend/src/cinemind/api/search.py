"""Hybrid search (keyword, labels, transcript meaning, pictures; fused with RRF), search by
picture, and the user's relevance judgments of results."""

from typing import Annotated

import cv2
import numpy as np
from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from cinemind.api.deps import SessionDep, SettingsDep
from cinemind.api.media import ERRORS, get_project
from cinemind.api.schemas import TextPart
from cinemind.api.search_schemas import (
    JudgmentIn,
    JudgmentOut,
    ListHit,
    SearchFilters,
    SearchOut,
    SearchRequest,
    SearchResult,
)
from cinemind.core.config import Settings
from cinemind.core.errors import InvalidInputError, NotFoundError, PayloadTooLargeError
from cinemind.core.search_config import RETRIEVERS
from cinemind.db.analysis import Scene, SearchJudgment, normal_query
from cinemind.db.base import utcnow
from cinemind.db.models import Keyframe, MediaAsset, QualityMetric, Shot
from cinemind.search import hybrid
from cinemind.utils.pictures import picture_size

router = APIRouter(tags=["search"])

USER = "user"
MAX_IMAGE_MB = 15
MAX_IMAGE_PIXELS = 40_000_000


def _filters(body: SearchFilters) -> hybrid.Filters:
    return hybrid.Filters(**body.model_dump())


def _out(
    session: Session,
    settings: Settings,
    project_id: str,
    outcome: hybrid.Outcome,
    text: str | None,
    like: str | None,
) -> SearchOut:
    ids = [r.shot_id for r in outcome.results]
    rows = session.execute(
        select(Shot, MediaAsset.filename, Scene.name, QualityMetric.score)
        .join(MediaAsset, MediaAsset.id == Shot.media_id)
        .outerjoin(Scene, Scene.id == Shot.scene_id)
        .outerjoin(QualityMetric, QualityMetric.shot_id == Shot.id)
        .where(Shot.id.in_(ids))
    ).all()
    info = {shot.id: (shot, filename, scene, quality) for shot, filename, scene, quality in rows}
    frames: dict[str, list[Keyframe]] = {}
    for frame in session.scalars(select(Keyframe).where(Keyframe.shot_id.in_(ids))):
        frames.setdefault(frame.shot_id, []).append(frame)
    judged: dict[str, bool] = {}
    if text:
        judged = {
            j.shot_id: j.relevant
            for j in session.scalars(
                select(SearchJudgment).where(
                    SearchJudgment.project_id == project_id,
                    SearchJudgment.query == normal_query(text),
                    SearchJudgment.judge == USER,
                )
            )
        }
    results: list[SearchResult] = []
    for fused in outcome.results:
        if fused.shot_id not in info:
            continue
        shot, filename, scene, quality = info[fused.shot_id]
        jump = fused.jump_s
        near = min(frames.get(shot.id, []), key=lambda k: abs(k.time_s - jump), default=None)
        why = {
            name: ListHit(
                rank=rank,
                score=item.score,
                contribution=round(part, 6),
                time_s=item.time_s,
                text=item.text,
                parts=[TextPart(text=t, match=m) for t, m in item.parts] if item.parts else None,
                matched=item.matched,
            )
            for name, (item, rank, part) in fused.parts.items()
        }
        results.append(
            SearchResult(
                shot_id=shot.id,
                media_id=shot.media_id,
                filename=filename,
                shot_index=shot.index,
                start_s=shot.start_s,
                end_s=shot.end_s,
                jump_s=jump,
                keyframe_url=f"/api/keyframes/{near.id}/image" if near else None,
                scene_name=scene,
                quality_score=quality,
                score=fused.score,
                why=why,
                relevant=judged.get(shot.id),
            )
        )
    cfg = settings.search
    return SearchOut(
        query=text,
        like_shot_id=like,
        results=results,
        lists=outcome.lists,
        unavailable=outcome.unavailable,
        rrf_k=cfg.rrf_k,
        weights=cfg.weights,
    )


@router.post(
    "/api/projects/{project_id}/search",
    response_model=SearchOut,
    responses=ERRORS,
    operation_id="searchShots",
)
def search_shots(
    project_id: str, body: SearchRequest, session: SessionDep, settings: SettingsDep
) -> SearchOut:
    """Shots for a typed query (all four lists) or like a given shot (pictures only), best
    first, each with the rank and score it had in every list it is in."""
    get_project(session, project_id)
    if body.like_shot_id:
        shot = session.get(Shot, body.like_shot_id)
        media = session.get(MediaAsset, shot.media_id) if shot else None
        if media is None or media.project_id != project_id:
            raise NotFoundError("That shot does not exist in this project.")
    query = hybrid.Query(
        text=None if body.like_shot_id else body.q,
        like_shot_id=body.like_shot_id,
        filters=_filters(body.filters),
        use=body.use or RETRIEVERS,
    )
    outcome = hybrid.run(session, settings, project_id, query)
    text = None if body.like_shot_id else (body.q or "").strip()
    return _out(session, settings, project_id, outcome, text, body.like_shot_id)


@router.post(
    "/api/projects/{project_id}/search/image",
    response_model=SearchOut,
    responses=ERRORS,
    operation_id="searchByImage",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def search_by_image(
    project_id: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    media_id: Annotated[str | None, Query(max_length=32)] = None,
    actor_id: Annotated[str | None, Query(max_length=32)] = None,
    scene_id: Annotated[str | None, Query(max_length=32)] = None,
    min_quality: Annotated[float | None, Query(ge=0, le=1)] = None,
    has_dialogue: bool = False,
) -> SearchOut:
    """Shots that look like a picture (JPEG, PNG or WebP as the raw request body, up to 15 MB
    and 40 megapixels). The picture is only read in memory, never stored."""
    limit = MAX_IMAGE_MB * 1024 * 1024
    await run_in_threadpool(get_project, session, project_id)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise PayloadTooLargeError(f"The picture is larger than {MAX_IMAGE_MB} MB.")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > limit:
            raise PayloadTooLargeError(f"The picture is larger than {MAX_IMAGE_MB} MB.")
    found = picture_size(bytes(data[:65536]))
    if found is None:
        raise InvalidInputError("That file is not a JPEG, PNG or WebP picture.")
    _, width, height = found
    if width * height > MAX_IMAGE_PIXELS:
        raise PayloadTooLargeError(
            f"The picture is {width} x {height} pixels; at most {MAX_IMAGE_PIXELS // 1_000_000} "
            "megapixels can be searched with."
        )

    def work() -> SearchOut:
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise InvalidInputError("That picture could not be read (the file may be damaged).")
        filters = SearchFilters(
            media_id=media_id,
            actor_id=actor_id,
            scene_id=scene_id,
            min_quality=min_quality,
            has_dialogue=has_dialogue,
        )
        query = hybrid.Query(image=image, filters=_filters(filters))
        outcome = hybrid.run(session, settings, project_id, query)
        return _out(session, settings, project_id, outcome, None, None)

    return await run_in_threadpool(work)


@router.put(
    "/api/projects/{project_id}/search/judgments",
    response_model=JudgmentOut,
    responses=ERRORS,
    operation_id="judgeSearchResult",
)
def judge_result(project_id: str, body: JudgmentIn, session: SessionDep) -> JudgmentOut:
    """Mark a result as a good or a bad answer to a query (or take that back). These are the
    labels the search evaluation (`eval/search_eval.py`) measures against."""
    get_project(session, project_id)
    shot = session.get(Shot, body.shot_id)
    media = session.get(MediaAsset, shot.media_id) if shot else None
    if shot is None or media is None or media.project_id != project_id:
        raise NotFoundError("That shot does not exist in this project.")
    query = normal_query(body.query)
    where = (
        SearchJudgment.project_id == project_id,
        SearchJudgment.query == query,
        SearchJudgment.shot_id == shot.id,
        SearchJudgment.judge == USER,
    )
    if body.relevant is None:
        session.execute(delete(SearchJudgment).where(*where))
    else:  # one statement, so two quick clicks cannot both insert
        values = {
            "project_id": project_id,
            "media_id": shot.media_id,
            "query": query,
            "shot_id": shot.id,
            "relevant": body.relevant,
            "judge": USER,
            "created_at": utcnow(),
        }
        session.execute(
            sqlite_insert(SearchJudgment)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["project_id", "query", "shot_id", "judge"],
                set_={"relevant": body.relevant, "created_at": values["created_at"]},
            )
        )
    session.commit()
    count = session.scalar(
        select(func.count())
        .select_from(SearchJudgment)
        .where(SearchJudgment.project_id == project_id, SearchJudgment.judge == USER)
    )
    return JudgmentOut(query=query, shot_id=shot.id, relevant=body.relevant, judged=int(count or 0))
