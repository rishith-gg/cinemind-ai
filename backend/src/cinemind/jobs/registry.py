"""Stage and chain definitions. A chain is an ordered list of stages run by the worker."""

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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


_CHAINS: dict[str, list[Stage]] = {}


def register_chain(name: str, stages: list[Stage]) -> None:
    _CHAINS[name] = stages


def get_chain(name: str) -> list[Stage]:
    if name not in _CHAINS:
        raise NotFoundError(f"Unknown processing chain '{name}'.")
    return _CHAINS[name]


def load_extra_modules(settings: Settings) -> None:
    """Import modules named in settings.extra_stage_modules so they can register chains."""
    for module in settings.extra_stage_modules:
        importlib.import_module(module)
