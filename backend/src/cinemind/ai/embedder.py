"""Picture and text vectors, with existing models run through Hugging Face `transformers`.

Existing models: OpenCLIP ViT-B/32 or SigLIP (picture and text towers that share one space) and
a MiniLM sentence model (transcript text). Ours: picking the model for the hardware tier, keeping
downloads out of processing (fetched once by `cinemind models pull`, afterwards only read from
disk), the image preparation (OpenCV, following each model's own preprocessing settings), mean
pooling for MiniLM as its model card describes, and the colour histogram used for scenes.
"""

# torch and transformers objects are only partly typed.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

import hashlib
import json
import logging
import shutil
from collections.abc import Callable, Sequence
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from cinemind.core.config import Settings
from cinemind.core.embed_config import (
    TEXT_MODELS,
    TIER_TEXT,
    TIER_VISUAL,
    VISUAL_MODELS,
    WEIGHTS,
    EmbedModel,
)
from cinemind.core.errors import InvalidInputError, ModelMissingError
from cinemind.core.hardware import tier_in_use

log = logging.getLogger(__name__)

PULL_HINT = "Run `uv run cinemind models pull` once (needs internet), then press Reprocess."
# Colour histogram: hue x saturation x value bins on the HSV image.
HIST_BINS = (8, 4, 4)
_HIST_HEIGHT = 180  # frames are shrunk to this height first; colour needs no detail


def engine_version() -> str:
    return f"transformers-{version('transformers')}+torch-{version('torch')}"


def choose_visual(settings: Settings, name: str | None = None) -> EmbedModel:
    return _choose(name or settings.embed.visual_model, VISUAL_MODELS, TIER_VISUAL, settings)


def choose_text(settings: Settings, name: str | None = None) -> EmbedModel:
    return _choose(name or settings.embed.text_model, TEXT_MODELS, TIER_TEXT, settings)


