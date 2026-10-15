"""Frame-exact description of a timeline for export, and its OpenTimelineIO form.

A stored timeline keeps source ranges in seconds. Here they become whole frames on the
timeline's rate (exact rational arithmetic), which every exporter then shares. Each cut points
at the ORIGINAL file, never the proxy.

Sources whose rate differs from the timeline are carried with in/out counted in timeline-rate
frames of source time; an NLE conforms them, so those cuts are accurate to within one frame and
are listed in `warnings`.
"""

from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from cinemind.core.errors import InvalidInputError
from cinemind.db.models import MediaAsset, Timeline
from cinemind.utils.timecode import (
    can_drop,
    is_drop,
    rate_label,
    rescale,
    seconds_to_frames,
    snap_rate,
    tc_to_frames,
)

START_TC_SECONDS = 3600  # timelines start at 01:00:00:00, the editorial convention


@dataclass(frozen=True)
class Source:
    media_id: str
    name: str
    path: str
    url: str
    rate: Fraction
    frames: int  # length in source-rate frames
    tc_start: int  # start timecode as source-rate frames
    drop: bool
    width: int
    height: int
    channels: int  # 0 = no audio
    sample_rate: int


@dataclass(frozen=True)
class Cut:
    source: Source
    rate: Fraction  # the timeline rate the three numbers below are counted in
    src_in: int  # frames from the first frame of the file
    duration: int
    record: int  # frames from the start of the timeline
    shot_id: str | None = None
    note: str | None = None  # why a rough cut chose this clip; written as a marker
    item_id: str | None = None  # the stored timeline item this cut was made from

    @property
    def src_in_s(self) -> Fraction:
        """Source in-point in seconds from the first frame of the file."""
        return self.src_in / self.rate

    @property
    def mixed_rate(self) -> bool:
        return self.source.rate != self.rate


@dataclass
class Sequence:
    name: str
    rate: Fraction
    width: int
    height: int
    kind: str = "all_shots"
    banner: str | None = None  # "AI-assisted rough cut. Human review required." on rough cuts
    cuts: list[Cut] = field(default_factory=lambda: [])
    warnings: list[str] = field(default_factory=lambda: [])

    @property
    def start_frame(self) -> int:
        return round(START_TC_SECONDS * round(self.rate))

    @property
    def duration(self) -> int:
        return sum(c.duration for c in self.cuts)


def export_rate(asset: MediaAsset) -> Fraction:
    """The rate an editor would call this clip, as a standard rate. A variable-rate clip
    averages a little under its base rate (119.4 for a 120 fps phone clip), so the base rate is
    used while it agrees with the average within 5 %; a base rate further off is not trusted."""
    if not asset.fps_num or not asset.fps_den:
        return Fraction(25)
    average = Fraction(asset.fps_num, asset.fps_den)
    if asset.nominal_fps_num and asset.nominal_fps_den:
        nominal = Fraction(asset.nominal_fps_num, asset.nominal_fps_den)
        if abs(nominal - average) <= average / 20:
            return snap_rate(nominal)
    return snap_rate(average)


def _source(asset: MediaAsset, warnings: list[str]) -> Source:
    rate = export_rate(asset)
    tc_start = 0
    if asset.start_timecode:
        try:
            tc_start = tc_to_frames(asset.start_timecode, rate)
        except InvalidInputError:
            warnings.append(f"{asset.filename}: unreadable start timecode, 00:00:00:00 assumed.")
    # A variable-rate file holds fewer frames than duration x base rate; count at its average
    # rate so an out point never lies past the end of the media.
    counted = rate
    if asset.is_vfr and asset.fps_num and asset.fps_den:
        counted = min(rate, Fraction(asset.fps_num, asset.fps_den))
    path = Path(asset.path)
    return Source(
        media_id=asset.id,
        name=asset.filename,
        path=asset.path,
        url=path.as_uri() if path.is_absolute() else asset.path,
        rate=rate,
        frames=max(1, seconds_to_frames(asset.duration_s or 0.0, counted)),
        tc_start=tc_start,
        drop=is_drop(asset.start_timecode) and can_drop(rate),
        width=asset.width or 0,
        height=asset.height or 0,
        channels=min(2, asset.audio_channels or 0) if asset.audio_codec else 0,
        sample_rate=asset.audio_sample_rate or 48000,
    )


def _some(names: list[str]) -> str:
    return ", ".join(names[:5]) + ("…" if len(names) > 5 else "")


def build_sequence(timeline: Timeline, assets: dict[str, MediaAsset]) -> Sequence:
    rate = Fraction(timeline.fps_num, timeline.fps_den)
    seq = Sequence(timeline.name, rate, timeline.width, timeline.height, timeline.kind)
    seq.banner = timeline.params.get("banner")
    sources: dict[str, Source] = {}
    record = 0
    past_end = 0
    variable: list[str] = []
    for item in timeline.items:
        asset = assets.get(item.media_id)
        if asset is None:
            continue
        if asset.id not in sources:
            sources[asset.id] = _source(asset, seq.warnings)
            if asset.is_vfr:
                variable.append(asset.filename)
            if not Path(asset.path).is_file():
                seq.warnings.append(
                    f"{asset.filename}: the original file is missing; relink it in your editor."
                )
        source = sources[asset.id]
        total = rescale(source.frames, source.rate, rate)
        src_in = max(0, seconds_to_frames(item.source_in_s, rate))
        if src_in >= total:  # the range starts after the last frame of the file
            past_end += 1
            continue
        src_out = min(seconds_to_frames(item.source_out_s, rate), total)
        duration = max(1, src_out - src_in)
        note = (item.reason or {}).get("summary")
        seq.cuts.append(Cut(source, rate, src_in, duration, record, item.shot_id, note, item.id))
        record += duration
    built = int(timeline.params.get("built_items", 0))
    removed = built - len(timeline.items)
    if removed > 0:
        seq.warnings.append(
            f"{removed} of the {built} cuts this timeline was built with are gone because their "
            "clips were removed from the project. Build a new timeline to match the library."
        )
    if past_end:
        seq.warnings.append(
            f"{past_end} cut(s) start after the end of their file and were left out."
        )
    if variable:
        seq.warnings.append(
            f"{len(variable)} clip(s) have a variable frame rate ({_some(variable)}). Their cuts "
            "are placed by time and can be a few frames off in the editor; transcode them to a "
            "constant frame rate for frame accuracy."
        )
    mixed = sorted({c.source.name for c in seq.cuts if c.mixed_rate})
    if mixed:
        seq.warnings.append(
            f"{len(mixed)} clip(s) do not match the timeline rate of {rate_label(rate)} fps "
            f"({_some(mixed)}). Their cuts are converted "
            "and can be off by up to one frame; EDL cannot describe mixed rates reliably."
        )
    return seq


def source_start(cut: Cut) -> int:
    """Source in-point including the file's start timecode, in timeline-rate frames."""
    return rescale(cut.source.tc_start, cut.source.rate, cut.rate) + cut.src_in
