"""Worker process: polls the queue and runs jobs. `python -m cinemind.jobs.worker`."""

import argparse
import logging
import os
import signal
import threading
import time
from types import FrameType

from sqlalchemy.orm import Session, sessionmaker

from cinemind.core.config import Settings, get_settings
from cinemind.db.base import make_engine, make_session_factory
from cinemind.db.migrate import upgrade_head
from cinemind.db.models import Job
from cinemind.jobs.queue import claim_next, emit, requeue_orphans
from cinemind.jobs.registry import load_extra_modules
from cinemind.jobs.runner import run_job
from cinemind.pipeline import project_refresh

log = logging.getLogger(__name__)


def run_worker(
    settings: Settings, stop: threading.Event | None = None, parent_pid: int | None = None
) -> None:
    """Run until `stop` is set, or until the parent process (e.g. `serve`) disappears."""
    stop = stop or threading.Event()
    load_extra_modules(settings)
    upgrade_head(settings.db_path)
    factory = make_session_factory(make_engine(settings.db_path))
    with factory() as session:
        resumed = requeue_orphans(session, settings.max_job_attempts)
    if resumed:
        log.info("resuming %d job(s) interrupted by a previous crash", len(resumed))
    log.info("worker ready (db=%s)", settings.db_path)
    while not stop.is_set():
        if parent_pid is not None and os.getppid() != parent_pid:
            log.info("parent process exited; stopping worker")
            break
        job_id = claim_next(factory)
        if job_id is None:
            time.sleep(settings.worker_poll_seconds)
            continue
        log.info("running job %s", job_id)
        try:
            run_job(factory, settings, job_id)
        except Exception:  # a bad job must not take the worker down
            log.exception("job %s aborted unexpectedly", job_id)
        _after_ingest(factory, settings, job_id)


def _after_ingest(factory: sessionmaker[Session], settings: Settings, job_id: str) -> None:
    """After an ingest job: once the project's queue is empty, group its faces into actors and
    its shots into scenes, and bring its vector indexes up to date."""
    try:
        with factory() as session:
            job = session.get(Job, job_id)
            if job is None or job.chain != "ingest" or job.project_id is None:
                return
            changed = project_refresh.refresh_if_idle(session, settings, job.project_id)
            for name in changed or ():
                emit(session, job_id, name)  # tells open pages to reload people or scenes
            session.commit()
    except Exception:  # each step can be repeated from its page; never stop the worker
        log.exception("project steps failed after job %s", job_id)


def main() -> None:
    # Rule 1: processing never downloads. Models are read from data/models by path already; this
    # also stops the Hugging Face libraries from trying the network if that ever changes.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    parser = argparse.ArgumentParser(description="CineMind job worker")
    parser.add_argument("--parent-pid", type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    stop = threading.Event()

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    run_worker(get_settings(), stop, args.parent_pid)


if __name__ == "__main__":
    main()
