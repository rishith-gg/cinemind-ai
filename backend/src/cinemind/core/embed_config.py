"""Embedding settings (sections `[embed]` and `[scenes]`) and the embedding models the app knows.

Existing models: OpenCLIP ViT-B/32 trained on LAION-2B (MIT), Google SigLIP (Apache 2.0) for
pictures, and two sentence-transformers MiniLM models (Apache 2.0) for transcript text. Each is
pinned to a repository revision, and its weights file is checked against a SHA-256 after the
download. Repositories, revisions, sizes, licences and checksums were read from the Hugging Face
model index on 2026-10-14.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, model_validator

from cinemind.core.hardware import Tier

Family = Literal["clip", "siglip", "minilm"]
WEIGHTS = "model.safetensors"


@dataclass(frozen=True)
class EmbedModel:
    key: str
    repo: str
    revision: str
    family: Family
    dim: int
    size_mb: int  # download size, rounded up
    sha256: str  # of the weights file
    licence: str
    # Files fetched besides the weights (tokenizer, configs). Small.
    files: tuple[str, ...]

    def path(self, models_root: Path) -> Path:
        """A new revision gets a new folder, so an old download is never mistaken for it."""
        return models_root / "embed" / f"{self.key}-{self.revision[:12]}"

    def ready(self, models_root: Path) -> bool:
        folder = self.path(models_root)
        return all((folder / name).is_file() for name in (WEIGHTS, *self.files))


_CLIP_FILES = (
    "config.json",
    "preprocessor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.json",
    "merges.txt",
)
_SIGLIP_FILES = (
    "config.json",
    "preprocessor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "spiece.model",
)
_MINILM_FILES = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "sentence_bert_config.json",
    "1_Pooling/config.json",
)

VISUAL_MODELS: dict[str, EmbedModel] = {
    "clip-vit-b32": EmbedModel(
        "clip-vit-b32",
        "laion/CLIP-ViT-B-32-laion2B-s34B-b79K",
        "1a25a446712ba5ee05982a381eed697ef9b435cf",
        "clip",
        512,
        578,
        "74813fbcdc750f235c9784c367ca1394d2a5c25eb0aac92761752ac239db7cff",
        "MIT",
        _CLIP_FILES,
    ),
    "siglip-base": EmbedModel(
        "siglip-base",
        "google/siglip-base-patch16-224",
        "7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed",
        "siglip",
        768,
        779,
        "2c63cb7d1f2e95ba501893cbb8faeb4ea9a3af295498d35097126228659c2af8",
        "Apache-2.0",
        _SIGLIP_FILES,
    ),
    "siglip-so400m": EmbedModel(
        "siglip-so400m",
        "google/siglip-so400m-patch14-384",
        "9fdffc58afc957d1a03a25b10dba0329ab15c2a3",
        "siglip",
        1152,
        3352,
        "ea2abad2b7f8a9c1aa5e49a244d5d57ffa71c56f720c94bc5d240ef4d6e1d94a",
        "Apache-2.0",
        _SIGLIP_FILES,
    ),
}
TEXT_MODELS: dict[str, EmbedModel] = {
    "minilm-l6": EmbedModel(
        "minilm-l6",
        "sentence-transformers/all-MiniLM-L6-v2",
        "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        "minilm",
        384,
        87,
        "53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db",
        "Apache-2.0",
        (*_MINILM_FILES, "vocab.txt"),
    ),
    "multilingual-minilm-l12": EmbedModel(
        "multilingual-minilm-l12",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "e8f8c211226b894fcb81acc59f3b34ba3efd5f42",
        "minilm",
        384,
        449,
        "eaa086f0ffee582aeb45b36e34cdd1fe2d6de2bef61f8a559a1bbc9bd955917b",
        "Apache-2.0",
        _MINILM_FILES,
    ),
}
# SPEC section 6: OpenCLIP ViT-B/32 on lite, SigLIP base on balanced, a larger SigLIP on quality.
TIER_VISUAL: dict[Tier, str] = {
    "lite": "clip-vit-b32",
    "balanced": "siglip-base",
    "quality": "siglip-so400m",
}
# SPEC: a small English model by default; the multilingual one is a setting.
TIER_TEXT: dict[Tier, str] = {"lite": "minilm-l6", "balanced": "minilm-l6", "quality": "minilm-l6"}


class EmbedConfig(BaseModel):
    # "auto" = the model of the hardware tier; or a key of VISUAL_MODELS / TEXT_MODELS.
    visual_model: str = "auto"
    text_model: str = "auto"
    # "auto" = an NVIDIA GPU if there is one, else Apple's GPU (MPS), else the CPU.
    device: Literal["auto", "cpu", "mps", "cuda"] = "auto"
    batch_size: int = 16
    # Vector index: "auto" = numpy on macOS (see search/vector_index.py), FAISS elsewhere.
    index_backend: Literal["auto", "faiss", "numpy"] = "auto"

    @model_validator(mode="after")
    def _known(self) -> Self:
        if self.visual_model != "auto" and self.visual_model not in VISUAL_MODELS:
            raise ValueError(
                f"embed.visual_model must be 'auto' or one of: {', '.join(VISUAL_MODELS)}"
            )
        if self.text_model != "auto" and self.text_model not in TEXT_MODELS:
            raise ValueError(f"embed.text_model must be 'auto' or one of: {', '.join(TEXT_MODELS)}")
        if not 1 <= self.batch_size <= 256:
            raise ValueError("embed.batch_size must be between 1 and 256")
        return self


class SceneConfig(BaseModel):
    """Grouping neighbouring shots into scenes. All three numbers are conventions: no footage with
    labelled scenes exists to set them (see AI_PIPELINE.md "Scenes"). The user can split and join
    scenes by hand."""

    # Two neighbouring shots belong to one scene when the weighted similarity reaches this.
    join_similarity: float = 0.8
    # Weights of the two signals: picture vectors (cosine) and colour (histogram intersection).
    visual_weight: float = 0.7
    color_weight: float = 0.3

    @model_validator(mode="after")
    def _ranges(self) -> Self:
        if not 0 < self.join_similarity < 1:
            raise ValueError("scenes.join_similarity must be between 0 and 1")
        if self.visual_weight < 0 or self.color_weight < 0:
            raise ValueError("scenes weights must not be negative")
        if self.visual_weight + self.color_weight == 0:
            raise ValueError("scenes weights must not both be 0")
        return self
