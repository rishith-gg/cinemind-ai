"""Projects CRUD. Deleting a project removes only derived data under data/, never footage."""

import logging
import shutil
from typing import Any

from fastapi import APIRouter
from sqlalchemy import delete, select

from cinemind.api.deps import SessionDep, SettingsDep
from cinemind.api.schemas import ErrorResponse, ProjectCreate, ProjectOut, ProjectUpdate
from cinemind.core.errors import JobStateError, NotFoundError
from cinemind.core.paths import validate_project_id
from cinemind.db.models import Job, JobEvent, Project

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["projects"])
_404: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}


def _get(session: SessionDep, project_id: str) -> Project:
    project = session.get(Project, validate_project_id(project_id))
    if project is None:
        raise NotFoundError("That project does not exist.")
    return project


@router.post("", response_model=ProjectOut, status_code=201, operation_id="createProject")
def create_project(body: ProjectCreate, session: SessionDep, settings: SettingsDep) -> Project:
    project = Project(name=body.name.strip() or "Untitled", description=body.description)
    session.add(project)
    session.commit()
    settings.project_dir(project.id).mkdir(parents=True, exist_ok=True)
    return project


@router.get("", response_model=list[ProjectOut], operation_id="listProjects")
def list_projects(session: SessionDep) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.created_at.desc())))


@router.get("/{project_id}", response_model=ProjectOut, responses=_404, operation_id="getProject")
def get_project(project_id: str, session: SessionDep) -> Project:
    return _get(session, project_id)


@router.patch(
    "/{project_id}", response_model=ProjectOut, responses=_404, operation_id="updateProject"
)
def update_project(project_id: str, body: ProjectUpdate, session: SessionDep) -> Project:
    project = _get(session, project_id)
    if body.name is not None:
        project.name = body.name.strip() or project.name
    if body.description is not None:
        project.description = body.description
    session.commit()
    return project


@router.delete("/{project_id}", status_code=204, responses=_404, operation_id="deleteProject")
def delete_project(project_id: str, session: SessionDep, settings: SettingsDep) -> None:
    project = _get(session, project_id)
    active = session.scalars(
        select(Job.id).where(Job.project_id == project_id, Job.status.in_(("queued", "running")))
    ).all()
    if active:
        raise JobStateError("This project has running jobs. Cancel them before deleting it.")
    job_ids = session.scalars(select(Job.id).where(Job.project_id == project_id)).all()
    session.execute(delete(JobEvent).where(JobEvent.job_id.in_(job_ids)))
    session.delete(project)
    session.commit()
    try:
        shutil.rmtree(settings.project_dir(project_id))
    except FileNotFoundError:
        pass
    except OSError:
        log.exception("could not remove derived data for project %s", project_id)
