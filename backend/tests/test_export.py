from fractions import Fraction as F
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

import otio_read
from cinemind.core.config import Settings
from cinemind.core.errors import InvalidInputError
from cinemind.db.models import MediaAsset, Timeline
from cinemind.export import service
from cinemind.export.sequence import (
    Cut,
    Sequence,
    Source,
    build_sequence,
    export_rate,
    source_start,
)
from cinemind.export.srt import subtitles, write_srt
from cinemind.rough_cut.assembly import natural_key
from cinemind.search.spoken import SpokenLine, Word
from cinemind.utils.timecode import tc_to_frames
from helpers import drain, import_one

NTSC60 = F(60000, 1001)
FORMATS = ("fcp7xml", "edl", "otio")


def _source(name: str, rate: F, frames: int, channels: int, tc: str | None = None) -> Source:
    path = f"/Volumes/Foot age/{name}"
    return Source(
        media_id=name,
        name=name,
        path=path,
        url=Path(path).as_uri(),
        rate=rate,
        frames=frames,
        tc_start=tc_to_frames(tc, rate) if tc else 0,
        drop=bool(tc and ";" in tc),
        width=3840,
        height=2160,
        channels=channels,
        sample_rate=48000,
    )


@pytest.fixture
def seq() -> Sequence:
    """Stereo clip cut twice, a drop-frame clip without audio, and a mono clip at another rate."""
    stereo = _source("IMG 0870 é.MOV", NTSC60, 372, 2)
    timecoded = _source("tc.mov", NTSC60, 600, 0, "01:00:00;00")
    slow = _source("slow.mov", F(24), 240, 1)
    out = Sequence("All shots", NTSC60, 3840, 2160)
    record = 0
    for source, src_in, duration in ((stereo, 0, 100), (stereo, 100, 150), (timecoded, 30, 60)):
        out.cuts.append(Cut(source, NTSC60, src_in, duration, record))
        record += duration
    out.cuts.append(Cut(slow, NTSC60, 60, 120, record))
    return out


@pytest.mark.parametrize("fmt", FORMATS)
def test_round_trip_keeps_every_cut(seq: Sequence, fmt: str) -> None:
    back = otio_read.read(service.render(seq, fmt), fmt, seq.rate)
    assert seq.start_frame == 216000  # 01:00:00:00
    if fmt != "edl":  # OTIO's EDL reader keeps record times relative; see test_edl_text
        assert back.start == seq.start_frame
    assert [(c.name, c.source_start, c.duration, c.record) for c in back.video] == [
        (c.source.name, source_start(c), c.duration, c.record) for c in seq.cuts
    ]
    assert back.video[2].source_start == 215784 + 30  # 01:00:00;00 drop-frame at 59.94, plus in
    assert all(c.exact for c in back.video)
    with_audio = [c for c in seq.cuts if c.source.channels]
    assert [(c.name, c.record) for c in back.audio[0]] == [
        (c.source.name, c.record) for c in with_audio
    ]
    if fmt != "edl":  # an EDL has no file paths, only clip names
        assert {c.url for c in back.video} == {c.source.url for c in seq.cuts}
        assert "Foot%20age/IMG%200870%20%C3%A9.MOV" in str(back.video[0].url)


