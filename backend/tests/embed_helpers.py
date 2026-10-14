"""Stand-ins for the picture and text models in tests (test-only; the app has no such path).

Picture vectors are made from a frame's mean colour, so frames that look alike get similar
vectors; text vectors come from a hash of the text. Neither means anything beyond that.
"""

# numpy's norm is untyped for these arrays.
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from cinemind.ai import embedder, tagger
from cinemind.core.config import Settings
from cinemind.core.embed_config import WEIGHTS, EmbedModel
from cinemind.pipeline import tag_stage


def unit(vector: Any) -> Any:
    vector = np.asarray(vector, dtype=np.float32)
    return vector / max(float(np.linalg.norm(vector)), 1e-12)


def colour_vector(frame: Any, dim: int) -> Any:
    vector = np.full(dim, 0.05, dtype=np.float32)
    vector[:3] = frame.reshape(-1, 3).mean(axis=0) / 255.0
    return unit(vector)


def text_vector(text: str, dim: int) -> Any:
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "little")
    return unit(np.random.default_rng(seed).standard_normal(dim))


def install_embed_models(settings: Settings) -> None:
    for spec in (embedder.choose_visual(settings), embedder.choose_text(settings)):
        folder = spec.path(settings.models_path)
        for name in (WEIGHTS, *spec.files):
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(b"test")


class FakeEmbedder:
    def __init__(self) -> None:
        self.images = 0
        self.texts = 0

    def embed_images(self, spec: EmbedModel, _s: Settings, frames: Sequence[Any]) -> Any:
        self.images += len(frames)
        return np.stack([colour_vector(f, spec.dim) for f in frames])

    def embed_prompts(self, spec: EmbedModel, _s: Settings, prompts: Sequence[str]) -> Any:
        return np.stack([text_vector(p, spec.dim) for p in prompts])

    def logit_scale(self, _spec: EmbedModel, _s: Settings) -> float:
        return 100.0

    def embed_texts(self, spec: EmbedModel, _s: Settings, texts: Sequence[str]) -> Any:
        self.texts += len(texts)
        return np.stack([text_vector(t, spec.dim) for t in texts])


def use_fake_embedder(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> FakeEmbedder:
    fake = FakeEmbedder()
    install_embed_models(settings)
    monkeypatch.setattr(embedder, "embed_images", fake.embed_images)
    monkeypatch.setattr(embedder, "embed_prompts", fake.embed_prompts)
    monkeypatch.setattr(embedder, "embed_texts", fake.embed_texts)
    monkeypatch.setattr(embedder, "logit_scale", fake.logit_scale)
    tag_stage.clear_vocabulary()
    return fake


def write_thresholds(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp: Path, tags: dict[str, Any]
) -> Path:
    """A thresholds file for the visual model in use, holding only `tags`."""
    spec = embedder.choose_visual(settings)
    path = tmp / "tag_thresholds.json"
    entry = {"date": "2026-10-14", "source": "test", "tags": tags}
    path.write_text(json.dumps({"models": {tagger.calibration_key(spec): entry}}))
    monkeypatch.setattr(tagger, "THRESHOLDS_FILE", path)
    return path
