"""The screenplay of a project, its alignment with the footage, and the script-ordered
assembly (SPEC P1-A)."""

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from cinemind.api.deps import SessionDep, SettingsDep
from cinemind.api.media import ERRORS, get_project
from cinemind.api.script_schemas import (
    AlignmentOut,
    ScriptCutCreate,
    ScriptIn,
    ScriptLineOut,
    ScriptOut,
    TakeChoice,
    TakeOut,
)
from cinemind.api.timeline_schemas import TimelineDetail
from cinemind.api.timelines import detail, rate_of
from cinemind.core.config import Settings
from cinemind.db.models import MediaAsset
from cinemind.db.script import ScriptDoc
from cinemind.rough_cut import script_store
from cinemind.rough_cut.script_cut import build_script_cut

router = APIRouter(tags=["script"])


def _out(session: Session, settings: Settings, doc: ScriptDoc) -> ScriptOut:
    limit = script_store.limit_of(settings, doc)
    ids = {t.media_id for line in doc.lines for t in line.takes}
    names = dict(
        session.execute(
            select(MediaAsset.id, MediaAsset.filename).where(MediaAsset.id.in_(ids))
        ).all()
    )
    lines: list[ScriptLineOut] = []
    for line in doc.lines:
        take, why = script_store.chosen(line, limit) if line.kind == "dialogue" else (None, "")
        lines.append(
            ScriptLineOut(
                id=line.id,
                index=line.index,
                kind=line.kind,
                character=line.character,
                scene=line.scene,
                text=line.text,
                choice=line.choice,
                chosen_take_id=take.id if take else None,
                why=why,
                takes=[
                    TakeOut(
                        id=t.id,
                        media_id=t.media_id,
                        filename=names.get(t.media_id, ""),
                        rank=t.rank,
                        start_s=t.start_s,
                        end_s=t.end_s,
                        text=t.text,
                        lexical=t.lexical,
                        semantic=t.semantic,
                        score=t.score,
                    )
                    for t in line.takes
                ],
            )
        )
    counts = script_store.summary(doc, limit)
    return ScriptOut(
        id=doc.id,
        project_id=doc.project_id,
        name=doc.name,
        format=doc.format,
        created_at=doc.created_at,
        alignment=AlignmentOut(
            **{k: v for k, v in doc.alignment.items() if k in AlignmentOut.model_fields},
            lexical_weight=doc.alignment.get("settings", {}).get("lexical_weight", 1.0),
            semantic_weight=doc.alignment.get("settings", {}).get("semantic_weight", 0.0),
        ),
        min_score=limit,
        dialogue_lines=counts["dialogue_lines"],
        with_take=counts["with_take"],
        lines=lines,
    )


@router.post(
    "/api/projects/{project_id}/script",
    response_model=ScriptOut,
    status_code=201,
    responses=ERRORS,
    operation_id="uploadScript",
)
def upload_script(
    project_id: str, body: ScriptIn, session: SessionDep, settings: SettingsDep
) -> ScriptOut:
    """Store the screenplay (replacing the project's previous one) and find each dialogue line
    in the transcripts."""
    get_project(session, project_id)
    doc = script_store.save(session, settings, project_id, body.name, body.text)
    session.commit()
    return _out(session, settings, doc)


@router.get(
    "/api/projects/{project_id}/script",
    response_model=ScriptOut,
    responses=ERRORS,
    operation_id="getScript",
)
def get_script(project_id: str, session: SessionDep, settings: SettingsDep) -> ScriptOut:
    get_project(session, project_id)
    return _out(session, settings, script_store.get_doc(session, project_id))


@router.post(
    "/api/projects/{project_id}/script/align",
    response_model=ScriptOut,
    responses=ERRORS,
    operation_id="alignScript",
)
def align_script(project_id: str, session: SessionDep, settings: SettingsDep) -> ScriptOut:
    """Find the lines again, e.g. after more footage was processed. Your choices stay."""
    get_project(session, project_id)
    doc = script_store.get_doc(session, project_id)
    script_store.align_doc(session, settings, doc)
    session.commit()
    return _out(session, settings, doc)


@router.delete(
    "/api/projects/{project_id}/script",
    status_code=204,
    responses=ERRORS,
    operation_id="deleteScript",
)
def delete_script(project_id: str, session: SessionDep) -> None:
    get_project(session, project_id)
    session.delete(script_store.get_doc(session, project_id))
    session.commit()


@router.put(
    "/api/script-lines/{line_id}/take",
    response_model=ScriptOut,
    responses=ERRORS,
    operation_id="chooseTake",
)
def choose_take(
    line_id: str, body: TakeChoice, session: SessionDep, settings: SettingsDep
) -> ScriptOut:
    """Use this take for the line, mark the line as not filmed, or go back to the best match."""
    line = script_store.choose(session, line_id, body.take_id, body.not_filmed)
    session.commit()
    doc = session.get(ScriptDoc, line.doc_id)
    assert doc is not None  # noqa: S101 - a line always belongs to a script (cascade)
    return _out(session, settings, doc)


@router.post(
    "/api/projects/{project_id}/script/assembly",
    response_model=TimelineDetail,
    status_code=201,
    responses=ERRORS,
    operation_id="createScriptAssembly",
)
def create_script_assembly(
    project_id: str, body: ScriptCutCreate, session: SessionDep, settings: SettingsDep
) -> TimelineDetail:
    """Every dialogue line's take in script order, as a timeline (AI-assisted rough cut)."""
    get_project(session, project_id)
    timeline = build_script_cut(session, settings, project_id, body.name, rate_of(body.fps))
    return detail(session, settings, timeline)
