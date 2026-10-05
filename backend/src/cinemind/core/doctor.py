"""`cinemind doctor`: real environment checks plus a model-tier recommendation."""

import platform
import shutil
import sys
from typing import Literal

from pydantic import BaseModel

from cinemind import __version__
from cinemind.core.config import Settings
from cinemind.core.hardware import (
    HardwareInfo,
    TierRecommendation,
    detect_hardware,
    recommend_tier,
    run_probe,
)

Status = Literal["ok", "missing", "warn"]

MIN_PYTHON = (3, 11)
MIN_FREE_DISK_GB = 20.0

# (tool name, command that prints its version, required to RUN the app?)
_TOOLS: list[tuple[str, list[str], bool]] = [
    ("ffmpeg", ["ffmpeg", "-version"], True),
    ("ffprobe", ["ffprobe", "-version"], True),
    ("uv", ["uv", "--version"], False),
    ("node", ["node", "--version"], False),
    ("pnpm", ["pnpm", "--version"], False),
    ("git", ["git", "--version"], False),
]

_INSTALL_HINTS: dict[str, dict[str, str]] = {
    "ffmpeg": {
        "Darwin": "brew install ffmpeg",
        "Linux": "sudo apt install ffmpeg  (or your distro's package manager)",
        "Windows": "winget install Gyan.FFmpeg",
    },
    "uv": {
        "Darwin": "brew install uv",
        "Linux": "curl -LsSf https://astral.sh/uv/install.sh | sh",
        "Windows": "winget install astral-sh.uv",
    },
    "node": {
        "Darwin": "brew install node",
        "Linux": "see https://nodejs.org",
        "Windows": "winget install OpenJS.NodeJS.LTS",
    },
    "pnpm": {
        "Darwin": "corepack enable pnpm",
        "Linux": "corepack enable pnpm",
        "Windows": "corepack enable pnpm",
    },
    "git": {
        "Darwin": "brew install git",
        "Linux": "sudo apt install git",
        "Windows": "winget install Git.Git",
    },
}


class Check(BaseModel):
    name: str
    status: Status
    required: bool
    version: str | None = None
    detail: str | None = None
    fix: str | None = None


class DoctorReport(BaseModel):
    app_version: str
    ok: bool  # every required check passed
    checks: list[Check]
    hardware: HardwareInfo
    recommended: TierRecommendation
    selected_tier: str  # the tier the app will use (config override or recommendation)


def _hint(tool: str) -> str | None:
    return _INSTALL_HINTS.get(tool, {}).get(platform.system())


def _version_from(output: str) -> str:
    first = output.splitlines()[0]
    # "ffmpeg version 9.0.2 Copyright ..." -> "9.0.2"; "uv 0.12.23 (...)" -> "0.12.23"
    parts = first.split()
    if "version" in parts:
        return parts[parts.index("version") + 1]
    return parts[1] if len(parts) > 1 and parts[0] in {"uv", "git"} else first.lstrip("v")


def check_python() -> Check:
    version = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info[:2] >= MIN_PYTHON:
        return Check(name="python", status="ok", required=True, version=version)
    return Check(
        name="python",
        status="missing",
        required=True,
        version=version,
        detail=f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required",
        fix="uv python install 3.12",
    )


def check_tool(name: str, command: list[str], required: bool) -> Check:
    if shutil.which(command[0]) is None:
        return Check(
            name=name,
            status="missing",
            required=required,
            detail="not found on PATH",
            fix=_hint(name),
        )
    out = run_probe(command)
    if not out:
        return Check(
            name=name,
            status="warn",
            required=required,
            detail="found, but did not report a version",
        )
    return Check(name=name, status="ok", required=required, version=_version_from(out))


def check_disk(hw: HardwareInfo) -> Check:
    if hw.free_disk_gb >= MIN_FREE_DISK_GB:
        return Check(name="disk", status="ok", required=False, detail=f"{hw.free_disk_gb} GB free")
    return Check(
        name="disk",
        status="warn",
        required=False,
        detail=f"only {hw.free_disk_gb} GB free; proxies and indexes need space",
    )


def run_doctor(settings: Settings, disk_path: str = ".") -> DoctorReport:
    hw = detect_hardware(disk_path)
    rec = recommend_tier(hw)
    checks = [check_python(), *(check_tool(*t) for t in _TOOLS), check_disk(hw)]
    selected = rec.tier if settings.model_tier == "auto" else settings.model_tier
    return DoctorReport(
        app_version=__version__,
        ok=all(c.status != "missing" for c in checks if c.required),
        checks=checks,
        hardware=hw,
        recommended=rec,
        selected_tier=selected,
    )
