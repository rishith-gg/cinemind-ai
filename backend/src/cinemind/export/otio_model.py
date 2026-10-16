"""The timeline as OpenTimelineIO, the project's interchange model (and the `.otio` export)."""
# opentimelineio ships no type stubs; the checks below are relaxed for this module only.
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from typing import Any

import opentimelineio as otio
from opentimelineio.opentime import RationalTime, TimeRange

from cinemind.export.sequence import Sequence, source_start
from cinemind.rough_cut import BANNER

# What the timeline is, stated in the file: nothing here was chosen by a model.
NOTES = {
    "all_shots": "Every detected shot in file order; nothing selected or ranked.",
    "rough_cut": f"{BANNER} Clips were chosen from a brief by search and ranking; each clip's "
    "marker says why.",
    "script_cut": f"{BANNER} Each script line's take in script order, found by matching the "
    "script with the transcripts; each clip's marker says which line.",
}


def to_otio(seq: Sequence) -> Any:
    """The timeline as OpenTimelineIO: one video track and one audio track, cuts only."""
    rate = float(seq.rate)
    timeline = otio.schema.Timeline(name=seq.name)
    timeline.global_start_time = RationalTime(seq.start_frame, rate)
    timeline.metadata["cinemind"] = {
        "rate": f"{seq.rate.numerator}/{seq.rate.denominator}",
        "width": seq.width,
        "height": seq.height,
        "kind": seq.kind,
        "note": f"{NOTES.get(seq.kind, seq.kind)} Source ranges are in timeline-rate frames.",
        "banner": seq.banner,
    }
    video = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    audio = otio.schema.Track(name="A1", kind=otio.schema.TrackKind.Audio)
    for cut in seq.cuts:
        src = cut.source
        src_range = TimeRange(
            RationalTime(source_start(cut), rate), RationalTime(cut.duration, rate)
        )
        for track in (video, audio):
            if track is audio and not src.channels:
                track.append(otio.schema.Gap(source_range=TimeRange(duration=src_range.duration)))
                continue
            reference = otio.schema.ExternalReference(
                target_url=src.url,
                available_range=TimeRange(
                    RationalTime(src.tc_start, float(src.rate)),
                    RationalTime(src.frames, float(src.rate)),
                ),
            )
            clip = otio.schema.Clip(name=src.name, media_reference=reference)
            clip.source_range = src_range
            if cut.note and track is video:
                clip.markers.append(
                    otio.schema.Marker(
                        name="Why this clip",
                        marked_range=TimeRange(src_range.start_time, RationalTime(0, rate)),
                        comment=cut.note,
                    )
                )
            clip.metadata["cinemind"] = {
                "media_id": src.media_id,
                "shot_id": cut.shot_id,
                "source_rate": f"{src.rate.numerator}/{src.rate.denominator}",
            }
            track.append(clip)
    timeline.tracks.append(video)
    timeline.tracks.append(audio)
    return timeline


def write_otio(seq: Sequence) -> str:
    return str(otio.adapters.write_to_string(to_otio(seq), "otio_json"))
