"""Stand-ins and small helpers shared by the face and actor tests."""

# numpy's norm is untyped for these arrays.
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from pathlib import Path
from typing import Any

import numpy as np
from fastapi.testclient import TestClient

from cinemind.ai.faces import Found
from cinemind.core import face_config
from cinemind.core.config import Settings
from cinemind.core.face_config import FaceConfig
from helpers import drain, import_one


def person(number: int, wobble: float = 0.0) -> Any:
    """A unit vector for made-up person `number`; `wobble` moves it a little, as another
    appearance of the same person would."""
    vector = np.zeros(face_config.EMBEDDING_DIM, dtype=np.float32)
    vector[number] = 1.0
    vector[100 + number] = wobble
    return vector / np.linalg.norm(vector)


class FakeFaces:
    """Stands in for the face models in tests (test-only; the app has no such code path).
    Every frame shows `people`: (left edge as a fraction of the width, vector)."""

    def __init__(self, people: list[tuple[float, Any]]) -> None:
        self.people = people
        self.frames = 0

    def find(self, image: Any, cfg: FaceConfig) -> list[Found]:
        self.frames += 1
        height, width = image.shape[:2]
        assert cfg.min_score == 0.8
        found = [
            Found((left * width, 0.2 * height, 60.0, 60.0), 0.95, 60.0, 0.1, 80.0, None, vector)
            for left, vector in self.people
        ]
        return [*found, Found((0.0, 0.0, 12.0, 12.0), 0.65, 12.0, 0.1, None, "low_score")]


def engine_factory(stand_in: "FakeFaces") -> Any:
    def create(_models_root: Path) -> FakeFaces:
        return stand_in

    return create


def install_models(settings: Settings) -> None:
    for spec in face_config.FACE_MODELS:
        target = spec.path(settings.models_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"test")


def import_clip(client: TestClient, pid: str, path: Path) -> str:
    media: Any = import_one(client, pid, path)["media"]
    return str(media["id"])


def faces_of(client: TestClient, media_id: str) -> dict[str, Any]:
    res = client.get(f"/api/media/{media_id}/faces")
    assert res.status_code == 200, res.text
    return res.json()


def actors_of(client: TestClient, pid: str) -> dict[str, Any]:
    res = client.get(f"/api/projects/{pid}/actors")
    assert res.status_code == 200, res.text
    return res.json()


def detail_of(client: TestClient, actor_id: str) -> dict[str, Any]:
    res = client.get(f"/api/actors/{actor_id}")
    assert res.status_code == 200, res.text
    return res.json()


def two_clips(client: TestClient, pid: str, settings: Settings, footage: Path) -> tuple[str, str]:
    """Two clips, each showing made-up persons 0 and 1 side by side."""
    first = import_clip(client, pid, footage / "a_h264.mp4")
    second = import_clip(client, pid, footage / "c_ntsc_noaudio.mkv")
    drain(settings)
    return first, second
