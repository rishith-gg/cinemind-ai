"""Format and pixel size of an uploaded picture, read from its header without decoding it, so a
small file that declares a huge image is refused before any memory is spent on it."""

import struct

# JPEG start-of-frame markers (baseline, progressive, lossless ...): they carry the size.
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg(data: bytes) -> tuple[int, int] | None:
    i = 2
    while i + 9 <= len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # no length field
            i += 2
            continue
        (length,) = struct.unpack(">H", data[i + 2 : i + 4])
        if marker in _SOF:
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        i += 2 + length
    return None


def _webp(data: bytes) -> tuple[int, int] | None:
    chunk = data[12:16]
    if chunk == b"VP8 " and len(data) >= 30:
        width, height = struct.unpack("<HH", data[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L" and len(data) >= 25:
        b = data[21:25]
        width = 1 + (b[0] | (b[1] & 0x3F) << 8)
        height = 1 + (b[1] >> 6 | b[2] << 2 | (b[3] & 0x0F) << 10)
        return width, height
    if chunk == b"VP8X" and len(data) >= 30:
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    return None


def picture_size(data: bytes) -> tuple[str, int, int] | None:
    """("jpeg" | "png" | "webp", width, height), or None for anything else or a broken header."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24 and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        return "png", width, height
    if data[:3] == b"\xff\xd8\xff":
        size = _jpeg(data)
        return ("jpeg", *size) if size else None
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        size = _webp(data)
        return ("webp", *size) if size else None
    return None