def test_fcp7xml_structure(seq: Sequence) -> None:
    text = service.render(seq, "fcp7xml")
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>')
    root = ET.fromstring(text)  # noqa: S314 - our own output
    sequence = root.find("sequence")
    assert sequence is not None
    assert sequence.findtext("rate/timebase") == "60" and sequence.findtext("rate/ntsc") == "TRUE"
    assert sequence.findtext("duration") == "430"
    assert sequence.findtext("timecode/string") == "01:00:00:00"
    video = sequence.findall("media/video/track")
    audio = sequence.findall("media/audio/track")
    # One audio item per cut, stereo or mono: one per channel doubles the sound in Resolve.
    assert [len(t.findall("clipitem")) for t in video + audio] == [4, 3]  # V1, A1

    # Each file is described once and referenced afterwards.
    files = root.findall(".//file")
    assert sum(1 for f in files if f.find("pathurl") is not None) == 3
    timecoded = next(f for f in files if f.findtext("name") == "tc.mov")
    assert timecoded.findtext("timecode/string") == "01:00:00;00"
    assert timecoded.findtext("timecode/displayformat") == "DF"
    assert timecoded.find("media/audio") is None
    slow = next(f for f in files if f.findtext("name") == "slow.mov")
    assert slow.findtext("rate/timebase") == "24" and slow.findtext("duration") == "240"

    # Links point at real clip items, at the position they claim.
    tracks = {"video": video, "audio": audio}
    ids = {c.get("id") for c in root.iter("clipitem")}
    links = list(root.iter("link"))
    assert (
        len(links) == 3 * 2 * 2
    )  # three cuts with sound, picture + sound each; none for video-only
    for link in links:
        track = tracks[str(link.findtext("mediatype"))][int(str(link.findtext("trackindex"))) - 1]
        target = track.findall("clipitem")[int(str(link.findtext("clipindex"))) - 1]
        assert target.get("id") == link.findtext("linkclipref") and target.get("id") in ids


def test_edl_text(seq: Sequence) -> None:
    lines = service.render(seq, "edl").splitlines()
    assert lines[:2] == ["TITLE: All shots", "FCM: NON-DROP FRAME"]
    events = [line for line in lines if line[:3].isdigit()]
    assert (
        events[0] == "001  AX       AA/V  C        00:00:00:00 00:00:01:40 01:00:00:00 01:00:01:40"
    )
    assert (
        events[2] == "003  AX       V     C        01:00:00;30 01:00:01;30 01:00:04:10 01:00:05:10"
    )
    assert events[3].split()[2] == "B"  # video + one audio channel
    assert "* FROM CLIP NAME: IMG 0870 é.MOV" in lines


def _asset(
    name: str, fps: tuple[int, int], nominal: tuple[int, int] | None, **more: Any
) -> MediaAsset:
    values: dict[str, Any] = {
        "id": name,
        "filename": name,
        "path": f"/nowhere/{name}",
        "duration_s": 10.0,
        "width": 1920,
        "height": 1080,
        "audio_codec": "aac",
        "audio_channels": 2,
        "audio_sample_rate": 48000,
        "start_timecode": None,
        "is_vfr": False,
    }
    values.update(more, fps_num=fps[0], fps_den=fps[1])
    values["nominal_fps_num"], values["nominal_fps_den"] = nominal or (None, None)
    return cast(MediaAsset, SimpleNamespace(**values))


def test_export_rate_prefers_a_plausible_nominal_rate() -> None:
    assert export_rate(_asset("phone120", (67575, 566), (120, 1))) == F(120)
    assert export_rate(_asset("phone60", (96000, 1601), (60000, 1001))) == NTSC60
    assert export_rate(_asset("no_nominal", (76950, 1283), None)) == F(60)
    assert export_rate(_asset("bogus_nominal", (25, 1), (90000, 1))) == F(25)


def _timeline(rate: F, items: list[tuple[str, float, float]], built: int = 0) -> Timeline:
    rows = [
        SimpleNamespace(
            id=f"item-{n}", media_id=m, shot_id=None, source_in_s=a, source_out_s=b, reason=None
        )
        for n, (m, a, b) in enumerate(items)
    ]
    values: dict[str, Any] = {"name": "t", "fps_num": rate.numerator, "fps_den": rate.denominator}
    values.update(kind="all_shots", params={"built_items": built or len(rows)})
    return cast(Timeline, SimpleNamespace(**values, width=1920, height=1080, items=rows))


