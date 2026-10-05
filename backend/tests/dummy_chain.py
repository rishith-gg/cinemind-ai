"""Test-only stage chains (registered via CINEMIND_EXTRA_STAGE_MODULES). Not shipped as AI."""

import time
from pathlib import Path
from typing import Any

from cinemind.core.errors import InvalidInputError
from cinemind.jobs.registry import Stage, StageContext, register_chain


def _mark(ctx: StageContext, line: str) -> None:
    marker = ctx.params.get("marker")
    if marker:
        with Path(marker).open("a") as f:
            f.write(line + "\n")


def stage_a(ctx: StageContext) -> dict[str, Any]:
    _mark(ctx, "a")
    return {"value": 1}


def stage_b(ctx: StageContext) -> dict[str, Any]:
    _mark(ctx, "b")
    gate = ctx.params.get("gate")  # block until the gate file exists (kill/cancel tests)
    steps = 0
    while gate and not Path(gate).exists():
        ctx.check_cancelled()
        steps += 1
        ctx.progress(min(0.9, steps / 20))
        time.sleep(0.05)
    return {"value": ctx.previous["a"]["value"] + 1}


def stage_c(ctx: StageContext) -> dict[str, Any]:
    _mark(ctx, "c")
    return {"value": ctx.previous["b"]["value"] + 1}


def stage_boom(ctx: StageContext) -> dict[str, Any]:
    raise InvalidInputError("Boom: this stage always fails.")


def stage_crash(ctx: StageContext) -> dict[str, Any]:
    raise RuntimeError("secret internal detail")


register_chain(
    "dummy",
    [
        Stage("a", stage_a, model_name="none", model_version="1"),
        Stage("b", stage_b),
        Stage("c", stage_c),
    ],
)
register_chain("dummy_fail", [Stage("a", stage_a), Stage("boom", stage_boom)])
register_chain("dummy_crash", [Stage("crash", stage_crash)])
