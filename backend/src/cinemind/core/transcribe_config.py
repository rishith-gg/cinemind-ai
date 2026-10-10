"""Speech-to-text settings (settings section `[transcribe]`) and the Whisper models the app knows.

The models are existing ones (OpenAI Whisper converted for CTranslate2 by Systran); each is pinned
to a repository revision so a transcript can be reproduced. Repositories, revisions and sizes
were read from the Hugging Face model index on 2026-10-10.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, model_validator

from cinemind.core.hardware import Tier


@dataclass(frozen=True)
class WhisperModel:
    repo: str
    revision: str
    size_mb: int  # download size, rounded up


WHISPER_MODELS: dict[str, WhisperModel] = {
    "tiny": WhisperModel(
        "Systran/faster-whisper-tiny", "d90ca5fe260221311c53c58e660288d3deb8d356", 79
    ),
    "base": WhisperModel(
        "Systran/faster-whisper-base", "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66", 148
    ),
    "small": WhisperModel(
        "Systran/faster-whisper-small", "536b0662742c02347bc0e980a01041f333bce120", 487
    ),
    "medium": WhisperModel(
        "Systran/faster-whisper-medium", "08e178d48790749d25932bbc082711ddcfdfbc4f", 1531
    ),
    "large-v3": WhisperModel(
        "Systran/faster-whisper-large-v3", "edaa852ec7e145841d8ffdb056a99866b5f0a478", 3091
    ),
}
# SPEC section 6. All of these are multilingual models.
TIER_MODEL: dict[Tier, str] = {"lite": "small", "balanced": "small", "quality": "large-v3"}
MODEL_FILES = ("model.bin", "config.json", "tokenizer.json")


def model_dir(models_root: Path, name: str) -> Path:
    """Where a model's pinned revision is kept; a new revision gets a new folder."""
    return models_root / "whisper" / f"{name}-{WHISPER_MODELS[name].revision[:12]}"


def model_ready(folder: Path) -> bool:
    return all((folder / name).is_file() for name in MODEL_FILES)


# When a transcript is marked uncertain. The first two are the model's own acceptance limits
# (Whisper retries a segment that crosses them and keeps its last attempt even if that fails
# too); the third is the library's default `language_detection_threshold`. Conventions, not
# limits we evaluated.
UNCERTAIN_LOGPROB_BELOW = -1.0
UNCERTAIN_COMPRESSION_ABOVE = 2.4
UNCERTAIN_LANGUAGE_BELOW = 0.5


def is_uncertain(avg_logprob: float, compression_ratio: float) -> bool:
    return avg_logprob < UNCERTAIN_LOGPROB_BELOW or compression_ratio > UNCERTAIN_COMPRESSION_ABOVE


# Downloads above this size need an explicit yes (CLAUDE.md rule 10).
ASK_ABOVE_MB = 2048


class TranscribeConfig(BaseModel):
    # "auto" = the model of the hardware tier (TIER_MODEL); or one of WHISPER_MODELS.
    model: str = "auto"
    # "auto" = detect the language from the first 30 s of speech; or a code such as "en", "ta".
    language: str = "auto"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    # "auto" = int8 on CPU, float16 on an NVIDIA GPU.
    compute_type: str = "auto"
    # The remaining values are the library's defaults, stated here so they are part of the
    # cache key and shown next to each transcript.
    beam_size: int = 5
    vad_threshold: float = 0.5
    vad_min_silence_ms: int = 2000

    @model_validator(mode="after")
    def _known(self) -> Self:
        if self.model != "auto" and self.model not in WHISPER_MODELS:
            known = ", ".join(WHISPER_MODELS)
            raise ValueError(f"transcribe.model must be 'auto' or one of: {known}")
        if not 1 <= self.beam_size <= 10:
            raise ValueError("transcribe.beam_size must be between 1 and 10")
        if not 0 < self.vad_threshold < 1:
            raise ValueError("transcribe.vad_threshold must be between 0 and 1")
        if self.vad_min_silence_ms < 0:
            raise ValueError("transcribe.vad_min_silence_ms must not be negative")
        language = self.language
        if language != "auto" and not (language.isalpha() and 2 <= len(language) <= 3):
            raise ValueError("transcribe.language must be 'auto' or a language code such as 'en'")
        return self
