"""Declarative base, shared column helpers and engine/session setup (SQLite, WAL)."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Engine, TypeDecorator, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class UTCDateTime(TypeDecorator[datetime]):
    """Stores timezone-aware UTC datetimes in SQLite (which has no tz support)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


def make_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 30})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
