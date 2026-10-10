"""Stage and chain definitions. A chain is an ordered list of stages run by the worker."""

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from cinemind.core.config import Settings
from cinemind.core.errors import NotFoundError


@dataclass
class StageContext:
    """What a stage may use. Stages never touch the DB session directly."""

    job_id: str
    project_id: str | None
    media_id: str | None
    params: dict[str, Any]
    settings: Settings
    previous: dict[str, dict[str, Any]]
    _progress: Callable[[float], None]
    _check_cancel: Callable[[], None]

    def progress(self, fraction: float) -> None:
        self._progress(min(1.0, max(0.0, fraction)))

    def check_cancelled(self) -> None:
        """Call regularly in long loops; raises JobCancelled if the user cancelled."""
        self._check_cancel()


@dataclass(frozen=True)
class Stage:
    name: str
    run: Callable[[StageContext], dict[str, Any]]
    model_name: str = ""
    model_version: str = ""
    params: dict[str, Any] = field(default_factory=lambda: {})
    # Job params this stage depends on (None = all). Keeps unrelated params from busting the cache.
    param_keys: tuple[str, ...] | None = None
    # Stages that write files under the project directory cache per project, so the same footage
    # imported into two projects still gets its own artifacts.
    scope_project: bool = False
    # Stages whose cache keys this stage's key is chained to (None = the stage before it). An
    # expensive stage names what it really reads, so unrelated settings do not invalidate it.
    upstream: tuple[str, ...] | None = None
    # Cached results are only reused if this says the output files still exist.
    verify: Callable[[StageContext, dict[str, Any]], bool] | None = None
    # Store the result in the database; runs after a fresh run AND after a cache hit.
    persist: Callable[[Session, StageContext, dict[str, Any]], None] | None = None


_CHAINS: dict[str, list[Stage]] = {}


def register_chain(name: str, stages: list[Stage]) -> None:
    seen: set[str] = set()
    for stage in stages:
        unknown = set(stage.upstream or ()) - seen
        if unknown:
            raise ValueError(f"stage '{stage.name}' names upstream stages not before it: {unknown}")
        seen.add(stage.name)
    _CHAINS[name] = stages


def get_chain(name: str) -> list[Stage]:
    importlib.import_module("cinemind.pipeline.ingest")  # registers the built-in chains
    if name not in _CHAINS:
        raise NotFoundError(f"Unknown processing chain '{name}'.")
    return _CHAINS[name]


def load_extra_modules(settings: Settings) -> None:
    """Import modules named in settings.extra_stage_modules so they can register chains."""
    for module in settings.extra_stage_modules:
        importlib.import_module(module)
