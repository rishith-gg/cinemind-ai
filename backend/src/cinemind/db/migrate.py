"""Run Alembic migrations programmatically (API and worker call this at startup)."""

from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS = Path(__file__).parent / "migrations"


def upgrade_head(db_path: Path) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(cfg, "head")
