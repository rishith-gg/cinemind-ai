"""Job queue operations on the SQLite `jobs` table (shared by API and worker)."""

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from cinemind.core.errors import JobStateError, NotFoundError
from cinemind.db.base import utcnow
from cinemind.db.models import Job, JobEvent, JobStage
from cinemind.jobs.registry import get_chain

TERMINAL = ("succeeded", "failed", "cancelled")


def emit(session: Session, job_id: str, type_: str, data: dict[str, Any] | None = None) -> None:
    session.add(JobEvent(job_id=job_id, type=type_, data=data or {}))


def get_job(session: Session, job_id: str) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise NotFoundError("That job does not exist.")
    return job


def enqueue(
    session: Session,
    chain: str,
    project_id: str | None = None,
    media_id: str | None = None,
    params: dict[str, Any] | None = None,
) -> Job:
    stages = get_chain(chain)  # raises NotFoundError for an unknown chain
    job = Job(chain=chain, project_id=project_id, media_id=media_id, params=params or {})
    job.stages = [JobStage(ordinal=i, name=s.name) for i, s in enumerate(stages)]
    session.add(job)
    session.flush()
    emit(session, job.id, "queued", {"chain": chain})
    session.commit()
    return job


def claim_next(factory: sessionmaker[Session]) -> str | None:
    """Atomically move the oldest queued job to running. Returns its id or None."""
    with factory() as session:
        job_id = session.scalars(
            select(Job.id).where(Job.status == "queued").order_by(Job.created_at, Job.id).limit(1)
        ).first()
        if job_id is None:
            return None
        claimed = session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(status="running", started_at=utcnow(), attempts=Job.attempts + 1)
            .returning(Job.id)
        ).first()
        if claimed is None:
            session.rollback()
            return None
        emit(session, job_id, "started")
        session.commit()
        return job_id


def request_cancel(session: Session, job_id: str) -> Job:
    job = get_job(session, job_id)
    if job.status in TERMINAL:
        raise JobStateError(f"The job already finished ({job.status}); it cannot be cancelled.")
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = utcnow()
        emit(session, job.id, "cancelled")
    else:
        job.cancel_requested = True
        emit(session, job.id, "cancel_requested")
    session.commit()
    return job


def retry(session: Session, job_id: str) -> Job:
    """Re-queue a failed/cancelled job. Finished stages are kept, so work resumes."""
    job = get_job(session, job_id)
    if job.status not in ("failed", "cancelled"):
        raise JobStateError("Only failed or cancelled jobs can be retried.")
    _reset_unfinished(job)
    job.status = "queued"
    job.cancel_requested = False
    job.error_code = job.error_message = None
    job.finished_at = None
    emit(session, job.id, "queued", {"retry": True})
    session.commit()
    return job


def requeue_orphans(session: Session, max_attempts: int = 3) -> list[str]:
    """Worker startup: with one worker, any 'running' job is left over from a crash."""
    jobs = session.scalars(select(Job).where(Job.status == "running")).all()
    resumed: list[str] = []
    for job in jobs:
        if job.attempts >= max_attempts:  # probably killing the worker (OOM, native crash)
            job.status, job.error_code = "failed", "worker_crashed"
            job.error_message = (
                "The worker crashed repeatedly on this job. Check the logs, then retry."
            )
            job.finished_at = utcnow()
            emit(session, job.id, "failed", {"error_code": "worker_crashed"})
            continue
        _reset_unfinished(job)
        job.status = "queued"
        emit(session, job.id, "queued", {"resumed_after_restart": True})
        resumed.append(job.id)
    session.commit()
    return resumed


def _reset_unfinished(job: Job) -> None:
    # A job created before a stage was added to its chain gets the missing stage rows.
    try:
        names = [stage.name for stage in get_chain(job.chain)]
    except NotFoundError:
        names = []
    for ordinal in range(len(job.stages), len(names)):
        job.stages.append(JobStage(ordinal=ordinal, name=names[ordinal]))
    for st in job.stages:
        if st.status not in ("succeeded", "cached"):
            st.status = "pending"
            st.progress = 0.0
            st.error_code = st.error_message = None
