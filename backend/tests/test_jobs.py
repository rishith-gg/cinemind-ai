import hashlib
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cinemind.core.config import Settings
from cinemind.core.errors import JobStateError, NotFoundError
from cinemind.db.models import Job, JobEvent, StageResult
from cinemind.jobs import queue
from cinemind.jobs.runner import cache_key, run_job


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


def test_stage_cache_keys_chain_to_the_previous_stage_unless_upstream_is_named(
    factory: sessionmaker[Session], settings: Settings
) -> None:
    from cinemind.jobs import registry
    from cinemind.jobs.registry import Stage, StageContext

    def run(_ctx: StageContext) -> dict[str, Any]:
        return {}

    registry.register_chain(
        "upstream_test",
        [
            Stage("a", run, param_keys=()),
            Stage("b", run, param_keys=("x",)),
            Stage("c", run, param_keys=(), upstream=("a",)),
        ],
    )

    def keys(x: int) -> list[str | None]:
        with factory() as session:
            job_id = queue.enqueue(session, "upstream_test", params={"x": x}).id
        queue.claim_next(factory)
        run_job(factory, settings, job_id)
        with factory() as session:
            return [stage.cache_key for stage in queue.get_job(session, job_id).stages]

    first, second = keys(1), keys(2)
    # b depends on x; c hangs on a only, so b's change does not reach it.
    assert first[0] == second[0] and first[1] != second[1] and first[2] == second[2]
    # Unchanged rule for ordinary stages: the key is chained to the stage before it.
    stage_b = registry.get_chain("upstream_test")[1]
    hashed = json.dumps({"job": {"x": 1}, "stage": {}}, sort_keys=True).encode()
    params_hash = hashlib.sha256(hashed).hexdigest()
    assert first[1] == cache_key("project:-", stage_b, params_hash, str(first[0]))

    with pytest.raises(ValueError, match="upstream"):
        registry.register_chain("bad", [Stage("a", run, upstream=("later",)), Stage("later", run)])


def test_retry_adds_stage_rows_for_stages_added_to_the_chain_since(
    factory: sessionmaker[Session], settings: Settings
) -> None:
    from cinemind.jobs import registry
    from cinemind.jobs.registry import Stage, StageContext

    def run(_ctx: StageContext) -> dict[str, Any]:
        return {}

    registry.register_chain("grows", [Stage("one", run)])
    with factory() as session:
        job = queue.enqueue(session, "grows")
        job.status = "failed"
        session.commit()
        job_id = job.id
    registry.register_chain("grows", [Stage("one", run), Stage("two", run)])
    with factory() as session:
        queue.retry(session, job_id)
    queue.claim_next(factory)
    run_job(factory, settings, job_id)
    with factory() as session:
        job = queue.get_job(session, job_id)
        assert job.status == "succeeded"
        assert [(s.name, s.status) for s in job.stages] == [
            ("one", "succeeded"),
            ("two", "succeeded"),
        ]
