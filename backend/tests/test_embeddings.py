"""Embedding stages, tag scoring and thresholds, and the vector index (Phase 8)."""

# numpy is only partly typed.
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from cinemind.ai import embedder, tagger, transcriber
from cinemind.ai.embedder import VisualModel
from cinemind.core.config import Settings
from cinemind.core.embed_config import EmbedConfig, SceneConfig
from cinemind.core.transcribe_config import MODEL_FILES
from cinemind.db.analysis import Embedding, EmbeddingSet, Tag, VectorIndexRow
from cinemind.db.base import make_engine, make_session_factory
from cinemind.db.models import Keyframe, MediaAsset, Shot
from cinemind.search import vector_index
from embed_helpers import FakeEmbedder, unit, use_fake_embedder, write_thresholds
from helpers import drain, import_one

THRESHOLDS = {
    "forest": {"threshold": 0.0, "enabled": True, "precision": 0.93, "dataset": "places365"},
    "outdoor": {"threshold": 1.01, "enabled": True, "precision": 0.95, "dataset": "places365"},
    "day": {"threshold": 0.7, "enabled": False, "reason": "held-out precision 0.61 < 0.85"},
}


def _session(settings: Settings) -> Any:
    return make_session_factory(make_engine(settings.db_path))()


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, api_settings: Settings, tmp_path: Path) -> FakeEmbedder:
    write_thresholds(monkeypatch, api_settings, tmp_path, THRESHOLDS)
    return use_fake_embedder(monkeypatch, api_settings)


def _ingest(client: TestClient, pid: str, path: Path, settings: Settings) -> str:
    media: Any = import_one(client, pid, path)["media"]
    drain(settings)
    return str(media["id"])


# --- units --------------------------------------------------------------------------------------


def test_settings_reject_unknown_models() -> None:
    with pytest.raises(ValueError, match="visual_model"):
        EmbedConfig(visual_model="resnet")
    with pytest.raises(ValueError, match="join_similarity"):
        SceneConfig(join_similarity=1.5)


def test_scores_are_shares_inside_each_group() -> None:
    rng = np.random.default_rng(1)
    images = np.stack([unit(rng.standard_normal(32)) for _ in range(5)])
    prompts = np.stack([unit(rng.standard_normal(32)) for _ in tagger.prompts()])
    tag_v, cat_v = tagger.class_vectors(prompts)
    assert len(tagger.places()) == 365 and cat_v.shape == (365, 32)
    scores, cat_probs = tagger.score(images, tag_v, cat_v, 100.0)
    assert np.allclose(scores["indoor"] + scores["outdoor"], 1)
    assert np.allclose(scores["close_up"] + scores["medium"] + scores["wide"], 1)
    assert np.allclose(cat_probs.sum(axis=1), 1)
    places = sum(scores[t.name] for t in tagger.PLACE_TAGS)
    assert np.all(places <= 1 + 1e-6)  # the other 300-odd categories take the rest
    assert len(tagger.top_places(cat_probs[0])) == 3


def test_category_names_read_as_words() -> None:
    assert tagger.category_text("/s/swimming_pool/indoor") == "indoor swimming pool"
    assert tagger.category_text("/f/forest_path") == "forest path"
    every = {c for tag in tagger.PLACE_TAGS for c in tag.texts}
    assert every <= {name for name, _ in tagger.places()}  # no typo in the vocabulary


def test_a_tag_is_shown_only_above_an_evaluated_threshold() -> None:
    calibration = {"tags": THRESHOLDS}
    assert tagger.decide("forest", [0.2], calibration) == ("shown", 0.0)
    assert tagger.decide("outdoor", [0.99], calibration) == ("below", 1.01)
    assert tagger.decide("day", [0.99], calibration) == ("disabled", 0.7)
    assert tagger.decide("wide", [0.99], calibration) == ("not_evaluated", None)
    assert tagger.decide("forest", [0.99], None) == ("not_evaluated", None)