def _choose(
    name: str, known: dict[str, EmbedModel], tiers: dict[Any, str], settings: Settings
) -> EmbedModel:
    if name == "auto":
        name = tiers[tier_in_use(settings.model_tier)]
    if name not in known:
        raise InvalidInputError(f"Unknown model '{name}'. Known: {', '.join(known)}.")
    return known[name]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def pull(spec: EmbedModel, models_root: Path) -> None:
    """Download the pinned revision and check the weights (setup time only; needs internet)."""
    from huggingface_hub import snapshot_download

    target = spec.path(models_root)
    partial = target.with_name(target.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    partial.parent.mkdir(parents=True, exist_ok=True)
    try:
        snapshot_download(
            spec.repo,
            revision=spec.revision,
            allow_patterns=[WEIGHTS, *spec.files],
            local_dir=str(partial),
        )
        if _sha256(partial / WEIGHTS) != spec.sha256:
            raise ModelMissingError(
                f"The download of '{spec.key}' does not match its checksum. Try again."
            )
        missing = [name for name in spec.files if not (partial / name).is_file()]
        if missing:
            raise ModelMissingError(f"The download of '{spec.key}' is incomplete. Try again.")
        shutil.rmtree(partial / ".cache", ignore_errors=True)
        shutil.rmtree(target, ignore_errors=True)
        partial.rename(target)
    finally:
        shutil.rmtree(partial, ignore_errors=True)


# --- devices ----------------------------------------------------------------------------------


# GPUs that failed once in this process: later batches go straight to the CPU instead of
# loading the model on the GPU again for every batch.
_FAILED_DEVICES: set[str] = set()


def pick_device(wanted: str) -> str:
    """The device embeddings run on (and are recorded with): the setting, or for "auto" an
    NVIDIA GPU, else Apple's GPU, else the CPU, skipping a GPU that already failed here."""
    import torch

    if wanted != "auto":
        return wanted
    if torch.cuda.is_available() and "cuda" not in _FAILED_DEVICES:
        return "cuda"
    if torch.backends.mps.is_available() and "mps" not in _FAILED_DEVICES:
        return "mps"
    return "cpu"


def _on_device(load: Callable[[str], Any], wanted: str, run: Callable[[Any], Any]) -> Any:
    """Run on the chosen device; a GPU chosen automatically that fails (driver, memory, an
    operation it lacks) falls back to the CPU instead of failing the clip, and stays skipped."""
    device = pick_device(wanted)
    try:
        return run(load(device))
    except (RuntimeError, NotImplementedError) as exc:
        if wanted != "auto" or device == "cpu":
            raise
        log.warning("embedding on %s failed (%s); using the CPU from now on", device, exc)
        _FAILED_DEVICES.add(device)
        return run(load("cpu"))


# --- picture model (CLIP / SigLIP) -----------------------------------------------------------


class VisualModel:
    """One loaded picture model: images and short texts to vectors in the same space."""

    def __init__(self, spec: EmbedModel, models_root: Path, device: str) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        folder = spec.path(models_root)
        if not spec.ready(models_root):
            raise ModelMissingError(
                f"The picture model '{spec.key}' ({spec.size_mb} MB) is not downloaded."
            )
        log.info("loading picture model %s on %s", spec.key, device)
        self.spec, self.device = spec, device
        self.model: Any = AutoModel.from_pretrained(str(folder), local_files_only=True)
        self.model.to(device).eval()
        self.tokenizer: Any = AutoTokenizer.from_pretrained(str(folder), local_files_only=True)
        self.prep: dict[str, Any] = json.loads((folder / "preprocessor_config.json").read_text())
        self.logit_scale = float(self.model.logit_scale.detach().exp().cpu())
        self._torch = torch

    def prepare(self, bgr: Any) -> Any:
        """One BGR frame as the model's input array (3, H, W), following its preprocessor
        settings: resize (shortest side, or to a fixed size), centre crop, scale, normalise.
        OpenCV's area filter shrinks (close to PIL's antialiased bicubic, which the models
        were trained with); bicubic enlarges."""
        prep = self.prep
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        size = prep.get("size", 224)
        if isinstance(size, dict) and "height" in size:
            new_w, new_h = int(size["width"]), int(size["height"])
        else:
            short = int(size["shortest_edge"] if isinstance(size, dict) else size)
            scale = short / min(h, w)
            new_w, new_h = max(short, round(w * scale)), max(short, round(h * scale))
        shrink = new_w * new_h < w * h
        rgb = cv2.resize(
            rgb, (new_w, new_h), interpolation=cv2.INTER_AREA if shrink else cv2.INTER_CUBIC
        )
        if prep.get("do_center_crop"):
            crop = prep.get("crop_size", 224)
            cw, ch = (crop["width"], crop["height"]) if isinstance(crop, dict) else (crop, crop)
            top, left = (new_h - ch) // 2, (new_w - cw) // 2
            rgb = rgb[top : top + ch, left : left + cw]
        pixels = rgb.astype(np.float32) * float(prep.get("rescale_factor", 1 / 255))
        pixels = (pixels - np.array(prep["image_mean"], np.float32)) / np.array(
            prep["image_std"], np.float32
        )
        return pixels.transpose(2, 0, 1)

    def images(self, frames: Sequence[Any]) -> Any:
        torch = self._torch
        batch = torch.from_numpy(np.stack([self.prepare(f) for f in frames])).to(self.device)
        with torch.inference_mode():
            out = self.model.get_image_features(pixel_values=batch)
        return _normalised(_tensor(out))

    def texts(self, prompts: Sequence[str]) -> Any:
        torch = self._torch
        # SigLIP was trained on texts padded to the full length; CLIP pads to the longest.
        padding = "max_length" if self.spec.family == "siglip" else True
        tokens = self.tokenizer(
            list(prompts), padding=padding, truncation=True, return_tensors="pt"
        ).to(self.device)
        with torch.inference_mode():
            out = self.model.get_text_features(**tokens)
        return _normalised(_tensor(out))


@lru_cache(maxsize=1)
def _visual(spec: EmbedModel, models_root: Path, device: str) -> VisualModel:
    return VisualModel(spec, models_root, device)


def embed_images(spec: EmbedModel, settings: Settings, frames: Sequence[Any]) -> Any:
    """Unit-length picture vectors, float32 (n, dim)."""
    return _on_device(
        lambda d: _visual(spec, settings.models_path, d),
        settings.embed.device,
        lambda m: m.images(frames),
    )


def embed_prompts(spec: EmbedModel, settings: Settings, prompts: Sequence[str]) -> Any:
    """Unit-length vectors of short texts in the picture model's space, float32 (n, dim)."""
    return _on_device(
        lambda d: _visual(spec, settings.models_path, d),
        settings.embed.device,
        lambda m: m.texts(prompts),
    )


def logit_scale(spec: EmbedModel, settings: Settings) -> float:
    """The model's learned temperature (CLIP: 100; SigLIP: about 117)."""
    return float(
        _on_device(
            lambda d: _visual(spec, settings.models_path, d),
            settings.embed.device,
            lambda m: m.logit_scale,
        )
    )


# --- sentence model (MiniLM) ------------------------------------------------------------------


class TextModel:
    def __init__(self, spec: EmbedModel, models_root: Path, device: str) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        folder = spec.path(models_root)
        if not spec.ready(models_root):
            raise ModelMissingError(
                f"The text model '{spec.key}' ({spec.size_mb} MB) is not downloaded."
            )
        log.info("loading text model %s on %s", spec.key, device)
        self.device = device
        self.model: Any = AutoModel.from_pretrained(str(folder), local_files_only=True)
        self.model.to(device).eval()
        self.tokenizer: Any = AutoTokenizer.from_pretrained(str(folder), local_files_only=True)
        config = json.loads((folder / "sentence_bert_config.json").read_text())
        self.max_length = int(config["max_seq_length"])
        self._torch = torch

    def encode(self, texts: Sequence[str]) -> Any:
        """Mean of the token vectors (padding left out), as the model card describes."""
        torch = self._torch
        tokens = self.tokenizer(
            list(texts),
            padding=True,
            truncation=True,
            max_length=self.max_length,
            return_tensors="pt",
        ).to(self.device)
        with torch.inference_mode():
            hidden = self.model(**tokens).last_hidden_state
        mask = tokens["attention_mask"].unsqueeze(-1).to(hidden.dtype)
        mean = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        return _normalised(mean)


@lru_cache(maxsize=1)
def _text(spec: EmbedModel, models_root: Path, device: str) -> TextModel:
    return TextModel(spec, models_root, device)


def embed_texts(spec: EmbedModel, settings: Settings, texts: Sequence[str]) -> Any:
    """Unit-length sentence vectors, float32 (n, dim)."""
    return _on_device(
        lambda d: _text(spec, settings.models_path, d),
        settings.embed.device,
        lambda m: m.encode(texts),
    )


# --- helpers ----------------------------------------------------------------------------------


def _tensor(out: Any) -> Any:
    """`get_*_features` returns a tensor, or in some versions an output object holding it."""
    if hasattr(out, "pooler_output") and not hasattr(out, "shape"):
        return out.pooler_output
    return out


def _normalised(tensor: Any) -> Any:
    vectors = tensor.detach().float().cpu().numpy().astype(np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, 1e-12)


def color_histogram(bgr: Any) -> Any:
    """Hue x saturation x value histogram, summing to 1 (float32). Two frames compare by
    histogram intersection (sum of the smaller bin), 1 = the same colours."""
    h, w = bgr.shape[:2]
    small = cv2.resize(
        bgr, (max(1, round(w * _HIST_HEIGHT / h)), _HIST_HEIGHT), interpolation=cv2.INTER_AREA
    )
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, list(HIST_BINS), [0, 180, 0, 256, 0, 256])
    flat = hist.flatten().astype(np.float32)
    return flat / max(float(flat.sum()), 1.0)
