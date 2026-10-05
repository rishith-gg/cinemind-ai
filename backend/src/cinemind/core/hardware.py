"""Hardware detection and model-tier selection (SPEC §6). No heavy ML imports here."""

import platform
import shutil
import subprocess
from typing import Literal

import psutil
from pydantic import BaseModel

GpuKind = Literal["cuda", "mps", "none"]
Tier = Literal["lite", "balanced", "quality"]

_GB = 1024**3


class GpuInfo(BaseModel):
    kind: GpuKind
    name: str | None = None
    vram_gb: float | None = None  # None for Apple (unified memory) and for no GPU


class HardwareInfo(BaseModel):
    os: str
    arch: str
    cpu_name: str
    cpu_cores: int
    ram_gb: float
    gpu: GpuInfo
    free_disk_gb: float


class TierRecommendation(BaseModel):
    tier: Tier
    reason: str


def run_probe(args: list[str], timeout: float = 5.0) -> str | None:
    """Run a read-only probe command (argument list, never a shell). None on any failure."""
    if shutil.which(args[0]) is None:
        return None
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _cpu_name() -> str:
    if platform.system() == "Darwin":
        name = run_probe(["sysctl", "-n", "machdep.cpu.brand_string"])
        if name:
            return name
    return platform.processor() or platform.machine() or "unknown"


def _detect_gpu(cpu_name: str) -> GpuInfo:
    out = run_probe(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
    )
    if out:
        name, _, mem_mb = out.splitlines()[0].partition(",")
        try:
            vram = round(float(mem_mb) / 1024, 1)
        except ValueError:
            vram = None
        return GpuInfo(kind="cuda", name=name.strip(), vram_gb=vram)
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return GpuInfo(kind="mps", name=cpu_name)  # Apple GPU shares system RAM
    return GpuInfo(kind="none")


def detect_hardware(disk_path: str = ".") -> HardwareInfo:
    cpu_name = _cpu_name()
    return HardwareInfo(
        os=f"{platform.system()} {platform.release()}",
        arch=platform.machine(),
        cpu_name=cpu_name,
        cpu_cores=psutil.cpu_count(logical=True) or 1,
        ram_gb=round(psutil.virtual_memory().total / _GB, 1),
        gpu=_detect_gpu(cpu_name),
        free_disk_gb=round(shutil.disk_usage(disk_path).free / _GB, 1),
    )


def recommend_tier(hw: HardwareInfo) -> TierRecommendation:
    """Map hardware to a tier using the SPEC §6 table."""
    gpu = hw.gpu
    if gpu.kind == "cuda" and gpu.vram_gb is not None:
        if gpu.vram_gb >= 8:
            return TierRecommendation(
                tier="quality", reason=f"NVIDIA GPU with {gpu.vram_gb} GB VRAM"
            )
        if gpu.vram_gb >= 4:
            return TierRecommendation(
                tier="balanced", reason=f"NVIDIA GPU with {gpu.vram_gb} GB VRAM"
            )
    if hw.ram_gb >= 16:
        return TierRecommendation(tier="balanced", reason=f"{hw.ram_gb} GB RAM (CPU/MPS path)")
    extra = (
        " Apple GPU (MPS) helps PyTorch models, but speech recognition runs on CPU."
        if gpu.kind == "mps"
        else ""
    )
    return TierRecommendation(
        tier="lite", reason=f"Only {hw.ram_gb} GB RAM and no CUDA GPU with 4+ GB.{extra}"
    )