def test_both_tags_of_a_two_way_group_are_never_shown_together() -> None:
    calibration = {
        "tags": {
            "day": {"threshold": 0.41, "enabled": True},
            "night": {"threshold": 0.41, "enabled": True},
        }
    }
    assert tagger.threshold_floor("day") == 0.5 and tagger.threshold_floor("forest") == 0.0
    day, night = 0.55, 0.45  # shares of one picture add up to 1
    assert tagger.decide("day", [day], calibration) == ("shown", 0.5)
    assert tagger.decide("night", [night], calibration)[0] == "below"
    # two keyframes, one each way: only the tag with the higher mean is shown
    assert tagger.decide("day", [0.6, 0.45], calibration)[0] == "shown"
    assert tagger.decide("night", [0.4, 0.55], calibration)[0] == "below"


def test_the_evaluated_rule_is_applied_per_keyframe_not_to_the_mean() -> None:
    calibration = {"tags": {"beach": {"threshold": 0.6, "enabled": True}}}
    # mean 0.675 would pass; one keyframe of three passing is not enough
    assert tagger.decide("beach", [0.95, 0.4, 0.3], calibration)[0] == "below"
    assert tagger.decide("beach", [0.95, 0.4], calibration)[0] == "shown"  # tie: mean 0.675 passes
    assert tagger.decide("beach", [0.65, 0.2], calibration)[0] == "below"  # tie: mean 0.425 fails
    assert tagger.decide("beach", [0.61, 0.62, 0.1], calibration)[0] == "shown"


def _visual_model(prep: dict[str, Any]) -> VisualModel:
    model = object.__new__(VisualModel)
    model.prep = prep
    return model


def test_image_preparation_follows_each_models_settings() -> None:
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame[:, :, 2] = 255  # pure red in BGR
    clip = _visual_model(
        {
            "size": 224,
            "do_center_crop": True,
            "crop_size": 224,
            "image_mean": [0.5, 0.5, 0.5],
            "image_std": [0.5, 0.5, 0.5],
        }
    )
    out = clip.prepare(frame)
    assert out.shape == (3, 224, 224)  # shortest side to 224, then the centre square
    assert np.allclose(out[0], 1.0) and np.allclose(out[2], -1.0)  # RGB order, normalised
    siglip = _visual_model(
        {
            "size": {"height": 224, "width": 224},
            "rescale_factor": 1 / 255,
            "image_mean": [0.5, 0.5, 0.5],
            "image_std": [0.5, 0.5, 0.5],
        }
    )
    assert siglip.prepare(frame).shape == (3, 224, 224)  # squeezed, not cropped


def test_colour_histogram_sums_to_one_and_matches_itself() -> None:
    rng = np.random.default_rng(2)
    frame = rng.integers(0, 255, (90, 160, 3), dtype=np.uint8)
    hist = embedder.color_histogram(frame)
    assert hist.shape == (int(np.prod(embedder.HIST_BINS)),)
    assert np.isclose(hist.sum(), 1) and np.isclose(np.minimum(hist, hist).sum(), 1)
    black = embedder.color_histogram(np.zeros_like(frame))
    assert np.minimum(hist, black).sum() < 0.2


_FAISS_CHECK = """
import json, sys
import numpy as np
from cinemind.search import vector_index
rng = np.random.default_rng(3)
vectors = rng.standard_normal((40, 16)).astype(np.float32)
vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
out = {}
for backend in ("numpy", "faiss"):
    index = vector_index.new_index(16, backend)
    index.add(vectors)
    scores, positions = index.search(vectors[:2] + 0.01, 5)
    out[backend] = [scores.tolist(), positions.tolist()]
print(json.dumps(out))
"""


def test_numpy_and_faiss_indexes_agree() -> None:
    # Own process without torch: on macOS torch and faiss bundle clashing OpenMP runtimes (D-079).
    if not vector_index.faiss_available():
        pytest.skip("faiss is not installed")
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _FAISS_CHECK],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    out = json.loads(done.stdout)
    assert out["numpy"][1] == out["faiss"][1] and out["numpy"][1][0][0] == 0
    assert np.allclose(out["numpy"][0], out["faiss"][0], atol=1e-5)
    small = vector_index.new_index(16, "numpy")
    small.add(np.eye(16, dtype=np.float32)[:2])
    _, positions = small.search(np.eye(16, dtype=np.float32)[:1], 5)
    assert list(positions[0][2:]) == [-1, -1, -1]


def test_index_backend_is_numpy_on_macos_unless_asked() -> None:
    expected = (
        "numpy" if sys.platform == "darwin" or not vector_index.faiss_available() else "faiss"
    )
    assert vector_index.choose_backend("auto") == expected
    assert vector_index.choose_backend("numpy") == "numpy"


