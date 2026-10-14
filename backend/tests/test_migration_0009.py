"""Migration 0009 rebuilds `shots` (new scene_id column): rows that point at shots must survive."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from cinemind.db.migrate import MIGRATIONS

_DUMMY = {"INTEGER": 1, "FLOAT": 1.0, "BOOLEAN": 0, "JSON": "{}", "DATETIME": "2026-10-14 00:00:00"}


def _insert(db: sqlite3.Connection, table: str, values: dict[str, object]) -> None:
    """Fill every required column: given values, else a dummy of the column's type."""
    row: dict[str, object] = {}
    for _, name, kind, notnull, _default, _pk in db.execute(f"PRAGMA table_info({table})"):
        if name in values:
            row[name] = values[name]
        elif notnull:
            row[name] = _DUMMY.get(str(kind).split("(")[0], "x")
    cols = ", ".join(f'"{c}"' for c in row)
    marks = ", ".join("?" * len(row))
    sql = f"INSERT INTO {table} ({cols}) VALUES ({marks})"  # noqa: S608 (test-owned names)
    db.execute(sql, list(row.values()))


def test_upgrade_keeps_shots_and_everything_pointing_at_them(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(cfg, "0008")
    db = sqlite3.connect(path)
    _insert(db, "projects", {"id": "p"})
    _insert(db, "media_assets", {"id": "m", "project_id": "p", "content_hash": "h"})
    _insert(db, "shots", {"id": "s", "media_id": "m", "index": 0})
    _insert(db, "keyframes", {"id": "k", "shot_id": "s", "media_id": "m", "path": "a.jpg"})
    _insert(db, "quality_metrics", {"shot_id": "s", "media_id": "m"})
    db.commit()
    db.close()

    command.upgrade(cfg, "head")
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    assert db.execute("SELECT id, scene_id FROM shots").fetchall() == [("s", None)]
    assert db.execute("SELECT id FROM keyframes").fetchall() == [("k",)]
    assert db.execute("SELECT shot_id FROM quality_metrics").fetchall() == [("s",)]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    command.downgrade(cfg, "0008")  # and back
    assert db.execute("SELECT id FROM keyframes").fetchall() == [("k",)]
