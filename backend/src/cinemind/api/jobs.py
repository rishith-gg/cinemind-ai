"""Job status, cancel/retry and the SSE event stream."""

import json
import time
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from cinemind.api.deps import FactoryDep, SessionDep, SettingsDep
from cinemind.api.schemas import ErrorResponse, JobOut
from cinemind.db.models import JobEvent
from cinemind.jobs import queue

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
_ERR: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}


def iter_sse(
    factory: sessionmaker[Session],
    after_id: int,
    poll_seconds: float,
    follow: bool = True,
    job_id: str | None = None,
) -> Iterator[str]:
    """Yield SSE frames for job_events with id > after_id; resumable via Last-Event-ID."""
    last = after_id
    idle_beats = 0
    while True:
        with factory() as session:
            stmt = select(JobEvent).where(JobEvent.id > last).order_by(JobEvent.id).limit(200)
            if job_id:
                stmt = stmt.where(JobEvent.job_id == job_id)
            events = session.scalars(stmt).all()
        for ev in events:
            last = ev.id
            payload = json.dumps({"job_id": ev.job_id, "type": ev.type, "data": ev.data})
            yield f"id: {ev.id}\nevent: {ev.type}\ndata: {payload}\n\n"
        if not follow:
            return
        if not events:
            idle_beats += 1
            if idle_beats % 30 == 0:
                yield ": keep-alive\n\n"
            time.sleep(poll_seconds)


def _latest_id(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        return session.scalar(select(func.max(JobEvent.id))) or 0


@router.get("/events", operation_id="streamJobEvents")
def stream_events(
    factory: FactoryDep,
    settings: SettingsDep,
    follow: bool = Query(True, description="false: send stored events then close"),
    job_id: str | None = None,
    last_event_id: str | None = Header(default=None),
) -> StreamingResponse:
    after = int(last_event_id) if last_event_id and last_event_id.isdigit() else None
    if after is None:  # fresh live connection: start from now instead of replaying history
        after = _latest_id(factory) if follow and not job_id else 0
    return StreamingResponse(
        iter_sse(factory, after, settings.worker_poll_seconds, follow, job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{job_id}", response_model=JobOut, responses=_ERR, operation_id="getJob")
def get_job(job_id: str, session: SessionDep) -> JobOut:
    return JobOut.model_validate(queue.get_job(session, job_id))


@router.post("/{job_id}/cancel", response_model=JobOut, responses=_ERR, operation_id="cancelJob")
def cancel_job(job_id: str, session: SessionDep) -> JobOut:
    return JobOut.model_validate(queue.request_cancel(session, job_id))


@router.post("/{job_id}/retry", response_model=JobOut, responses=_ERR, operation_id="retryJob")
def retry_job(job_id: str, session: SessionDep) -> JobOut:
    return JobOut.model_validate(queue.retry(session, job_id))
