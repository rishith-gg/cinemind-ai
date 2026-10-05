import json

from typer.testing import CliRunner

from cinemind.cli import app

runner = CliRunner()


def test_doctor_json() -> None:
    result = runner.invoke(app, ["doctor", "--json"])
    data = json.loads(result.output)
    assert "recommended" in data and result.exit_code in (0, 1)


def test_doctor_table() -> None:
    assert "Recommended model tier" in runner.invoke(app, ["doctor"]).output
