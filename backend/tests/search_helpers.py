"""Shared by the search and ranking tests: a processed `cuts.mp4` project and a search call."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cinemind.ai import transcriber
from cinemind.core.config import Settings
from cinemind.core.search_config import SearchConfig
from cinemind.core.transcribe_config import MODEL_FILES
from embed_helpers import use_fake_embedder, write_thresholds
from helpers import drain, import_one

TAGS = {"forest": {"threshold": 0.0, "enabled": True, "precision": 0.93, "dataset": "places365"}}


def _seg(start: float, end: float, text: str, logprob: float = -0.2) -> dict[str, Any]:
    words = text.split()
    step = (end - start) / len(words)
    return {
        "start": start,
        "end": end,
        "text": text,
        "avg_logprob": logprob,
        "no_speech_prob": 0.1,
        "compression_ratio": 1.2,
        "words": [[start + i * step, start + (i + 1) * step, w, 0.9] for i, w in enumerate(words)],
    }


def _speech(*_args: Any) -> dict[str, Any]:
    return {
        "language": "en",
        "language_probability": 0.9,
        "speech_s": 3.0,
        "segments": [
            _seg(0.2, 1.8, "walking into the forest now"),
            _seg(6.2, 7.6, "the forest at night", logprob=-1.6),  # uncertain: never a hit
        ],
    }


def processed_cuts(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    cut_footage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """cuts.mp4 (four shots: test pattern, colour bars, fractal, dark blue), processed with the
    stand-in models and a transcript that mentions a forest in the first shot."""
    write_thresholds(monkeypatch, api_settings, tmp_path, TAGS)
    fake = use_fake_embedder(monkeypatch, api_settings)
    folder = transcriber.choose_model(api_settings).path
    folder.mkdir(parents=True)
    for name in MODEL_FILES:
        (folder / name).write_bytes(b"test")
    monkeypatch.setattr(transcriber, "transcribe", _speech)
    api_settings.media_roots.append(cut_footage)
    # The stand-in text vectors are hashes: unrelated to each other, so no floor here.
    api_settings.search = SearchConfig(text_min_similarity=-1.0)
    media: Any = import_one(client, pid, cut_footage / "cuts.mp4")["media"]
    drain(api_settings)
    shots = client.get(f"/api/media/{media['id']}/shots").json()
    assert len(shots) == 4
    return {"media": media["id"], "shots": [s["id"] for s in shots], "fake": fake}


def search(client: TestClient, pid: str, **body: Any) -> Any:
    res = client.post(f"/api/projects/{pid}/search", json=body)
    assert res.status_code == 200, res.text
    return res.json()
