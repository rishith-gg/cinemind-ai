"""Alembic environment (online mode only; SQLite)."""

from alembic import context
from sqlalchemy import create_engine

from cinemind.db import models  # noqa: F401  (register tables)
from cinemind.db.base import Base

config = context.config
target_metadata = Base.metadata


def run() -> None:
    engine = create_engine(config.get_main_option("sqlalchemy.url") or "")
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run()
