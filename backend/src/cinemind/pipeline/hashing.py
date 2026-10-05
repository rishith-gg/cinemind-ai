"""Fast content hash: xxh3-128 over file size, first/last MiB and evenly spaced samples."""

from pathlib import Path

import xxhash

_CHUNK = 1024 * 1024
_SAMPLE = 64 * 1024
_SAMPLES = 16


def content_hash(path: Path) -> str:
    """Identify a file without reading all of it. Not cryptographic; used for caching/dedup/relink.
    Edits that keep the size and leave the head, tail and sampled blocks untouched are not
    detected (accepted trade-off, see D-025)."""
    size = path.stat().st_size
    digest = xxhash.xxh3_128()
    digest.update(str(size).encode())
    with path.open("rb") as f:
        digest.update(f.read(_CHUNK))
        if size > 2 * _CHUNK:
            span = size - 2 * _CHUNK
            for i in range(1, _SAMPLES + 1):
                f.seek(_CHUNK + span * i // (_SAMPLES + 1))
                digest.update(f.read(_SAMPLE))
            f.seek(size - _CHUNK)
            digest.update(f.read(_CHUNK))
    return digest.hexdigest()