# --- the stages, with the stand-in models -------------------------------------------------------


def test_keyframes_get_vectors_and_tags_follow_the_thresholds(
    client: TestClient, pid: str, footage: Path, api_settings: Settings, fake: FakeEmbedder
) -> None:
    media = _ingest(client, pid, footage / "a_h264.mp4", api_settings)
    with _session(api_settings) as s:
        state = s.get(EmbeddingSet, (media, "visual"))
        keyframes = list(s.scalars(select(Keyframe).where(Keyframe.media_id == media)))
        assert state is not None and state.status == "done" and state.count == len(keyframes)
        rows = list(s.scalars(select(Embedding).where(Embedding.media_id == media)))
        assert {r.kind for r in rows} == {"keyframe", "color"}
        assert {r.ref_id for r in rows if r.kind == "keyframe"} == {k.id for k in keyframes}
        vector = np.frombuffer(rows[0].vector, dtype=np.float32)
        assert len(vector) == rows[0].dim and fake.images == len(keyframes)
        tags = {t.name: t for t in s.scalars(select(Tag).where(Tag.media_id == media))}
        assert tags["forest"].status == "shown" and tags["forest"].threshold == 0.0
        assert tags["outdoor"].status == "below"
        assert tags["day"].status == "disabled"
        assert tags["wide"].status == "not_evaluated" and tags["beach"].threshold is None
        assert tags["forest"].details["evaluation"]["precision"] == 0.93
        assert tags["forest"].details["model"] == embedder.choose_visual(api_settings).key
        assert "top_places" in tags["beach"].details
    res = client.get(f"/api/media/{media}/tags").json()
    assert res["status"] == "done" and res["calibrated"] == "2026-10-14"
    shown = {t["name"] for shot in res["shots"] for t in shot["tags"] if t["visible"]}
    assert shown == {"forest"}  # everything else is below, disabled or not evaluated