def test_build_sequence_is_gapless_clamped_and_warns() -> None:
    assets = {
        "a.mov": _asset("a.mov", (25, 1), (25, 1)),
        "b.mov": _asset("b.mov", (30000, 1001), (30000, 1001), start_timecode="garbage"),
    }
    timeline = _timeline(
        F(25),
        [("a.mov", 0.0, 2.0), ("a.mov", 2.0, 3.52), ("a.mov", 3.52, 99.0), ("b.mov", 1.0, 2.0)],
    )
    built = build_sequence(timeline, assets)
    cuts = built.cuts
    assert [(c.src_in, c.duration, c.record) for c in cuts[:3]] == [
        (0, 50, 0),
        (50, 38, 50),
        (88, 162, 88),  # out point clamped to the 250-frame file
    ]
    for before, after in zip(cuts[:2], cuts[1:3], strict=True):  # through edits: no gap, no overlap
        assert before.src_in + before.duration == after.src_in
        assert before.record + before.duration == after.record
    assert cuts[3].mixed_rate and (cuts[3].src_in, cuts[3].duration) == (25, 25)
    text = " ".join(built.warnings)
    assert "unreadable start timecode" in text and "original file is missing" in text
    assert "do not match the timeline rate of 25 fps (b.mov)" in text


def test_variable_rate_clip_is_counted_at_its_average_rate_and_flagged() -> None:
    # The user's 120 fps phone clip: 7.545 s averaging 119.39 fps holds ~901 frames, not 905.
    phone = _asset("phone120.mov", (67575, 566), (120, 1), duration_s=7.545011, is_vfr=True)
    built = build_sequence(_timeline(F(120), [("phone120.mov", 0.0, 7.545011)]), {phone.id: phone})
    source = built.cuts[0].source
    assert source.rate == F(120) and source.frames == 901
    assert built.cuts[0].duration == 901  # the out point stays inside the media
    assert "variable frame rate (phone120.mov)" in " ".join(built.warnings)


def test_cuts_past_the_end_and_removed_clips_are_reported() -> None:
    assets = {"a.mov": _asset("a.mov", (25, 1), (25, 1))}
    timeline = _timeline(F(25), [("a.mov", 0.0, 2.0), ("a.mov", 10.0, 12.0)], built=5)
    built = build_sequence(timeline, assets)
    assert [(c.src_in, c.duration) for c in built.cuts] == [(0, 50)]
    text = " ".join(built.warnings)
    assert "3 of the 5 cuts" in text and "1 cut(s) start after the end" in text


def test_drop_flag_needs_a_rate_that_can_drop() -> None:
    film = _asset("film.mov", (24000, 1001), (24000, 1001), start_timecode="01:00:00;00")
    built = build_sequence(_timeline(F(24000, 1001), [("film.mov", 0.0, 1.0)]), {film.id: film})
    assert not built.cuts[0].source.drop
    assert "<displayformat>DF</displayformat>" not in service.render(built, "fcp7xml")


def test_edl_refuses_what_the_format_cannot_hold(seq: Sequence) -> None:
    fast = Sequence("fast", F(120), 1920, 1080, cuts=[Cut(seq.cuts[0].source, F(120), 0, 240, 0)])
    with pytest.raises(InvalidInputError, match="above 60 fps"):
        service.render(fast, "edl")
    cut = seq.cuts[0]
    many = Sequence("many", NTSC60, 1920, 1080, cuts=[cut] * 1000)
    with pytest.raises(InvalidInputError, match="at most 999 cuts"):
        service.render(many, "edl")
    assert "<xmeml" in service.render(fast, "fcp7xml")  # the other formats still work


def test_otio_file_says_what_the_timeline_is(seq: Sequence) -> None:
    text = service.render(seq, "otio")
    assert "nothing selected or ranked" in text and "AI-assisted" not in text


@pytest.mark.parametrize(
    ("name", "stem"),
    [
        ("All shots", "All shots"),
        ("Cut v1.5 final", "Cut v1_5 final"),
        ("../../etc/passwd", "passwd"),
        ("a/b\\c", "c"),
        ("タイムライン", "timeline"),
        ("...", "___"),
    ],
)
def test_timeline_name_becomes_one_safe_path_component(name: str, stem: str) -> None:
    got = service.file_stem(name)
    assert got == stem and "/" not in got and not got.startswith(".")


