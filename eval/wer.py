"""Word error rate (WER) and speed of the app's transcription on a labelled sample.

It calls the same functions the `transcribe` stage calls (our ffmpeg decode, faster-whisper with
the `[transcribe]` settings), so the numbers describe the app, not the model in isolation.

  uv run python eval/wer.py fetch
      Download Mini LibriSpeech dev-clean-2 (126 MB, read English audiobooks, CC BY 4.0,
      https://www.openslr.org/31/) into data/eval/. Setup step; needs internet.
  uv run python eval/wer.py run <folder> [--models base small] [--minutes 10] [--language auto]
      <folder> is searched for LibriSpeech transcripts (`*.trans.txt` next to the audio) and for
      pairs `clip.<ext>` + `clip.txt` (a hand-written transcript of your own clip).
      Writes eval/results/wer_<folder name>_<date>.txt and .json.

Scoring: both texts are lower-cased, punctuation is removed, whitespace collapsed; then
WER = (substitutions + deletions + insertions) / reference words, over all utterances together
(jiwer). Numbers written as digits by the model count as errors against spelled-out references.
"""

import argparse
import json
import platform
import random
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import date
from pathlib import Path
from typing import Any

import jiwer
import numpy as np
import psutil

from cinemind.ai import transcriber
from cinemind.core.config import REPO_ROOT, get_settings
from cinemind.core.hardware import detect_hardware

DATASET_URL = "https://www.openslr.org/resources/31/dev-clean-2.tar.gz"
DATASET_DIR = REPO_ROOT / "data" / "eval" / "librispeech-dev-clean-2"
AUDIO = {".flac", ".wav", ".mp3", ".m4a", ".aiff", ".mov", ".mp4", ".mkv", ".mxf"}
NORMALISE = jiwer.Compose(
    [
        jiwer.ToLowerCase(),
        jiwer.RemovePunctuation(),
        jiwer.RemoveMultipleSpaces(),
        jiwer.Strip(),
        jiwer.ReduceToListOfListOfWords(),
    ]
)


def fetch() -> None:
    if any(DATASET_DIR.rglob("*.trans.txt")):
        print(f"already there: {DATASET_DIR}")
        return
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    archive = DATASET_DIR / "dev-clean-2.tar.gz"
    print(f"downloading {DATASET_URL} ...")
    curl = shutil.which("curl")
    if curl is None:
        sys.exit(f"curl is needed for the download; or fetch {DATASET_URL} by hand")
    # curl uses the system certificate store (python.org builds of Python may have none).
    subprocess.run([curl, "-fL", "--retry", "3", "-o", str(archive), DATASET_URL], check=True)  # noqa: S603
    with tarfile.open(archive) as tar:
        tar.extractall(DATASET_DIR, filter="data")
    archive.unlink()
    print(f"done: {DATASET_DIR}")


def find_pairs(folder: Path) -> list[tuple[str, Path, str]]:
    """(utterance id, audio file, reference text), sorted by id."""
    pairs: dict[str, tuple[Path, str]] = {}
    for listing in folder.rglob("*.trans.txt"):
        for line in listing.read_text(encoding="utf-8").splitlines():
            name, _, text = line.partition(" ")
            audio = listing.with_name(name + ".flac")
            if text.strip() and audio.is_file():
                pairs[name] = (audio, text.strip())
    for reference in folder.rglob("*.txt"):
        if reference.name.endswith(".trans.txt"):
            continue
        for audio in reference.parent.glob(reference.stem + ".*"):
            if audio.suffix.lower() in AUDIO and reference.read_text(encoding="utf-8").strip():
                pairs[reference.stem] = (audio, reference.read_text(encoding="utf-8").strip())
    return [(name, *pairs[name]) for name in sorted(pairs)]


