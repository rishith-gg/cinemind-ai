"""The AI-assisted rough cut through the API: building from a brief, editing, swapping and
exporting. Uses the processed `cuts.mp4` project of the search tests (four shots of 2.0, 1.52,
2.48 and 2.0 s; one certain spoken line at 0.2-1.8 s in the first, one uncertain at 6.2-7.6 s)."""

import re
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import otio_read
from cinemind.core.config import Settings
from cinemind.core.rough_cut_config import RoughCutConfig
from search_helpers import processed_cuts

BANNER = "AI-assisted rough cut. Human review required."


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
    # The synthetic pictures (test pattern, flat blue) are not judged on quality here.
    api_settings.rough_cut = RoughCutConfig(min_quality=0.0)
    return found


def _cut(client: TestClient, pid: str, **body: Any) -> dict[str, Any]:
    res = client.post(f"/api/projects/{pid}/rough-cut", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def _length(timeline: dict[str, Any]) -> float:
    return sum(i["source_out_s"] - i["source_in_s"] for i in timeline["items"])


def test_rough_cut_from_a_brief_explains_every_clip(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    cut = _cut(client, pid, brief="6 second sequence about the forest")
    assert cut["kind"] == "rough_cut" and cut["params"]["banner"] == BANNER
    assert cut["params"]["understood"] == ["length: 6 s", "looking for: the forest"]
    assert cut["params"]["target_s"] == 6 and cut["params"]["target_from"] == "brief"
    assert cut["params"]["built_s"] < 60
    assert 6 * 0.9 - 0.05 <= _length(cut) <= 6 * 1.1 + 0.05
    for item in cut["items"]:
        reason = item["reason"]
        assert reason["summary"].startswith(f"Result {reason['rank']} of ")
        assert set(reason["breakdown"]) >= {"relevance", "quality", "duplicate"}
        assert reason["trim"]["how"] in ("speech", "around match", "whole shot")
        assert item["keyframe_id"] and item["media_duration_s"] == pytest.approx(8.0, abs=0.1)
    # The shot with the spoken line keeps the whole line (0.2-1.8 s plus room, inside the shot).
    spoken = next(i for i in cut["items"] if i["shot_id"] == project["shots"][0])
    assert spoken["reason"]["trim"]["how"] == "speech"
    assert spoken["reason"]["trim"]["lines"] == ["walking into the forest now"]
    assert spoken["source_in_s"] == 0.0 and spoken["source_out_s"] == pytest.approx(2.0)
    # The uncertain line (6.2-7.6 s) never makes the last shot a speech clip.
    for item in cut["items"]:
        if item["shot_id"] == project["shots"][3]:
            assert item["reason"]["trim"]["how"] != "speech"
    # Chronological by default: in source order.
    starts = [i["source_in_s"] for i in cut["items"]]
    assert starts == sorted(starts)


def test_length_order_and_name_from_the_request_win(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    cut = _cut(
        client, pid, brief="1 minute of forest in order", target_s=3, order="score", name="Short"
    )
    assert cut["name"] == "Short" and cut["params"]["order"] == "score"
    assert cut["params"]["target_from"] == "you"
    assert _length(cut) <= 3 * 1.1 + 0.05
    ranks = [i["reason"]["rank"] for i in cut["items"]]
    assert ranks == sorted(ranks)
    # Shots not needed are kept as swap suggestions, with their own reasons.
    assert cut["alternatives"] and all(a["summary"] for a in cut["alternatives"])


def test_brief_without_subject_uses_every_shot_and_leaves_out_rejected_and_poor_ones(
    client: TestClient, pid: str, project: dict[str, Any], api_settings: Settings
) -> None:
    rejected = project["shots"][2]
    res = client.put(f"/api/shots/{rejected}/mark", json={"mark": "reject"})
    assert res.status_code == 200, res.text
    cut = _cut(client, pid, brief="8 seconds")
    assert cut["params"]["query"] == ""
    used = {i["shot_id"] for i in cut["items"]}
    assert rejected not in used and rejected not in {a["shot_id"] for a in cut["alternatives"]}
    assert used == {project["shots"][0], project["shots"][1], project["shots"][3]}

    # The flat dark blue shot scores 0 on quality: under the limit it is left out, with why.
    api_settings.rough_cut = RoughCutConfig(min_quality=0.5)
    cut = _cut(client, pid, brief="8 seconds")
    flat = project["shots"][3]
    assert flat not in {i["shot_id"] for i in cut["items"]}
    left = {e["shot_id"]: e["why"] for e in cut["params"]["left_out"]}
    assert left[flat] == "quality 0.00 is below 0.5"

    api_settings.rough_cut = RoughCutConfig(min_quality=0.0, min_clip_s=5.0)
    res = client.post(f"/api/projects/{pid}/rough-cut", json={"brief": "8 seconds"})
    assert res.status_code == 422
    assert "quality limit, too short" in res.json()["message"]


def test_brief_errors_are_friendly(client: TestClient, pid: str, project: dict[str, Any]) -> None:
    res = client.post(f"/api/projects/{pid}/rough-cut", json={"brief": ""})
    assert res.status_code == 422
    res = client.post(f"/api/projects/{pid}/rough-cut", json={"brief": "x", "fps": [7, 1]})
    assert res.status_code == 422 and "not a supported" in res.json()["message"]
    res = client.post("/api/projects/" + "0" * 32 + "/rough-cut", json={"brief": "forest"})
    assert res.status_code == 404


def test_editor_reorders_trims_removes_and_renames(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    cut = _cut(client, pid, brief="8 seconds")
    items = cut["items"]
    assert len(items) >= 3
    first, second, third = items[0], items[1], items[2]
    edits = [
        {
            "id": third["id"],
            "source_in_s": third["source_in_s"],
            "source_out_s": third["source_out_s"],
        },
        {"id": first["id"], "source_in_s": 0.52, "source_out_s": 1.52},  # on the 25 fps grid
    ]
    res = client.patch(f"/api/timelines/{cut['id']}", json={"name": "Mine", "items": edits})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["name"] == "Mine" and [i["id"] for i in out["items"]] == [third["id"], first["id"]]
    assert (out["items"][1]["source_in_s"], out["items"][1]["source_out_s"]) == (0.52, 1.52)
    assert out["items"][1]["record_frame"] == out["items"][0]["duration_frames"]  # gapless
    assert second["shot_id"] not in {i["shot_id"] for i in out["items"]}
    assert out["warnings"] == []  # removing clips yourself is not "clips removed from project"
    again = client.get(f"/api/timelines/{cut['id']}").json()
    assert [i["id"] for i in again["items"]] == [third["id"], first["id"]]

    bad = [
        [{"id": "nope", "source_in_s": 0, "source_out_s": 1}],
        [{"id": first["id"], "source_in_s": 1.0, "source_out_s": 1.0}],
        [{"id": first["id"], "source_in_s": -1, "source_out_s": 1}],
        [{"id": first["id"], "source_in_s": 0, "source_out_s": 99}],
        [{"id": first["id"], "source_in_s": 0, "source_out_s": 1}] * 2,
    ]
    for body in bad:
        res = client.patch(f"/api/timelines/{cut['id']}", json={"items": body})
        assert res.status_code == 422, body
        assert res.json().get("message") or res.json().get("detail")  # domain or schema error


def test_swap_puts_a_suggestion_in_and_the_old_clip_back_as_one(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    cut = _cut(client, pid, brief="2 seconds of forest", order="score")
    item = cut["items"][0]
    suggestion = cut["alternatives"][0]
    res = client.post(
        f"/api/timelines/{cut['id']}/items/{item['id']}/swap",
        json={"shot_id": suggestion["shot_id"]},
    )
    assert res.status_code == 200, res.text
    out = res.json()
    swapped = next(i for i in out["items"] if i["id"] == item["id"])
    assert swapped["shot_id"] == suggestion["shot_id"]
    assert swapped["reason"]["summary"] == suggestion["summary"]
    assert swapped["source_in_s"] >= suggestion["start_s"] - 1e-6
    assert swapped["source_out_s"] <= suggestion["end_s"] + 1e-6
    assert item["shot_id"] in {a["shot_id"] for a in out["alternatives"]}
    # A shot already on the timeline cannot be added twice; an unknown shot is not found.
    if len(out["items"]) > 1:
        other = next(i for i in out["items"] if i["id"] != item["id"])
        res = client.post(
            f"/api/timelines/{cut['id']}/items/{item['id']}/swap",
            json={"shot_id": other["shot_id"]},
        )
        assert res.status_code == 422
    res = client.post(
        f"/api/timelines/{cut['id']}/items/{item['id']}/swap", json={"shot_id": "nope"}
    )
    assert res.status_code == 404


def test_rough_cut_exports_with_markers_banner_and_subtitles(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    cut = _cut(client, pid, brief="8 seconds")
    tid = cut["id"]
    xml = client.get(f"/api/timelines/{tid}/export/fcp7xml").text
    assert f"<!-- {BANNER} -->" in xml
    assert xml.count("<marker>") == len(cut["items"])
    assert "Result 1 of" in xml
    edl = client.get(f"/api/timelines/{tid}/export/edl").text
    assert f"* {BANNER}" in edl and edl.count("* WHY: ") == len(cut["items"])
    otio_text = client.get(f"/api/timelines/{tid}/export/otio").text
    assert BANNER in otio_text and "Why this clip" in otio_text
    for fmt, text in (("fcp7xml", xml), ("edl", edl), ("otio", otio_text)):
        back = otio_read.read(text, fmt, Fraction(cut["fps_num"], cut["fps_den"]))
        assert [c.duration for c in back.video] == [i["duration_frames"] for i in cut["items"]]

    srt = client.get(f"/api/timelines/{tid}/export/srt")
    assert srt.status_code == 200, srt.text
    blocks = srt.text.strip().split("\n\n")
    assert len(blocks) == 1  # the certain line only; the uncertain one is never a subtitle
    number, times, text = blocks[0].split("\n")
    assert number == "1" and text == "walking into the forest now"
    start, end = re.findall(r"(\d\d):(\d\d):(\d\d),(\d\d\d)", times)
    seconds = [
        int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000 for h, m, s, ms in (start, end)
    ]
    assert seconds[0] == pytest.approx(0.2, abs=0.05) and seconds[1] == pytest.approx(1.8, abs=0.05)


def test_srt_without_speech_in_the_cuts_says_so(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    cut = _cut(client, pid, brief="8 seconds")
    keep = [i for i in cut["items"] if i["shot_id"] != project["shots"][0]]
    body = {"items": [{k: i[k] for k in ("id", "source_in_s", "source_out_s")} for i in keep]}
    assert client.patch(f"/api/timelines/{cut['id']}", json=body).status_code == 200
    res = client.get(f"/api/timelines/{cut['id']}/export/srt")
    assert res.status_code == 422 and "no subtitles" in res.json()["message"]


def _edits(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: i[k] for k in ("id", "source_in_s", "source_out_s")} for i in items]


def test_edit_refuses_non_numbers_and_clips_under_a_frame(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    cut = _cut(client, pid, brief="8 seconds")
    item = cut["items"][0]
    url = f"/api/timelines/{cut['id']}"
    for value in ("NaN", "Infinity"):
        body = f'{{"items": [{{"id": "{item["id"]}", "source_in_s": 0, "source_out_s": {value}}}]}}'
        res = client.patch(url, content=body, headers={"content-type": "application/json"})
        assert res.status_code == 422, value
    one_frame = [{"id": item["id"], "source_in_s": 0.0, "source_out_s": 0.04}]  # 25 fps
    assert client.patch(url, json={"items": one_frame}).status_code == 200
    half = [{"id": item["id"], "source_in_s": 0.0, "source_out_s": 0.01}]
    res = client.patch(url, json={"items": half})
    assert res.status_code == 422 and "one frame" in res.json()["message"]
    assert client.get(url).status_code == 200  # still readable


def test_items_of_another_timeline_are_refused(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    first = _cut(client, pid, brief="8 seconds")
    second = _cut(client, pid, brief="4 seconds")
    res = client.patch(f"/api/timelines/{second['id']}", json={"items": _edits(first["items"][:1])})
    assert res.status_code == 422 and "not on this timeline" in res.json()["message"]


def test_trim_by_hand_is_explained_and_removed_clips_come_back_as_suggestions(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    cut = _cut(client, pid, brief="8 seconds")
    first, *rest = cut["items"]
    trimmed = {**first, "source_in_s": first["source_in_s"] + 0.2}
    out = client.patch(
        f"/api/timelines/{cut['id']}", json={"items": _edits([trimmed, *rest[:-1]])}
    ).json()
    reason = out["items"][0]["reason"]
    assert reason["trim"]["how"] == "by you" and reason["auto_trim"] == first["reason"]["trim"]
    gone = rest[-1]
    assert out["alternatives"][0]["shot_id"] == gone["shot_id"]
    assert out["alternatives"][0]["summary"] == gone["reason"]["summary"]


def test_swapping_back_restores_the_clip_and_its_reason(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    cut = _cut(client, pid, brief="2 seconds of forest", order="score")
    item = cut["items"][0]
    suggestions = [a["shot_id"] for a in cut["alternatives"]]
    url = f"/api/timelines/{cut['id']}/items/{item['id']}/swap"
    client.post(url, json={"shot_id": suggestions[0]})
    back = client.post(url, json={"shot_id": item["shot_id"]}).json()
    restored = back["items"][0]
    assert restored["shot_id"] == item["shot_id"]
    assert restored["reason"]["summary"] == item["reason"]["summary"]
    assert sorted(a["shot_id"] for a in back["alternatives"]) == sorted(suggestions)


def test_emptying_a_timeline_yourself_is_not_called_a_removal_from_the_project(
    client: TestClient, pid: str, project: dict[str, Any]
) -> None:
    cut = _cut(client, pid, brief="8 seconds")
    assert client.patch(f"/api/timelines/{cut['id']}", json={"items": []}).status_code == 200
    res = client.get(f"/api/timelines/{cut['id']}/export/fcp7xml")
    assert res.status_code == 422 and "has no clips" in res.json()["message"]
