import pytest

from cinemind.core import doctor
from cinemind.core.config import Settings
from cinemind.core.doctor import check_tool, run_doctor


def _no_tool(_name: str) -> None:
    return None


def _any_tool(_name: str) -> str:
    return "/x/tool"


def _ffmpeg_version(_args: list[str]) -> str:
    return "ffmpeg version 9.0.2 Copyright (c)"


def test_missing_tool_reports_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", _no_tool)
    check = check_tool("ffmpeg", ["ffmpeg", "-version"], required=True)
    assert check.status == "missing" and check.required and check.fix


def test_version_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", _any_tool)
    monkeypatch.setattr(doctor, "run_probe", _ffmpeg_version)
    assert check_tool("ffmpeg", ["ffmpeg", "-version"], True).version == "9.0.2"


def test_report_fails_when_required_tool_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", _no_tool)
    report = run_doctor(Settings())
    assert not report.ok
    assert {c.name for c in report.checks if c.status == "missing" and c.required} >= {"ffmpeg"}


def test_tier_override_wins() -> None:
    assert run_doctor(Settings(model_tier="quality")).selected_tier == "quality"


def test_real_doctor_runs() -> None:
    report = run_doctor(Settings())
    assert report.hardware.cpu_cores >= 1 and report.hardware.ram_gb > 0
