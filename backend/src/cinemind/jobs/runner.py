"""Stage runner: executes one job's chain with caching, provenance, progress and cancel."""

import hashlib
import json
import logging
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from cinemind.core.config import Settings
from cinemind.core.errors import DomainError, JobCancelled
from cinemind.db.base import utcnow
from cinemind.db.models import Job, MediaAsset, StageResult
from cinemind.jobs import queue
from cinemind.jobs.queue import emit
from cinemind.jobs.registry import Stage, StageContext, get_chain

log = logging.getLogger(__name__)


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def cache_key(media_hash: str, stage: Stage, params_hash: str, upstream_key: str) -> str:
    """Rule 5: (media hash, stage, params hash, model name + version), chained to the previous
    stage's key so a change upstream invalidates everything downstream."""
    return _hash(
        [media_hash, stage.name, params_hash, stage.model_name, stage.model_version, upstream_key]
    )


def run_job(factory: sessionmaker[Session], settings: Settings, job_id: str) -> None:
    with factory() as session:
        job = queue.get_job(session, job_id)
        stages = get_chain(job.chain)
        asset = session.get(MediaAsset, job.media_id) if job.media_id else None
        media_hash = asset.content_hash if asset else f"project:{job.project_id or '-'}"
        params = dict(job.params)
        project_id, media_id = job.project_id, job.media_id

    previous: dict[str, dict[str, Any]] = {}
    upstream_key = ""
    try:
        for ordinal, stage in enumerate(stages):
            _check_cancel(factory, job_id)
            used = (
                params
                if stage.param_keys is None
                else {k: params[k] for k in stage.param_keys if k in params}
            )
            params_hash = _hash({"job": used, "stage": stage.params})
            key = cache_key(media_hash, stage, params_hash, upstream_key)
            upstream_key = key
            prov = {
                "cache_key": key,
                "params_hash": params_hash,
                "model_name": stage.model_name,
                "model_version": stage.model_version,
            }
            cached = _load_cached(factory, key)
            if cached is not None:
                _set_stage(factory, job_id, ordinal, len(stages), "cached", prov)
                previous[stage.name] = cached
                continue

            _set_stage(factory, job_id, ordinal, len(stages), "running", prov)
            ctx = StageContext(
                job_id=job_id,
                project_id=project_id,
                media_id=media_id,
                params=params,
                settings=settings,
                previous=previous,
                _progress=_progress_writer(factory, job_id, ordinal, len(stages)),
                _check_cancel=lambda: _check_cancel(factory, job_id),
            )
            result = stage.run(ctx)
            _store_result(factory, key, media_hash, stage, params_hash, result)
            _set_stage(factory, job_id, ordinal, len(stages), "succeeded", prov)
            previous[stage.name] = result
        _finish_job(factory, job_id, "succeeded")
    except JobCancelled:
        _fail_stage(factory, job_id, "cancelled", None, None)
        _finish_job(factory, job_id, "cancelled")
    except DomainError as exc:
        _fail_stage(factory, job_id, "failed", exc.code, exc.message)
        _finish_job(factory, job_id, "failed", exc.code, exc.message)
    except Exception:
        log.exception("job %s crashed", job_id)
        msg = "A processing step crashed. Partial results are kept; you can retry the job."
        _fail_stage(factory, job_id, "failed", "internal_error", msg)
        _finish_job(factory, job_id, "failed", "internal_error", msg)


def _check_cancel(factory: sessionmaker[Session], job_id: str) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is not None and job.cancel_requested:
            raise JobCancelled


def _load_cached(factory: sessionmaker[Session], key: str) -> dict[str, Any] | None:
    with factory() as session:
        row = session.get(StageResult, key)
        return dict(row.result) if row else None


def _store_result(
    factory: sessionmaker[Session],
    key: str,
    media_hash: str,
    stage: Stage,
    params_hash: str,
    result: dict[str, Any],
) -> None:
    with factory() as session:
        session.merge(
            StageResult(
                cache_key=key,
                media_hash=media_hash,
                stage=stage.name,
                params_hash=params_hash,
                model_name=stage.model_name,
                model_version=stage.model_version,
                result=result,
            )
        )
        session.commit()


def _set_stage(
    factory: sessionmaker[Session],
    job_id: str,
    ordinal: int,
    total: int,
    status: str,
    prov: dict[str, str],
) -> None:
    with factory() as session:
        job = queue.get_job(session, job_id)
        st = job.stages[ordinal]
        st.status = status
        st.started_at = st.started_at or utcnow()
        for k, v in prov.items():
            setattr(st, k, v)
        if status in ("succeeded", "cached"):
            st.progress = 1.0
            st.finished_at = utcnow()
        job.progress = (ordinal + (1.0 if st.progress >= 1.0 else 0.0)) / total
        emit(
            session,
            job_id,
            "stage",
            {"stage": st.name, "status": status, "job_progress": job.progress},
        )
        session.commit()


def _progress_writer(factory: sessionmaker[Session], job_id: str, ordinal: int, total: int) -> Any:
    last = [0.0]

    def write(fraction: float) -> None:
        if fraction - last[0] < 0.01 and fraction < 1.0:
            return
        last[0] = fraction
        with factory() as session:
            job = queue.get_job(session, job_id)
            job.stages[ordinal].progress = fraction
            job.progress = (ordinal + fraction) / total
            emit(
                session,
                job_id,
                "progress",
                {"stage": job.stages[ordinal].name, "progress": fraction, "job": job.progress},
            )
            session.commit()

    return write


def _fail_stage(
    factory: sessionmaker[Session],
    job_id: str,
    status: str,
    code: str | None,
    message: str | None,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:  # project deleted while running
            return
        for st in job.stages:
            if st.status == "running":
                st.status, st.error_code, st.error_message = status, code, message
                st.finished_at = utcnow()
        session.commit()


def _finish_job(
    factory: sessionmaker[Session],
    job_id: str,
    status: str,
    code: str | None = None,
    message: str | None = None,
) -> None:
    with factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.status, job.error_code, job.error_message = status, code, message
        job.finished_at = utcnow()
        if status == "succeeded":
            job.progress = 1.0
        emit(session, job_id, status, {"error_code": code, "message": message})
        session.commit()
