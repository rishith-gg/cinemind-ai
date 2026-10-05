from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

import dummy_chain
from cinemind.core.config import Settings
from cinemind.db.base import make_engine, make_session_factory
from cinemind.db.migrate import upgrade_head

# Importing registers the test-only chains.
REGISTERED_CHAINS = dummy_chain.__name__


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        media_roots=[],
        worker_poll_seconds=0.05,
        extra_stage_modules=["dummy_chain"],
    )


@pytest.fixture
def factory(settings: Settings) -> Iterator[sessionmaker[Session]]:
    upgrade_head(settings.db_path)
    engine = make_engine(settings.db_path)
    yield make_session_factory(engine)
    engine.dispose()
