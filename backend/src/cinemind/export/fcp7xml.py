"""Final Cut Pro 7 XML (xmeml) writer: the main hand-off format for DaVinci Resolve.

Our own writer rather than the OTIO `fcp_xml` adapter, whose output has empty audio clip items
and unescaped file URLs (DECISIONS D-036). That adapter is used as an independent reader in the
round-trip tests instead. One video track and one audio track, cuts only, video and audio of a cut
linked. A cut gets ONE audio clip item whatever its channel count: DaVinci Resolve 21 reads each
audio clip item as the file's whole (stereo) audio, so one item per channel doubled the sound
(manual import test, 2026-10-09). In/out are media-relative frames on the sequence timebase.
"""

from fractions import Fraction
from xml.etree import ElementTree as ET

from cinemind.export.sequence import Cut, Sequence, Source
from cinemind.utils.timecode import frames_to_tc, rescale, timebase

_HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'


def _text(parent: ET.Element, tag: str, value: object) -> ET.Element:
    node = ET.SubElement(parent, tag)
    node.text = str(value)
    return node


def _rate(parent: ET.Element, rate: Fraction) -> None:
    base, ntsc = timebase(rate)
    node = ET.SubElement(parent, "rate")
    _text(node, "timebase", base)
    _text(node, "ntsc", "TRUE" if ntsc else "FALSE")


def _timecode(parent: ET.Element, rate: Fraction, frame: int, drop: bool) -> None:
    node = ET.SubElement(parent, "timecode")
    _rate(node, rate)
    _text(node, "string", frames_to_tc(frame, rate, drop))
    _text(node, "frame", frame)
    _text(node, "displayformat", "DF" if drop else "NDF")


def _file(parent: ET.Element, src: Source, file_id: str, define: bool) -> None:
    node = ET.SubElement(parent, "file", id=file_id)
    if not define:  # later uses only reference the first definition
        return
    _text(node, "name", src.name)
    _text(node, "pathurl", src.url)
    _rate(node, src.rate)
    _text(node, "duration", src.frames)
    _timecode(node, src.rate, src.tc_start, src.drop)
    media = ET.SubElement(node, "media")
    chars = ET.SubElement(ET.SubElement(media, "video"), "samplecharacteristics")
    _text(chars, "width", src.width)
    _text(chars, "height", src.height)
    if src.channels:
        audio = ET.SubElement(media, "audio")
        chars = ET.SubElement(audio, "samplecharacteristics")
        _text(chars, "depth", 16)
        _text(chars, "samplerate", src.sample_rate)
        _text(audio, "channelcount", src.channels)


def write_fcp7xml(seq: Sequence) -> str:
    root = ET.Element("xmeml", version="5")
    sequence = ET.SubElement(root, "sequence", id="sequence-1")
    _text(sequence, "name", seq.name)
    _text(sequence, "duration", seq.duration)
    _rate(sequence, seq.rate)
    _timecode(sequence, seq.rate, seq.start_frame, drop=False)
    media = ET.SubElement(sequence, "media")

    video = ET.SubElement(media, "video")
    chars = ET.SubElement(ET.SubElement(video, "format"), "samplecharacteristics")
    _text(chars, "width", seq.width)
    _text(chars, "height", seq.height)
    _text(chars, "pixelaspectratio", "square")
    _rate(chars, seq.rate)
    audio = ET.SubElement(media, "audio")
    channels = max((c.source.channels for c in seq.cuts), default=0)
    _text(audio, "numOutputChannels", max(1, channels))
    audio_tracks = 1 if channels else 0
    chars = ET.SubElement(ET.SubElement(audio, "format"), "samplecharacteristics")
    _text(chars, "depth", 16)
    _text(chars, "samplerate", 48000)

    # Track 0 is video, track 1 is audio. A cut sits on the audio track if its source has sound;
    # `members` remembers (track, index in track, clip id) to link picture and sound together.
    tracks = [ET.SubElement(video, "track")] + [
        ET.SubElement(audio, "track") for _ in range(audio_tracks)
    ]
    counts = [0] * len(tracks)
    file_ids: dict[str, str] = {}
    for number, cut in enumerate(seq.cuts, start=1):
        members: list[tuple[int, int, str]] = []
        for track in range(2 if cut.source.channels else 1):
            counts[track] += 1
            kind = "v" if track == 0 else "a"
            members.append((track, counts[track], f"clipitem-{number}-{kind}"))
        for track, _, clip_id in members:
            _clipitem(tracks[track], cut, track, clip_id, members, file_ids)
    ET.indent(root, space="  ")
    return _HEADER + ET.tostring(root, encoding="unicode") + "\n"


def _clipitem(
    parent: ET.Element,
    cut: Cut,
    track: int,
    clip_id: str,
    members: list[tuple[int, int, str]],
    file_ids: dict[str, str],
) -> None:
    src = cut.source
    item = ET.SubElement(parent, "clipitem", id=clip_id)
    _text(item, "name", src.name)
    _text(item, "enabled", "TRUE")
    _text(item, "duration", rescale(src.frames, src.rate, cut.rate))
    _rate(item, cut.rate)
    _text(item, "start", cut.record)
    _text(item, "end", cut.record + cut.duration)
    _text(item, "in", cut.src_in)
    _text(item, "out", cut.src_in + cut.duration)
    define = src.media_id not in file_ids
    file_id = file_ids.setdefault(src.media_id, f"file-{len(file_ids) + 1}")
    _file(item, src, file_id, define)
    source_track = ET.SubElement(item, "sourcetrack")
    _text(source_track, "mediatype", "video" if track == 0 else "audio")
    _text(source_track, "trackindex", max(1, track))
    if len(members) > 1:
        for member_track, clip_index, member_id in members:
            link = ET.SubElement(item, "link")
            _text(link, "linkclipref", member_id)
            _text(link, "mediatype", "video" if member_track == 0 else "audio")
            _text(link, "trackindex", max(1, member_track))
            _text(link, "clipindex", clip_index)
            if member_track > 0:
                _text(link, "groupindex", 1)
