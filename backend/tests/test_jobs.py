import threading
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cinemind.core.config import Settings
from cinemind.core.errors import JobStateError, NotFoundError
from cinemind.db.models import Job, JobEvent, StageResult
from cinemind.jobs import queue
from cinemind.jobs.runner import run_job


def _run(factory: sessionmaker[Session], settings: Settings, **kw: object) -> Job:
    with factory() as s:
        job_id = queue.enqueue(s, **kw).id  # type: ignore[arg-type]
    claimed = queue.claim_next(factory)
    assert claimed == job_id
    run_job(factory, settings, job_id)
    with factory() as s:
        job = queue.get_job(s, job_id)
        _ = job.stages  # load before the session closes
        return job


def test_chain_succeeds_with_provenance(
    factory: sessionmaker[Session], settings: Settings, tmp_path: Path
) -> None:
    marker = tmp_path / "m"
    job = _run(factory, settings, chain="dummy", params={"marker": str(marker)})
    assert job.status == "succeeded" and job.progress == 1.0
    assert marker.read_text().split() == ["a", "b", "c"]
    first = job.stages[0]
    assert (first.status, first.model_name, first.model_version) == ("succeeded", "none", "1")
    assert first.cache_key and first.params_hash
    with factory() as s:
        assert s.scalars(select(StageResult)).all()
        types = [e.type for e in s.scalars(select(JobEvent).order_by(JobEvent.id))]
    assert types[0] == "queued" and types[-1] == "succeeded"


def test_second_run_is_served_from_cache(
    factory: sessionmaker[Session], settings: Settings, tmp_path: Path
) -> None:
    marker = tmp_path / "m"
    params = {"marker": str(marker)}
    _run(factory, settings, chain="dummy", params=params)
    again = _run(factory, settings, chain="dummy", params=params)
    assert [st.status for st in again.stages] == ["cached"] * 3
    assert marker.read_text().split() == ["a", "b", "c"]  # nothing re-executed


def test_different_params_miss_the_cache(
    factory: sessionmaker[Session], settings: Settings, tmp_path: Path
) -> None:
    marker = tmp_path / "m"
    _run(factory, settings, chain="dummy", params={"marker": str(marker), "x": 1})
    _run(factory, settings, chain="dummy", params={"marker": str(marker), "x": 2})
    assert marker.read_text().split() == ["a", "b", "c"] * 2


def test_domain_failure_then_retry_keeps_finished_stages(
    factory: sessionmaker[Session], settings: Settings
) -> None:
    job = _run(factory, settings, chain="dummy_fail")
    assert job.status == "failed" and job.error_code == "invalid_input"
    assert "Boom" in (job.error_message or "")
    assert [s.status for s in job.stages] == ["succeeded", "failed"]
    with factory() as s:
        retried = queue.retry(s, job.id)
        assert retried.status == "queued"
        assert [st.status for st in retried.stages] == ["succeeded", "pending"]


def test_unexpected_crash_hides_internals(
    factory: sessionmaker[Session], settings: Settings
) -> None:
    job = _run(factory, settings, chain="dummy_crash")
    assert job.status == "failed" and job.error_code == "internal_error"
    assert "secret" not in (job.error_message or "")


def test_cancel_queued_and_unknown_chain(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        job = queue.enqueue(s, "dummy")
        assert queue.request_cancel(s, job.id).status == "cancelled"
        with pytest.raises(JobStateError):
            queue.request_cancel(s, job.id)
        with pytest.raises(JobStateError):
            queue.retry(s, _succeeded(s))
        with pytest.raises(NotFoundError):
            queue.enqueue(s, "nope")


def _succeeded(s: Session) -> str:
    job = queue.enqueue(s, "dummy")
    job.status = "succeeded"
    s.commit()
    return job.id


def test_cancel_running_job(
    factory: sessionmaker[Session], settings: Settings, tmp_path: Path
) -> None:
    gate = tmp_path / "never"
    with factory() as s:
        job_id = queue.enqueue(s, "dummy", params={"gate": str(gate)}).id
    assert queue.claim_next(factory) == job_id
    t = threading.Thread(target=run_job, args=(factory, settings, job_id))
    t.start()
    with factory() as s:
        queue.request_cancel(s, job_id)
    t.join(timeout=10)
    assert not t.is_alive()
    with factory() as s:
        job = queue.get_job(s, job_id)
        assert job.status == "cancelled"
        queue.retry(s, job_id)  # cancelled jobs can be retried


def test_claim_is_exclusive(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        queue.enqueue(s, "dummy")
    assert queue.claim_next(factory) is not None
    assert queue.claim_next(factory) is None


def test_upstream_change_invalidates_downstream(
    factory: sessionmaker[Session], settings: Settings, tmp_path: Path
) -> None:
    from dataclasses import replace

    from cinemind.jobs import registry

    marker = {"marker": str(tmp_path / "m")}
    _run(factory, settings, chain="dummy", params=marker)
    original = registry.get_chain("dummy")
    registry.register_chain(
        "dummy", [original[0], replace(original[1], model_version="2"), original[2]]
    )
    try:
        job = _run(factory, settings, chain="dummy", params=marker)
    finally:
        registry.register_chain("dummy", original)
    assert [s.status for s in job.stages] == ["cached", "succeeded", "succeeded"]


def test_poison_job_fails_after_max_attempts(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        job_id = queue.enqueue(s, "dummy").id
    for _ in range(3):
        assert queue.claim_next(factory) == job_id
        with factory() as s:
            queue.requeue_orphans(s, max_attempts=3)
    with factory() as s:
        job = queue.get_job(s, job_id)
        assert job.status == "failed" and job.error_code == "worker_crashed"
