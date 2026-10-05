from cinemind.core.hardware import GpuInfo, HardwareInfo, recommend_tier


def hw(ram: float, gpu: GpuInfo) -> HardwareInfo:
    return HardwareInfo(
        os="Test", arch="x", cpu_name="cpu", cpu_cores=8, ram_gb=ram, gpu=gpu, free_disk_gb=100
    )


def test_small_ram_no_gpu_is_lite() -> None:
    assert recommend_tier(hw(8, GpuInfo(kind="none"))).tier == "lite"


def test_apple_8gb_is_lite_and_mentions_mps() -> None:
    rec = recommend_tier(hw(8, GpuInfo(kind="mps", name="Apple M1")))
    assert rec.tier == "lite" and "MPS" in rec.reason


def test_16gb_cpu_is_balanced() -> None:
    assert recommend_tier(hw(16, GpuInfo(kind="none"))).tier == "balanced"


def test_cuda_vram_thresholds() -> None:
    assert recommend_tier(hw(8, GpuInfo(kind="cuda", vram_gb=6))).tier == "balanced"
    assert recommend_tier(hw(16, GpuInfo(kind="cuda", vram_gb=12))).tier == "quality"
    assert recommend_tier(hw(8, GpuInfo(kind="cuda", vram_gb=2))).tier == "lite"
