"""Speech to text with faster-whisper.

Existing engine and models: faster-whisper (CTranslate2) running OpenAI Whisper weights, with the
Silero voice-activity detector it ships. Ours: picking the model for the hardware tier, keeping
downloads out of processing (a model is fetched once by `cinemind models pull` and afterwards
only ever read from disk), and the shape of the stored result.
"""

# faster-whisper and CTranslate2 ship without type information.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import numpy as np

from cinemind.core.config import Settings
from cinemind.core.errors import (
    InvalidInputError,
    ModelMissingError,
    TranscriptionError,
    UnreadableMediaError,
)
from cinemind.core.hardware import tier_in_use
from cinemind.core.transcribe_config import (
    TIER_MODEL,
    WHISPER_MODELS,
    TranscribeConfig,
    model_dir,
    model_ready,
)
from cinemind.pipeline.ffmpeg import pcm_chunks

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # what Whisper models are trained on
PULL_HINT = "Run `uv run cinemind models pull` once (needs internet), then press Reprocess."


@dataclass(frozen=True)
class ModelChoice:
    name: str
    repo: str
    revision: str
    size_mb: int
    path: Path

    @property
    def ready(self) -> bool:
        return model_ready(self.path)


def engine_version() -> str:
    try:
        return f"{version('faster-whisper')}+ct2-{version('ctranslate2')}"
    except PackageNotFoundError:  # pragma: no cover - both are hard dependencies
        return "unknown"


def choose_model(settings: Settings, name: str | None = None) -> ModelChoice:
    """The Whisper model in use: `name`, else `[transcribe] model`, else the hardware tier's."""
    name = name or settings.transcribe.model
    if name == "auto":
        name = TIER_MODEL[tier_in_use(settings.model_tier)]
    if name not in WHISPER_MODELS:
        raise InvalidInputError(
            f"Unknown speech model '{name}'. Known: {', '.join(WHISPER_MODELS)}."
        )
    spec = WHISPER_MODELS[name]
    folder = model_dir(settings.models_path, name)
    return ModelChoice(name, spec.repo, spec.revision, spec.size_mb, folder)