def test_natural_file_order() -> None:
    names = ["IMG_10.MOV", "img_2.mov", "IMG_1.MOV", "a.mp4"]
    assert sorted(names, key=natural_key) == ["a.mp4", "IMG_1.MOV", "img_2.mov", "IMG_10.MOV"]


# --- API --------------------------------------------------------------------------------------


@pytest.fixture
def cut_project(client: TestClient, api_settings: Settings, pid: str, cut_footage: Path) -> str:
    api_settings.media_roots.append(cut_footage)
    import_one(client, pid, cut_footage / "cuts.mp4")
    import_one(client, pid, cut_footage / "one_shot_ntsc.mov")
    drain(api_settings)
    return pid


def test_all_shots_timeline_exports_and_round_trips(
    client: TestClient, api_settings: Settings, cut_project: str, cut_footage: Path
) -> None:
    res = client.post(f"/api/projects/{cut_project}/timelines", json={"fps": [25, 1]})
    assert res.status_code == 201
    timeline = res.json()
    assert (timeline["fps_num"], timeline["fps_den"], timeline["kind"]) == (25, 1, "all_shots")
    items = timeline["items"]
    assert [(i["filename"], i["record_frame"], i["duration_frames"]) for i in items] == [
        ("cuts.mp4", 0, 50),
        ("cuts.mp4", 50, 38),
        ("cuts.mp4", 88, 62),
        ("cuts.mp4", 150, 50),
        ("one_shot_ntsc.mov", 200, 75),
    ]
    assert [i["mixed_rate"] for i in items] == [False] * 4 + [True]
    assert timeline["duration_frames"] == 275 and timeline["duration_s"] == 11.0
    assert "one_shot_ntsc.mov" in timeline["warnings"][0]
    assert timeline["params"]["clip_rates"] == {"25": 1, "29.97": 1}

    folder = Path(timeline["export_dir"])
    assert folder == api_settings.project_dir(cut_project) / "exports"
    for fmt in FORMATS:
        got = client.get(f"/api/timelines/{timeline['id']}/export/{fmt}")
        assert got.status_code == 200 and "attachment" in got.headers["content-disposition"]
        saved = folder / f"All shots_{timeline['id'][:8]}{service.EXTENSIONS[fmt]}"
        assert saved.read_text(encoding="utf-8") == got.text
        back = otio_read.read(got.text, fmt, F(25))
        assert [(c.name, c.duration, c.record) for c in back.video] == [
            (i["filename"], i["duration_frames"], i["record_frame"]) for i in items
        ]
        assert [c.source_start for c in back.video[:4]] == [0, 50, 88, 150]
        assert all(c.exact for c in back.video[:4])  # same rate as the timeline: frame exact
        # 01:00:00;00 at 29.97 is 107892 frames = 3599.9964 s = frame 90000 at 25 fps
        assert back.video[4].source_start == 90000
        if fmt != "edl":  # the original file, never the proxy
            assert back.video[0].url == (cut_footage / "cuts.mp4").resolve().as_uri()

    listed = client.get(f"/api/projects/{cut_project}/timelines").json()
    assert [t["id"] for t in listed] == [timeline["id"]] and listed[0]["item_count"] == 5
    assert client.get(f"/api/timelines/{timeline['id']}").json()["items"] == items


def test_default_rate_and_excluding_other_rates(client: TestClient, cut_project: str) -> None:
    url = f"/api/projects/{cut_project}/timelines"
    auto = client.post(url, json={"name": "Auto"}).json()
    # one clip at each rate: the tie goes to the higher rate
    assert (auto["fps_num"], auto["fps_den"]) == (30000, 1001)
    assert auto["params"]["rate_chosen_by"] == "most common clip rate"
    only = client.post(url, json={"fps": [25, 1], "mixed_rates": "exclude"}).json()
    assert {i["filename"] for i in only["items"]} == {"cuts.mp4"} and only["warnings"] == []
    assert only["params"]["excluded"] == ["one_shot_ntsc.mov"]
    none = client.post(url, json={"fps": [50, 1], "mixed_rates": "exclude"})
    assert none.status_code == 422 and "50 fps" in none.json()["message"]


