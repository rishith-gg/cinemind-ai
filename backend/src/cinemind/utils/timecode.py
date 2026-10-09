"""Frame rates and timecode with exact integer/rational arithmetic (never float fps)."""

import re
from fractions import Fraction

from cinemind.core.errors import InvalidInputError

# Rates an NLE timeline can be set to. Sources are snapped to the nearest one for export.
STANDARD_RATES = (
    Fraction(24000, 1001),
    Fraction(24),
    Fraction(25),
    Fraction(30000, 1001),
    Fraction(30),
    Fraction(48),
    Fraction(50),
    Fraction(60000, 1001),
    Fraction(60),
    Fraction(100),
    Fraction(120000, 1001),
    Fraction(120),
)
_SNAP_TOLERANCE = Fraction(1, 100)
_TC = re.compile(r"^(\d{1,2})[:.](\d{2})[:.](\d{2})([:;.])(\d{2,3})$")


def snap_rate(fps: Fraction) -> Fraction:
    """Nearest standard rate if within 1 % (a variable-rate phone clip averaging 59.96 fps is
    a 59.94 clip to an editor); otherwise the nearest whole rate."""
    nearest = min(STANDARD_RATES, key=lambda rate: abs(rate - fps))
    if abs(nearest - fps) <= nearest * _SNAP_TOLERANCE:
        return nearest
    return Fraction(max(1, round(fps)))


def timebase(rate: Fraction) -> tuple[int, bool]:
    """(integer timebase, NTSC flag) as FCP7 XML and timecode use them: 30000/1001 -> (30, True)."""
    return round(rate), rate.denominator == 1001


def rate_label(rate: Fraction) -> str:
    return str(rate.numerator) if rate.denominator == 1 else f"{float(rate):.3f}".rstrip("0")


def seconds_to_frames(seconds: float, rate: Fraction) -> int:
    return round(seconds * rate.numerator / rate.denominator)


def rescale(frames: int, src: Fraction, dst: Fraction) -> int:
    """The same instant counted in another rate's frames (nearest frame)."""
    return frames if src == dst else round(Fraction(frames) * dst / src)


def can_drop(rate: Fraction) -> bool:
    return rate in (Fraction(30000, 1001), Fraction(60000, 1001))


def frames_to_tc(frames: int, rate: Fraction, drop: bool = False) -> str:
    base, _ = timebase(rate)
    drop = drop and can_drop(rate)
    if drop:
        skipped = 2 * base // 30  # frame numbers skipped each minute, except every tenth
        per_ten = base * 600 - 9 * skipped
        per_minute = base * 60 - skipped
        tens, rem = divmod(frames, per_ten)
        frames += 9 * skipped * tens
        if rem > skipped:
            frames += skipped * ((rem - skipped) // per_minute)
    seconds, ff = divmod(frames, base)
    minutes, ss = divmod(seconds, 60)
    hh, mm = divmod(minutes, 60)
    width = 3 if base > 100 else 2
    return f"{hh:02d}:{mm:02d}:{ss:02d}{';' if drop else ':'}{ff:0{width}d}"


def tc_to_frames(text: str, rate: Fraction) -> int:
    """Frame count for a timecode string; ';' before the frames means drop-frame."""
    match = _TC.match(text.strip())
    if match is None:
        raise InvalidInputError(f"'{text}' is not a valid timecode.")
    hh, mm, ss, sep, ff = match.groups()
    base, _ = timebase(rate)
    minutes = int(hh) * 60 + int(mm)
    frames = (minutes * 60 + int(ss)) * base + int(ff)
    if sep == ";" and can_drop(rate):
        frames -= (2 * base // 30) * (minutes - minutes // 10)
    return frames


def is_drop(text: str | None) -> bool:
    return bool(text) and ";" in str(text)