def run(folder: Path, models: list[str], minutes: float, language: str, seed: int) -> None:
    settings = get_settings()
    cfg = settings.transcribe.model_copy(update={"language": language})
    pairs = find_pairs(folder)
    if not pairs:
        sys.exit(f"no labelled audio found under {folder}")
    random.Random(seed).shuffle(pairs)  # noqa: S311 - a reproducible sample, not security

    sample: list[tuple[str, Any, str]] = []
    seconds = 0.0
    for name, audio_file, reference in pairs:
        if seconds >= minutes * 60:
            break
        audio = transcriber.decode_audio(audio_file, lambda: None)
        sample.append((name, audio, reference))
        seconds += len(audio) / transcriber.SAMPLE_RATE
    hw = detect_hardware(str(REPO_ROOT))
    report: dict[str, Any] = {
        "date": date.today().isoformat(),
        "dataset": str(folder),
        "utterances": len(sample),
        "available_utterances": len(pairs),
        "audio_minutes": round(seconds / 60, 2),
        "sample_seed": seed,
        "utterance_ids": [name for name, _, _ in sample],
        "hardware": (
            f"{hw.cpu_name}, {hw.cpu_cores} threads, {hw.ram_gb} GB RAM, {platform.system()}"
        ),
        "engine": transcriber.engine_version(),
        "settings": cfg.model_dump(exclude={"model"}),
        "normalisation": "lower case, punctuation removed, whitespace collapsed",
        "models": {},
    }
    lines = [
        f"WER on {len(sample)} of {len(pairs)} utterances ({report['audio_minutes']} min)",
        f"dataset {folder}",
        f"date {report['date']} | {report['hardware']} | engine {report['engine']}",
        f"settings {report['settings']} | sample seed {seed}",
        f"scoring: {report['normalisation']}; errors / reference words over the whole sample",
        "",
        "model     revision      WER %   sub   del   ins  ref words  other-lang  sec/audio-sec"
        "  RSS MB",
    ]
    for model in models:
        choice = transcriber.choose_model(settings, model)
        if not choice.ready:
            sys.exit(f"model '{model}' is not downloaded: uv run cinemind models pull {model}")
        quiet = np.zeros(transcriber.SAMPLE_RATE, dtype=np.float32)
        transcriber.transcribe(choice, quiet, cfg, lambda _f: None, lambda: None)  # load the model
        references: list[str] = []
        hypotheses: list[str] = []
        other_language = 0
        compute = ""
        started = time.perf_counter()
        for _name, audio, reference in sample:
            out = transcriber.transcribe(choice, audio, cfg, lambda _f: None, lambda: None)
            compute = f"{out['device']} {out['compute_type']}"
            other_language += out["language"] not in ("en", None) if language == "auto" else 0
            references.append(reference)
            hypotheses.append(" ".join(seg["text"] for seg in out["segments"]))
        elapsed = time.perf_counter() - started
        scored = jiwer.process_words(
            references, hypotheses, reference_transform=NORMALISE, hypothesis_transform=NORMALISE
        )
        ref_words = scored.hits + scored.substitutions + scored.deletions
        result = {
            "revision": choice.revision,
            "compute": compute,
            "wer": round(scored.wer, 4),
            "substitutions": scored.substitutions,
            "deletions": scored.deletions,
            "insertions": scored.insertions,
            "reference_words": ref_words,
            "utterances_detected_as_another_language": other_language,
            "seconds": round(elapsed, 1),
            "seconds_per_audio_second": round(elapsed / seconds, 3),
            "resident_memory_mb": round(psutil.Process().memory_info().rss / 1024**2),
        }
        report["models"][model] = result
        lines.append(
            f"{model:<9} {choice.revision[:12]}  {100 * scored.wer:5.2f} {scored.substitutions:5d} "
            f"{scored.deletions:5d} {scored.insertions:5d} {ref_words:10d} {other_language:11d} "
            f"{result['seconds_per_audio_second']:14.3f} {result['resident_memory_mb']:7d}"
        )
        print(lines[-1], flush=True)
    lines += [
        "",
        f"compute: {', '.join(sorted({m['compute'] for m in report['models'].values()}))}",
    ]
    out_dir = REPO_ROOT / "eval" / "results"
    stem = f"wer_{folder.resolve().name}_{report['date']}"
    (out_dir / f"{stem}.txt").write_text("\n".join(lines) + "\n")
    (out_dir / f"{stem}.json").write_text(json.dumps(report, indent=2) + "\n")
    print("\n".join(lines))
    print(f"\nwrote eval/results/{stem}.txt and .json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fetch")
    runner = commands.add_parser("run")
    runner.add_argument("folder", type=Path)
    runner.add_argument("--models", nargs="+", default=["small"])
    runner.add_argument("--minutes", type=float, default=10.0)
    runner.add_argument("--language", default="auto")
    runner.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.command == "fetch":
        fetch()
    else:
        run(args.folder, args.models, args.minutes, args.language, args.seed)
