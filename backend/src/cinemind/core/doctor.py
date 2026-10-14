"""`cinemind doctor`: real environment checks plus a model-tier recommendation."""

import platform
import shutil
import sys
from typing import Literal

from pydantic import BaseModel

from cinemind import __version__
from cinemind.core import face_config
from cinemind.core.config import Settings
from cinemind.core.embed_config import TEXT_MODELS, TIER_TEXT, TIER_VISUAL, VISUAL_MODELS
from cinemind.core.hardware import (
    HardwareInfo,
    Tier,
    TierRecommendation,
    detect_hardware,
    recommend_tier,
    run_probe,
)
from cinemind.core.transcribe_config import TIER_MODEL, WHISPER_MODELS, model_dir, model_ready

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


def check_speech_model(settings: Settings, tier: Tier) -> Check:
    """Is the Whisper model for this tier on disk? Optional: everything but transcripts works
    without it, and it is only ever fetched by `cinemind models pull`."""
    name = settings.transcribe.model
    name = TIER_MODEL[tier] if name == "auto" else name
    spec = WHISPER_MODELS[name]
    if model_ready(model_dir(settings.models_path, name)):
        return Check(name="speech model", status="ok", required=False, version=name)
    return Check(
        name="speech model",
        status="warn",
        required=False,
        version=name,
        detail=f"not downloaded ({spec.size_mb} MB); clips are processed without transcripts",
        fix="uv run cinemind models pull",
    )


def check_face_models(settings: Settings) -> Check:
    """Are the face models on disk? Optional: everything but faces and actors works without."""
    if face_config.models_ready(settings.models_path):
        return Check(name="face models", status="ok", required=False, version=face_config.ENGINE)
    size_mb = sum(spec.size_kb for spec in face_config.FACE_MODELS) / 1024
    return Check(
        name="face models",
        status="warn",
        required=False,
        version=face_config.ENGINE,
        detail=f"not downloaded ({size_mb:.0f} MB); clips are processed without faces",
        fix="uv run cinemind models pull",
    )


def check_embed_models(settings: Settings, tier: Tier) -> Check:
    """Picture and text models (optional: without them there are no tags, scenes or search by
    meaning; everything else works)."""
    visual_key = settings.embed.visual_model
    text_key = settings.embed.text_model
    visual = VISUAL_MODELS[TIER_VISUAL[tier] if visual_key == "auto" else visual_key]
    text = TEXT_MODELS[TIER_TEXT[tier] if text_key == "auto" else text_key]
    version = f"{visual.key} + {text.key}"
    missing = [s for s in (visual, text) if not s.ready(settings.models_path)]
    if not missing:
        return Check(name="picture/text models", status="ok", required=False, version=version)
    size = sum(s.size_mb for s in missing)
    return Check(
        name="picture/text models",
        status="warn",
        required=False,
        version=version,
        detail=f"not downloaded ({size} MB); clips are processed without tags and scenes",
        fix="uv run cinemind models pull",
    )


def run_doctor(settings: Settings, disk_path: str = ".") -> DoctorReport:
    hw = detect_hardware(disk_path)
    rec = recommend_tier(hw)
    selected = rec.tier if settings.model_tier == "auto" else settings.model_tier
    checks = [
        check_python(),
        *(check_tool(*t) for t in _TOOLS),
        check_disk(hw),
        check_speech_model(settings, selected),
        check_face_models(settings),
        check_embed_models(settings, selected),
    ]
    return DoctorReport(
        app_version=__version__,
        ok=all(c.status != "missing" for c in checks if c.required),
        checks=checks,
        hardware=hw,
        recommended=rec,
        selected_tier=selected,
    )
