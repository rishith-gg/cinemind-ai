"""Script alignment through the API on the processed `cuts.mp4` project: one certain spoken line
("walking into the forest now", 0.2-1.8 s) and one uncertain one ("the forest at night"), which
alignment never uses."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cinemind.core.config import Settings
from cinemind.core.script_config import ScriptConfig
from search_helpers import processed_cuts

SCRIPT = """INT. FOREST - DAY

ANNA
Walking into the forest now.

BEN
A storm is coming over the hills.

ANNA
The harbour lights went out an hour ago.
"""


@pytest.fixture
def project(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    cut_footage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    found = processed_cuts(client, pid, api_settings, cut_footage, tmp_path, monkeypatch)
    # The stand-in text vectors are hashes (meaningless): compare words only here.
    api_settings.script = ScriptConfig(lexical_weight=1.0, semantic_weight=0.0)
    return found


def _upload(client: TestClient, pid: str, text: str = SCRIPT) -> dict[str, Any]:
    res = client.post(f"/api/projects/{pid}/script", json={"name": "Forest", "text": text})
    assert res.status_code == 201, res.text
    return res.json()


def _dialogue(script: dict[str, Any]) -> list[dict[str, Any]]:
    return [line for line in script["lines"] if line["kind"] == "dialogue"]


def test_lines_are_found_in_the_transcript_with_scores_and_why(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    script = _upload(client, pid)
    assert script["format"] == "fountain" and script["name"] == "Forest"
    assert [line["kind"] for line in script["lines"]] == [
        "scene",
        "dialogue",
        "dialogue",
        "dialogue",
    ]
    assert script["alignment"]["segments"] == 1  # the uncertain line is never used
    assert script["dialogue_lines"] == 3 and script["with_take"] == 1
    found, absent, never = _dialogue(script)
    take = found["takes"][0]
    assert found["character"] == "ANNA" and found["scene"] == "INT. FOREST - DAY"
    assert found["chosen_take_id"] == take["id"] and found["why"] == "best match"
    assert take["filename"] == "cuts.mp4" and take["score"] == 1.0
    assert take["start_s"] == pytest.approx(0.2) and take["end_s"] == pytest.approx(1.8)
    assert absent["chosen_take_id"] is None and never["chosen_take_id"] is None
    assert "limit" in absent["why"] or "not found" in absent["why"]
    assert client.get(f"/api/projects/{pid}/script").json()["lines"] == script["lines"]


def test_choosing_takes_survives_aligning_again(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    script = _upload(client, pid)
    line = _dialogue(script)[0]
    take_id = line["takes"][0]["id"]
    url = f"/api/script-lines/{line['id']}/take"
    out = client.put(url, json={"not_filmed": True}).json()
    assert _dialogue(out)[0]["chosen_take_id"] is None
    assert _dialogue(out)[0]["why"] == "marked not filmed by you"
    out = client.put(url, json={"take_id": take_id}).json()
    assert _dialogue(out)[0]["why"] == "chosen by you"
    again = client.post(f"/api/projects/{pid}/script/align").json()
    assert _dialogue(again)[0]["choice"] == "take" and _dialogue(again)[0]["why"] == "chosen by you"
    assert _dialogue(again)[0]["chosen_take_id"] is not None
    out = client.put(url, json={}).json()
    assert _dialogue(out)[0]["choice"] == "auto"

    other = _dialogue(script)[2]["id"]
    res = client.put(f"/api/script-lines/{other}/take", json={"take_id": take_id})
    assert res.status_code == 404  # a take of another line
    res = client.put(url, json={"take_id": take_id, "not_filmed": True})
    assert res.status_code == 422


def test_script_assembly_is_a_timeline_in_script_order_with_why(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    _upload(client, pid)
    res = client.post(f"/api/projects/{pid}/script/assembly", json={})
    assert res.status_code == 201, res.text
    cut = res.json()
    assert cut["kind"] == "script_cut" and cut["name"] == "Script assembly: Forest"
    assert cut["params"]["banner"] == "AI-assisted rough cut. Human review required."
    assert cut["params"]["lines_used"] == 1 and len(cut["params"]["left_out_lines"]) == 2
    (item,) = cut["items"]
    assert item["source_in_s"] == pytest.approx(0.0, abs=0.05)  # 0.2 s minus 0.25 s room
    assert item["source_out_s"] == pytest.approx(2.04, abs=0.05)
    assert item["reason"]["summary"].startswith("Script line 1 (ANNA): take 1 of")
    assert item["shot_id"] == project["shots"][0] and item["keyframe_id"]
    assert item["reason"]["script_lines"][0]["heard"] == "walking into the forest now"
    xml = client.get(f"/api/timelines/{cut['id']}/export/fcp7xml").text
    assert "Script line 1 (ANNA)" in xml and xml.count("<marker>") == 1


def test_script_errors_are_friendly(client: TestClient, pid: str, project: dict[str, Any]) -> None:
    res = client.get(f"/api/projects/{pid}/script")
    assert res.status_code == 404 and "no script yet" in res.json()["message"]
    res = client.post(f"/api/projects/{pid}/script", json={"text": "INT. ROOM\n\nNothing."})
    assert res.status_code == 422 and "No dialogue" in res.json()["message"]
    _upload(client, pid, "ANNA\nNever said anywhere at all.\n")
    res = client.post(f"/api/projects/{pid}/script/assembly", json={})
    assert res.status_code == 422 and "No script line has a take" in res.json()["message"]
    assert client.delete(f"/api/projects/{pid}/script").status_code == 204
    assert client.get(f"/api/projects/{pid}/script").status_code == 404


def test_a_new_script_replaces_the_old_one(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    first = _upload(client, pid)
    second = _upload(client, pid, "Walking into the forest now.")
    assert second["id"] != first["id"] and second["format"] == "plain"
    assert client.get(f"/api/projects/{pid}/script").json()["id"] == second["id"]


def test_words_only_limit_when_meaning_has_no_weight(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    """The stand-in text model is there, but the weight of meaning is 0: words only, with the
    words-only limit, and no model recorded as used."""
    script = _upload(client, pid)
    assert script["alignment"]["semantic"] is False and script["alignment"]["text_model"] is None
    assert script["min_score"] == ScriptConfig().words_only_min_score


def test_choices_survive_replacing_the_script_for_unchanged_lines(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    script = _upload(client, pid)
    found, absent, _ = _dialogue(script)
    client.put(f"/api/script-lines/{found['id']}/take", json={"take_id": found["takes"][0]["id"]})
    client.put(f"/api/script-lines/{absent['id']}/take", json={"not_filmed": True})
    changed = SCRIPT.replace("A storm is coming over the hills.", "A storm is coming.")
    lines = _dialogue(_upload(client, pid, changed))
    assert lines[0]["choice"] == "take" and lines[0]["why"] == "chosen by you"
    assert lines[1]["choice"] == "auto"  # its words changed: the choice does not carry over


def test_lines_from_one_running_take_play_as_one_clip(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    _upload(client, pid, "ANNA\nWalking into\n\nANNA\nthe forest now\n")
    cut = client.post(f"/api/projects/{pid}/script/assembly", json={"name": "Two lines"}).json()
    assert cut["name"] == "Two lines" and len(cut["items"]) == 1
    (item,) = cut["items"]
    assert [entry["line"] for entry in item["reason"]["script_lines"]] == [1, 2]
    assert item["reason"]["summary"].endswith("Plays 2 lines.")


def test_choice_on_a_scene_line_or_for_an_unknown_project_is_not_found(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    scene = _upload(client, pid)["lines"][0]
    assert client.put(f"/api/script-lines/{scene['id']}/take", json={}).status_code == 404
    res = client.post("/api/projects/" + "0" * 32 + "/script", json={"text": "Hi."})
    assert res.status_code == 404
    res = client.put(f"/api/script-lines/{scene['id']}/take", json={"take_id": ""})
    assert res.status_code == 422