def pull(choice: ModelChoice) -> None:
    """Download the pinned revision into the models folder (setup time only; needs internet)."""
    from faster_whisper.utils import download_model

    partial = choice.path.with_name(choice.path.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    partial.parent.mkdir(parents=True, exist_ok=True)
    download_model(choice.repo, output_dir=str(partial), revision=choice.revision)
    if not model_ready(partial):
        shutil.rmtree(partial, ignore_errors=True)
        raise ModelMissingError(f"The download of '{choice.name}' is incomplete. Try again.")
    shutil.rmtree(choice.path, ignore_errors=True)
    partial.rename(choice.path)


def decode_audio(source: Path, check_cancelled: Callable[[], None]) -> Any:
    """First audio stream as mono float32 at 16 kHz, decoded by our own ffmpeg call."""
    failure = "The audio track could not be decoded for transcription."
    chunks = list(pcm_chunks(source, check_cancelled, failure, rate=SAMPLE_RATE, mono=True))
    if not chunks:
        raise UnreadableMediaError(failure)
    # Filled chunk by chunk: the 16-bit copy and the float copy are the only two alive at once.
    audio = np.empty(sum(len(chunk) for chunk in chunks), dtype=np.float32)
    position = 0
    while chunks:
        chunk = chunks.pop(0)
        audio[position : position + len(chunk)] = chunk
        position += len(chunk)
    audio /= 32768.0
    return audio


def _device(cfg: TranscribeConfig) -> tuple[str, str]:
    import ctranslate2

    device = cfg.device
    if device == "auto":
        device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
    compute = cfg.compute_type
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"
    return device, compute


@lru_cache(maxsize=1)
def _load(path: str, device: str, compute_type: str) -> Any:
    from faster_whisper import WhisperModel

    log.info("loading speech model %s on %s (%s)", Path(path).name, device, compute_type)
    return WhisperModel(path, device=device, compute_type=compute_type, local_files_only=True)


def _model(choice: ModelChoice, cfg: TranscribeConfig) -> tuple[Any, str, str]:
    """The loaded model. A GPU picked automatically that then fails to load (driver or memory)
    falls back to the CPU; an explicit choice does not."""
    if not choice.ready:
        raise ModelMissingError(f"The speech model '{choice.name}' is not downloaded. {PULL_HINT}")
    device, compute = _device(cfg)
    try:
        return _load(str(choice.path), device, compute), device, compute
    except (RuntimeError, ValueError) as exc:
        if device == "cpu" or cfg.device != "auto":
            log.warning("speech model failed to load: %s", exc)
            raise InvalidInputError(
                f"The speech model could not be loaded on {device} with compute type "
                f"'{compute}'. Check the [transcribe] settings."
            ) from exc
        log.warning("speech model failed on %s (%s); using the CPU", device, exc)
        return _load(str(choice.path), "cpu", "int8"), "cpu", "int8"


def _decode(
    model: Any,
    audio: Any,
    cfg: TranscribeConfig,
    progress: Callable[[float], None],
    check_cancelled: Callable[[], None],
) -> tuple[list[dict[str, Any]], Any]:
    total_s = len(audio) / SAMPLE_RATE
    try:
        found, info = model.transcribe(
            audio,
            language=None if cfg.language == "auto" else cfg.language,
            beam_size=cfg.beam_size,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={
                "threshold": cfg.vad_threshold,
                "min_silence_duration_ms": cfg.vad_min_silence_ms,
            },
        )
    except ValueError as exc:  # raised before any decoding, e.g. an unknown language code
        raise InvalidInputError(f"The speech model rejected the settings: {exc}") from exc
    segments: list[dict[str, Any]] = []
    for seg in found:
        check_cancelled()
        text = seg.text.strip()
        if not any(ch.isalnum() for ch in text):  # nothing, or punctuation only
            continue
        words = [
            [
                round(min(w.start, total_s), 3),
                round(min(w.end, total_s), 3),
                w.word.strip(),
                round(float(w.probability), 4),
            ]
            for w in seg.words or []
            if w.word.strip()
        ]
        segments.append(
            {
                "start": round(min(seg.start, total_s), 3),
                "end": round(min(seg.end, total_s), 3),
                "text": text,
                "avg_logprob": round(float(seg.avg_logprob), 4),
                "no_speech_prob": round(float(seg.no_speech_prob), 4),
                "compression_ratio": round(float(seg.compression_ratio), 3),
                "words": words,
            }
        )
        progress(seg.end / total_s if total_s > 0 else 1.0)
    return segments, info


def transcribe(
    choice: ModelChoice,
    audio: Any,
    cfg: TranscribeConfig,
    progress: Callable[[float], None],
    check_cancelled: Callable[[], None],
) -> dict[str, Any]:
    """Segments with word timings for 16 kHz mono audio. Speech is found by the voice-activity
    detector first, so silence and noise are not sent to the model. Times are seconds from the
    start of the audio. `language` is None when no speech was found. A GPU picked automatically
    that fails while decoding (missing GPU libraries, out of memory) is replaced by the CPU."""
    model, device, compute = _model(choice, cfg)
    try:
        segments, info = _decode(model, audio, cfg, progress, check_cancelled)
    except RuntimeError as exc:
        if device == "cpu" or cfg.device != "auto":
            log.exception("speech model failed on %s", device)
            raise TranscriptionError(
                f"The speech model failed while transcribing on {device}. See the log for details."
            ) from exc
        log.warning("speech model failed on %s (%s); transcribing on the CPU instead", device, exc)
        device, compute = "cpu", "int8"
        model = _load(str(choice.path), device, compute)
        segments, info = _decode(model, audio, cfg, progress, check_cancelled)
    return {
        "language": info.language if segments else None,
        "language_probability": round(float(info.language_probability), 4) if segments else None,
        "language_detected": cfg.language == "auto",
        "speech_s": round(float(info.duration_after_vad), 3),
        "device": device,
        "compute_type": compute,
        "segments": segments,
    }