def test_reprocessing_reuses_vectors_and_new_thresholds_apply_without_a_model_run(
    client: TestClient,
    pid: str,
    footage: Path,
    api_settings: Settings,
    fake: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    media = _ingest(client, pid, footage / "a_h264.mp4", api_settings)
    seen = fake.images
    with _session(api_settings) as s:
        before = sorted(
            r.id for r in s.scalars(select(Embedding).where(Embedding.media_id == media))
        )
    write_thresholds(
        monkeypatch, api_settings, tmp_path, {"beach": {"threshold": 0.0, "enabled": True}}
    )
    client.post(f"/api/media/{media}/process")
    drain(api_settings)
    assert fake.images == seen  # cached: no picture went through the model again
    with _session(api_settings) as s:
        after = sorted(
            r.id for r in s.scalars(select(Embedding).where(Embedding.media_id == media))
        )
        assert after == before  # unchanged result: the rows (and their ids) stay
        tags = {t.name: t.status for t in s.scalars(select(Tag).where(Tag.media_id == media))}
        assert tags["beach"] == "shown" and tags["forest"] == "not_evaluated"


def test_without_models_clips_are_still_processed_and_say_so(
    client: TestClient, pid: str, footage: Path, api_settings: Settings
) -> None:
    media = _ingest(client, pid, footage / "a_h264.mp4", api_settings)
    res = client.get(f"/api/media/{media}/tags").json()
    assert res["status"] == "model_missing" and "models pull" in res["message"]
    states = {e["kind"]: e["status"] for e in client.get(f"/api/media/{media}/embeddings").json()}
    assert states == {"visual": "model_missing", "text": "no_transcript"}
    job = client.get(f"/api/jobs?project_id={pid}").json()[0]
    assert job["status"] == "succeeded"


def test_transcript_segments_get_text_vectors(
    client: TestClient,
    pid: str,
    footage: Path,
    api_settings: Settings,
    fake: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = transcriber.choose_model(api_settings).path
    folder.mkdir(parents=True)
    for name in MODEL_FILES:
        (folder / name).write_bytes(b"test")

    def speak(*_args: Any) -> dict[str, Any]:
        seg = {"avg_logprob": -0.2, "no_speech_prob": 0.1, "compression_ratio": 1.2}
        return {
            "language": "en",
            "language_probability": 0.9,
            "speech_s": 1.6,
            "segments": [
                {
                    **seg,
                    "start": 0.1,
                    "end": 0.9,
                    "text": "walking home",
                    "words": [[0.1, 0.9, "walking", 0.9]],
                },
                {
                    **seg,
                    "start": 1.0,
                    "end": 1.9,
                    "text": "at night",
                    "words": [[1.0, 1.9, "night", 0.9]],
                },
            ],
        }

    monkeypatch.setattr(transcriber, "transcribe", speak)
    media = _ingest(client, pid, footage / "a_h264.mp4", api_settings)
    with _session(api_settings) as s:
        rows = list(
            s.scalars(
                select(Embedding).where(Embedding.media_id == media, Embedding.kind == "segment")
            )
        )
        assert len(rows) == 2 and fake.texts == 2
        tags = {t.name: t for t in s.scalars(select(Tag).where(Tag.media_id == media))}
        assert tags["speech"].status == "shown" and tags["speech"].details["speech_s"] >= 1.0


# --- the index ----------------------------------------------------------------------------------


def test_vector_index_is_rebuilt_from_the_database(
    client: TestClient, pid: str, footage: Path, api_settings: Settings, fake: FakeEmbedder
) -> None:
    media = _ingest(client, pid, footage / "a_h264.mp4", api_settings)
    _ingest(client, pid, footage / "e_vfr.mp4", api_settings)
    listed = client.get(f"/api/projects/{pid}/index").json()
    assert [(i["kind"], i["up_to_date"]) for i in listed] == [("keyframe", True)]
    model = listed[0]["model"]
    with _session(api_settings) as s:
        record = s.scalar(select(VectorIndexRow).where(VectorIndexRow.project_id == pid))
        assert record is not None and record.count == listed[0]["count"]
        path = api_settings.project_dir(pid) / record.path
        target = s.scalar(
            select(Embedding).where(Embedding.media_id == media, Embedding.kind == "keyframe")
        )
        assert target is not None
        query = np.frombuffer(target.vector, dtype=np.float32)
        hits = vector_index.search(s, api_settings, pid, "keyframe", model, query, 3)
        assert hits[0][0] == target.ref_id and hits[0][1] == pytest.approx(1.0, abs=1e-5)
    path.unlink()  # derived data: losing it costs nothing
    assert client.get(f"/api/projects/{pid}/index").json()[0]["up_to_date"] is False
    rebuilt = client.post(f"/api/projects/{pid}/index/rebuild").json()
    assert rebuilt[0]["up_to_date"] is True and path.is_file()
    client.delete(f"/api/media/{media}")  # its rows go, so the index shrinks
    after = client.get(f"/api/projects/{pid}/index").json()
    assert after[0]["count"] < listed[0]["count"] and after[0]["up_to_date"] is True


def test_project_tag_counts_and_reviews(
    client: TestClient, pid: str, footage: Path, api_settings: Settings, fake: FakeEmbedder
) -> None:
    media = _ingest(client, pid, footage / "a_h264.mp4", api_settings)
    with _session(api_settings) as s:
        shot = s.scalar(select(Shot).where(Shot.media_id == media))
        assert shot is not None and s.get(MediaAsset, media) is not None
        shot_id = shot.id
    assert client.get(f"/api/projects/{pid}/tags").json()[0]["name"] == "forest"
    res = client.put(
        "/api/tags/review", json={"shot_id": shot_id, "name": "forest", "decision": "rejected"}
    )
    assert res.status_code == 200
    tag = next(t for t in res.json()["shots"][0]["tags"] if t["name"] == "forest")
    assert tag["review"] == "rejected" and tag["visible"] is False
    assert client.get(f"/api/projects/{pid}/tags").json() == []
    res = client.put(
        "/api/tags/review", json={"shot_id": shot_id, "name": "wide", "decision": "approved"}
    )
    tag = next(t for t in res.json()["shots"][0]["tags"] if t["name"] == "wide")
    assert tag["visible"] is True and tag["status"] == "not_evaluated"  # the user's word counts
    client.post(f"/api/media/{media}/process")
    drain(api_settings)  # tag rows are rewritten; the reviews stay
    tags = client.get(f"/api/media/{media}/tags").json()["shots"][0]["tags"]
    assert {t["name"]: t["review"] for t in tags if t["review"]} == {
        "forest": "rejected",
        "wide": "approved",
    }
    bad = client.put(
        "/api/tags/review", json={"shot_id": shot_id, "name": "spaceship", "decision": "approved"}
    )
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_input"
    gone = client.put(
        "/api/tags/review", json={"shot_id": "nope", "name": "wide", "decision": "none"}
    )
    assert gone.status_code == 404


@pytest.mark.model
@pytest.mark.parametrize("visual_key", ["clip-vit-b32", "siglip-base"])
def test_real_models_match_pictures_and_sentences_by_meaning(visual_key: str) -> None:
    from cinemind.core.embed_config import VISUAL_MODELS

    real = Settings()
    visual, text = VISUAL_MODELS[visual_key], embedder.choose_text(real)
    if not (visual.ready(real.models_path) and text.ready(real.models_path)):
        pytest.skip(f"needs the downloaded models (cinemind models pull {visual_key})")
    red = np.zeros((240, 320, 3), dtype=np.uint8)
    red[:, :, 2] = 230
    blue = np.zeros_like(red)
    blue[:, :, 0] = 230
    images = embedder.embed_images(visual, real, [red, blue])
    prompts = embedder.embed_prompts(visual, real, ["a plain red picture", "a plain blue picture"])
    assert images.shape == (2, visual.dim)
    assert np.allclose(np.linalg.norm(images, axis=1), 1, atol=1e-4)
    sims = images @ prompts.T
    assert sims[0, 0] > sims[0, 1] and sims[1, 1] > sims[1, 0]
    sentences = embedder.embed_texts(
        text, real, ["he walks home at night", "a man walking back after dark", "rice prices rose"]
    )
    near, far = float(sentences[0] @ sentences[1]), float(sentences[0] @ sentences[2])
    assert near > 0.5 > far


def test_a_model_that_goes_missing_and_comes_back_keeps_and_restores_everything(
    client: TestClient,
    pid: str,
    footage: Path,
    api_settings: Settings,
    fake: FakeEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cinemind.core.embed_config import VISUAL_MODELS

    media = _ingest(client, pid, footage / "a_h264.mp4", api_settings)
    with _session(api_settings) as s:
        vectors = s.query(Embedding).filter_by(media_id=media, kind="keyframe").count()
        tags = s.query(Tag).filter_by(media_id=media, source="model").count()
    other = next(k for k in VISUAL_MODELS if k != embedder.choose_visual(api_settings).key)
    monkeypatch.setattr(api_settings.embed, "visual_model", other)  # not on disk
    client.post(f"/api/media/{media}/process")
    drain(api_settings)
    assert client.get(f"/api/media/{media}/tags").json()["status"] == "model_missing"
    with _session(api_settings) as s:  # what the earlier run found stays
        assert s.query(Embedding).filter_by(media_id=media, kind="keyframe").count() == vectors
        assert s.query(Tag).filter_by(media_id=media, source="model").count() == tags
    monkeypatch.setattr(api_settings.embed, "visual_model", "auto")
    client.post(f"/api/media/{media}/process")
    drain(api_settings)  # the cached result of the first run comes back
    assert client.get(f"/api/media/{media}/tags").json()["status"] == "done"


def test_a_failing_gpu_falls_back_to_the_cpu_once_and_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import torch

    monkeypatch.setattr(embedder, "_FAILED_DEVICES", set())
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    loads: list[str] = []

    def load(device: str) -> str:
        loads.append(device)
        return device

    def run(device: str) -> str:
        if device == "mps":
            raise RuntimeError("MPS backend out of memory")
        return device

    assert embedder.pick_device("auto") == "mps"
    assert embedder._on_device(load, "auto", run) == "cpu"  # pyright: ignore[reportPrivateUsage]
    assert embedder._on_device(load, "auto", run) == "cpu"  # pyright: ignore[reportPrivateUsage]
    assert loads == ["mps", "cpu", "cpu"]  # the GPU is not tried again for every batch
    assert embedder.pick_device("auto") == "cpu"  # and the result says where it ran
    with pytest.raises(RuntimeError):  # a device the user chose is not replaced silently
        embedder._on_device(load, "mps", run)  # pyright: ignore[reportPrivateUsage]