def test_timeline_errors_are_friendly(client: TestClient, pid: str, cut_project: str) -> None:
    other = client.post("/api/projects", json={"name": "empty"}).json()["id"]
    empty = client.post(f"/api/projects/{other}/timelines", json={})
    assert empty.status_code == 422 and "no shots yet" in empty.json()["message"]
    url = f"/api/projects/{cut_project}/timelines"
    assert client.post(url, json={"fps": [0, 1]}).status_code == 422
    for bad_name in ("   ", "bad\u0001name"):
        assert client.post(url, json={"name": bad_name}).status_code == 422
    odd = client.post(url, json={"fps": [17, 1]})
    assert odd.status_code == 422 and "not a supported" in odd.json()["message"]
    assert client.post("/api/projects/" + "0" * 32 + "/timelines", json={}).status_code == 404

    timeline = client.post(url, json={}).json()["id"]
    bad = client.get(f"/api/timelines/{timeline}/export/aaf")
    assert bad.status_code == 422 and "fcp7xml" in bad.json()["message"]
    assert client.get("/api/timelines/nope").status_code == 404

    # Removing a clip removes its cuts, and the timeline says so.
    media = {
        m["filename"]: m["id"] for m in client.get(f"/api/projects/{cut_project}/media").json()
    }
    assert client.delete(f"/api/media/{media['one_shot_ntsc.mov']}").status_code == 204
    partial = client.get(f"/api/timelines/{timeline}").json()
    assert partial["item_count"] == 4 and "1 of the 5 cuts" in " ".join(partial["warnings"])
    # Removing the rest empties it; exporting it says why.
    assert client.delete(f"/api/media/{media['cuts.mp4']}").status_code == 204
    assert client.get(f"/api/timelines/{timeline}").json()["item_count"] == 0
    gone = client.get(f"/api/timelines/{timeline}/export/edl")
    assert gone.status_code == 422 and "empty" in gone.json()["message"]
    assert client.delete(f"/api/timelines/{timeline}").status_code == 204
    assert client.delete(f"/api/timelines/{timeline}").status_code == 404


def test_srt_places_words_inside_each_cut_at_their_timeline_time(seq: Sequence) -> None:
    """Second cut of the stereo clip: source frames 100-250 at 59.94 (1.668-4.171 s), on the
    timeline from frame 100. A line half inside keeps only its words inside; a word piece
    shorter than 0.3 s is dropped."""
    words = (Word(1.0, 1.5, "before"), Word(2.0, 2.5, "inside"), Word(2.5, 3.0, "too"))
    lines = {
        "IMG 0870 é.MOV": [
            SpokenLine(1.0, 3.0, "before inside too", words),
            SpokenLine(4.1, 6.0, "barely in"),  # 0.07 s inside the cut: dropped
        ]
    }
    second = Sequence("s", NTSC60, 3840, 2160, cuts=[seq.cuts[1]])
    second.cuts[0] = Cut(seq.cuts[1].source, NTSC60, 100, 150, 0)
    found = subtitles(second, lines)
    assert len(found) == 1
    start, end, text = found[0]
    offset = float(F(100) / NTSC60)
    assert text == "inside too"
    assert (start, end) == pytest.approx((2.0 - offset, 3.0 - offset))
    assert write_srt(second, lines).startswith("1\n00:00:00,332 --> 00:00:01,332\ninside too\n")


def test_a_short_whole_line_is_a_subtitle_but_a_short_clipped_piece_is_not(seq: Sequence) -> None:
    cut = Cut(seq.cuts[0].source, NTSC60, 0, 120, 0)  # source 0 .. 2.002 s
    short = Sequence("s", NTSC60, 3840, 2160, cuts=[cut])
    lines = {
        "IMG 0870 é.MOV": [
            SpokenLine(0.5, 0.7, "Yes.", (Word(0.5, 0.7, "Yes."),)),
            SpokenLine(1.8, 3.0, "no way", (Word(1.8, 1.95, "no"), Word(2.5, 3.0, "way"))),
        ]
    }
    assert [text for _, _, text in subtitles(short, lines)] == ["Yes."]
