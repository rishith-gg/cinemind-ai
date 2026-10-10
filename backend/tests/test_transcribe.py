import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from typer.testing import CliRunner

from cinemind.ai import transcriber
from cinemind.cli import app as cli_app
from cinemind.core.config import Settings
from cinemind.core.doctor import check_speech_model
from cinemind.core.errors import InvalidInputError, TranscriptionError, UnreadableMediaError
from cinemind.core.transcribe_config import MODEL_FILES, TranscribeConfig, is_uncertain
from cinemind.db.base import make_engine
from cinemind.search.transcript_search import match_expression, query_terms
from helpers import drain, import_one


def _seg(start: float, words: list[tuple[str, float]], logprob: float = -0.3) -> dict[str, Any]:
    """A segment whose words are 0.5 s apart, starting at `start`."""
    timed = [[start + 0.5 * i, start + 0.5 * i + 0.4, w, p] for i, (w, p) in enumerate(words)]
    return {
        "start": start,
        "end": timed[-1][1],
        "text": " ".join(w for w, _ in words),
        "avg_logprob": logprob,
        "no_speech_prob": 0.1,
        "compression_ratio": 1.2,
        "words": timed,
    }


SPOKEN = [
    _seg(0.2, [("Hello", 0.9), ("there,", 0.8), ("camera", 0.95), ("rolling.", 0.9)]),
    _seg(4.0, [("Walking", 0.4), ("towards", 0.3), ("the", 0.5), ("forest", 0.2)], logprob=-1.4),
]


class FakeEngine:
    """Stands in for the speech model in tests (test-only; the app has no such code path)."""

    def __init__(self, segments: list[dict[str, Any]]) -> None:
        self.segments = segments
        self.calls = 0

    def __call__(self, _choice: Any, audio: Any, cfg: TranscribeConfig, *_: Any) -> dict[str, Any]:
        self.calls += 1
        assert len(audio) > 0 and cfg.beam_size == 5
        return {
            "language": "en" if self.segments else None,
            "language_probability": 0.42 if self.segments else None,
            "language_detected": True,
            "speech_s": 3.5 if self.segments else 0.0,
            "device": "cpu",
            "compute_type": "int8",
            "segments": self.segments,
        }


def _install_model(settings: Settings) -> None:
    folder = transcriber.choose_model(settings).path
    folder.mkdir(parents=True)
    for name in MODEL_FILES:
        (folder / name).write_bytes(b"test")


@pytest.fixture
def engine(api_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    fake = FakeEngine(SPOKEN)
    _install_model(api_settings)
    monkeypatch.setattr(transcriber, "transcribe", fake)
    return fake


def _import(client: TestClient, pid: str, path: Path) -> dict[str, str]:
    """Import one file; returns {"id": media id}."""
    media: Any = import_one(client, pid, path)["media"]
    return {"id": str(media["id"])}


def _transcript(client: TestClient, media_id: str) -> dict[str, Any]:
    res = client.get(f"/api/media/{media_id}/transcript")
    assert res.status_code == 200
    return res.json()


def _search(client: TestClient, pid: str, q: str, **params: str) -> list[dict[str, Any]]:
    res = client.get(f"/api/projects/{pid}/transcripts/search", params={"q": q, **params})
    assert res.status_code == 200, res.text
    return res.json()["hits"]


# --- settings and query building ---------------------------------------------------------------


def test_settings_reject_unknown_models_and_languages() -> None:
    assert TranscribeConfig(model="base", language="ta").language == "ta"
    bad: list[dict[str, Any]] = [{"model": "huge"}, {"language": "english"}, {"beam_size": 0}]
    for values in bad:
        with pytest.raises(ValueError, match="transcribe"):
            TranscribeConfig(**values)


def test_search_terms_are_data_never_fts_syntax() -> None:
    assert query_terms('  walk  "forest" ') == ["walk", "forest"]
    assert match_expression(['don"t', "NEAR(a"]) == '"don""t"* "NEAR(a"*'
    assert match_expression(query_terms('say "hi" OR x*')) == '"say"* "hi"* "OR"* "x*"*'
    assert query_terms("a\x00b\ttab") == ["a", "b", "tab"]  # control characters end a word
    for empty in ("", '  " ', "?? --", "\x00"):
        with pytest.raises(InvalidInputError):
            query_terms(empty)
    with pytest.raises(InvalidInputError, match="at most"):
        query_terms("a " * 17)


def test_uncertain_uses_the_models_own_limits() -> None:
    assert not is_uncertain(-0.9, 2.3)
    assert is_uncertain(-1.01, 1.0) and is_uncertain(-0.2, 2.5)


# --- audio decoding ------------------------------------------------------------------------------


def test_decode_audio_is_16k_mono_float(footage: Path) -> None:
    audio = transcriber.decode_audio(footage / "d_audio.wav", lambda: None)
    assert audio.dtype.name == "float32" and audio.ndim == 1
    assert len(audio) == pytest.approx(2 * transcriber.SAMPLE_RATE, rel=0.02)
    assert 0.05 < float(abs(audio).max()) <= 1.0
    with pytest.raises(UnreadableMediaError):
        transcriber.decode_audio(footage / "c_ntsc_noaudio.mkv", lambda: None)


# --- the stage, through the API ----------------------------------------------------------------


def test_transcript_with_word_timings_and_provenance(
    client: TestClient, pid: str, api_settings: Settings, footage: Path, engine: FakeEngine
) -> None:
    media = _import(client, pid, footage / "a_h264.mp4")
    drain(api_settings)
    job = client.get(f"/api/media/{media['id']}").json()
    assert job["job"]["status"] == "succeeded"
    assert (job["transcript_status"], job["transcript_language"]) == ("done", "en")

    data = _transcript(client, media["id"])
    assert data["status"] == "done" and data["message"] is None
    choice = transcriber.choose_model(api_settings)
    assert (data["model"], data["model_revision"]) == (choice.name, choice.revision)
    assert data["details"]["engine"] == transcriber.engine_version()
    assert data["details"]["settings"]["beam_size"] == 5
    assert data["language_probability"] == 0.42 and data["language_uncertain"] is True
    first, second = data["segments"]
    assert first["text"] == "Hello there, camera rolling." and not first["uncertain"]
    assert [w["word"] for w in first["words"]] == ["Hello", "there,", "camera", "rolling."]
    assert first["words"][2]["start_s"] == pytest.approx(1.2)
    assert first["confidence"] == pytest.approx((0.9 + 0.8 + 0.95 + 0.9) / 4, abs=1e-3)
    # Below the model's own acceptance limit: kept, but marked as a guess.
    assert second["uncertain"] and second["avg_logprob"] == -1.4

    summary = client.get(f"/api/projects/{pid}/transcripts").json()
    assert [(s["filename"], s["status"], s["segments"], s["words"]) for s in summary] == [
        ("a_h264.mp4", "done", 2, 8)
    ]
    stage = client.get(f"/api/jobs/{job['job']['id']}").json()["stages"][-1]
    assert (stage["name"], stage["model_name"]) == ("transcribe", "faster-whisper")
    assert stage["model_version"].startswith(transcriber.engine_version())


def test_keyword_search_finds_the_moment_a_word_is_spoken(
    client: TestClient, pid: str, api_settings: Settings, footage: Path, engine: FakeEngine
) -> None:
    media = _import(client, pid, footage / "a_h264.mp4")
    drain(api_settings)

    (hit,) = _search(client, pid, "forest")
    assert hit["media_id"] == media["id"] and hit["filename"] == "a_h264.mp4"
    assert (hit["start_s"], hit["jump_s"]) == (4.0, 5.5)  # 4th word of the segment at 4.0 s
    assert hit["parts"] == [
        {"text": "Walking towards the ", "match": False},
        {"text": "forest", "match": True},
    ]
    assert hit["uncertain"] is True
    # Start of a word, any case; all words must occur; punctuation in the transcript is ignored.
    assert _search(client, pid, "WALK")[0]["jump_s"] == 4.0
    assert _search(client, pid, "rolling camera")[0]["jump_s"] == pytest.approx(1.7)
    assert _search(client, pid, "there")[0]["jump_s"] == pytest.approx(0.7)
    assert _search(client, pid, "camera forest") == []
    assert _search(client, pid, "orest") == []
    # Operators and quotes typed by a user never reach FTS5 as syntax.
    odd_entries = ('"forest', "forest OR", "NEAR(forest", "text:forest", "forest*", "-forest")
    for odd in (*odd_entries, "forest\x00x", "for\x00est"):
        assert isinstance(_search(client, pid, odd), list)
    assert _search(client, pid, "forest", media_id="0" * 32) == []
    assert len(_search(client, pid, "forest", media_id=media["id"])) == 1
    other = client.post("/api/projects", json={"name": "other"}).json()["id"]
    assert _search(client, other, "forest") == []
    bad = client.get(f"/api/projects/{pid}/transcripts/search", params={"q": "?!"})
    assert bad.status_code == 422 and "word" in bad.json()["message"]

    # Removing the clip removes its text from the index (delete cascade -> FTS trigger).
    assert client.delete(f"/api/media/{media['id']}").status_code == 204
    assert _search(client, pid, "forest") == []
    with make_engine(api_settings.db_path).connect() as conn:
        left = conn.execute(
            text("SELECT count(*) FROM transcript_fts WHERE transcript_fts MATCH 'forest'")
        ).scalar_one()
    assert left == 0


def test_reprocessing_keeps_rows_and_other_settings_do_not_retranscribe(
    client: TestClient, pid: str, api_settings: Settings, footage: Path, engine: FakeEngine
) -> None:
    media = _import(client, pid, footage / "a_h264.mp4")
    drain(api_settings)
    before = [s["id"] for s in _transcript(client, media["id"])["segments"]]

    # A quality setting changes (the quality stages run again); the speech model is not asked.
    api_settings.quality.long_silence_s = 1.0
    api_settings.keyframes_per_shot = 2
    client.post(f"/api/media/{media['id']}/process")
    drain(api_settings)
    job = client.get(f"/api/media/{media['id']}").json()["job"]
    stages = {s["name"]: s["status"] for s in client.get(f"/api/jobs/{job['id']}").json()["stages"]}
    assert (stages["audio_qc"], stages["transcribe"]) == ("succeeded", "cached")
    assert engine.calls == 1
    assert [s["id"] for s in _transcript(client, media["id"])["segments"]] == before

    # A transcription setting changes: it runs again and the stored text is replaced.
    api_settings.transcribe.language = "en"
    engine.segments = SPOKEN[:1]
    client.post(f"/api/media/{media['id']}/process")
    drain(api_settings)
    assert engine.calls == 2
    data = _transcript(client, media["id"])
    assert len(data["segments"]) == 1 and data["details"]["settings"]["language"] == "en"
    assert _search(client, pid, "forest") == []


def test_missing_model_is_reported_and_picked_up_after_the_download(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    footage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = _import(client, pid, footage / "a_h264.mp4")
    drain(api_settings)
    item = client.get(f"/api/media/{media['id']}").json()
    # Everything else about the clip is still there.
    assert item["job"]["status"] == "succeeded" and item["quality_score"] is not None
    assert item["transcript_status"] == "model_missing"
    data = _transcript(client, media["id"])
    assert data["status"] == "model_missing" and data["segments"] == []
    assert "not downloaded" in data["message"] and "cinemind models pull" in data["message"]

    fake = FakeEngine(SPOKEN)
    monkeypatch.setattr(transcriber, "transcribe", fake)
    _install_model(api_settings)
    client.post(f"/api/media/{media['id']}/process")
    drain(api_settings)
    assert fake.calls == 1 and _transcript(client, media["id"])["status"] == "done"


def test_clips_without_audio_speech_or_a_readable_track(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    footage: Path,
    engine: FakeEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine.segments = []
    silent = _import(client, pid, footage / "c_ntsc_noaudio.mkv")
    tone = _import(client, pid, footage / "d_audio.wav")
    drain(api_settings)
    assert engine.calls == 1  # the clip without audio never reaches the model
    no_audio, no_speech = _transcript(client, silent["id"]), _transcript(client, tone["id"])
    assert (no_audio["status"], no_audio["message"]) == (
        "no_audio",
        "This clip has no audio track.",
    )
    assert no_speech["status"] == "no_speech" and no_speech["language"] is None
    assert "No speech" in no_speech["message"] and not no_speech["language_uncertain"]

    def broken(_source: Path, _check: object) -> None:
        raise UnreadableMediaError("The audio track could not be decoded for transcription.")

    monkeypatch.setattr(transcriber, "decode_audio", broken)
    clip = _import(client, pid, footage / "b_prores.mov")
    drain(api_settings)
    assert client.get(f"/api/media/{clip['id']}").json()["job"]["status"] == "succeeded"
    data = _transcript(client, clip["id"])
    assert data["status"] == "audio_unreadable" and "could not be decoded" in data["message"]

    pending = client.get(f"/api/media/{'0' * 32}/transcript")
    assert pending.status_code == 404


def test_not_yet_processed_clip_is_pending(client: TestClient, pid: str, footage: Path) -> None:
    media = _import(client, pid, footage / "a_h264.mp4")
    data = _transcript(client, media["id"])
    assert data["status"] == "pending" and "Not transcribed yet" in data["message"]
    assert client.get(f"/api/media/{media['id']}").json()["transcript_status"] is None


def test_search_in_other_scripts_and_inside_compound_words(
    client: TestClient, pid: str, api_settings: Settings, footage: Path, engine: FakeEngine
) -> None:
    engine.segments = [
        _seg(1.0, [("नमस्ते", 0.9), ("दोस्तों", 0.9)]),
        _seg(3.0, [("ಹೇಗಿದ್ದೀರಿ", 0.9), ("ಎಲ್ಲರೂ", 0.9)]),
        _seg(6.0, [("The", 0.9), ("café", 0.9), ("is", 0.9), ("well-known.", 0.9)]),
    ]
    _import(client, pid, footage / "a_h264.mp4")
    drain(api_settings)
    # Vowel signs stay inside the word: the whole word is found and highlighted, not a fragment.
    (hindi,) = _search(client, pid, "नमस्ते")
    assert hindi["parts"] == [{"text": "नमस्ते", "match": True}, {"text": " दोस्तों", "match": False}]
    assert _search(client, pid, "दोस्")[0]["jump_s"] == 1.5
    assert _search(client, pid, "ಎಲ್ಲರೂ")[0]["jump_s"] == 3.5
    # Accents are ignored and a hyphenated word is found by its second part, at the right time.
    assert _search(client, pid, "cafe")[0]["jump_s"] == 6.5
    assert _search(client, pid, "known")[0]["jump_s"] == 7.5


def test_unreadable_audio_is_tried_again(
    client: TestClient,
    pid: str,
    api_settings: Settings,
    footage: Path,
    engine: FakeEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decode = transcriber.decode_audio

    def broken(_source: Path, _check: object) -> None:
        raise UnreadableMediaError("The audio track could not be decoded for transcription.")

    monkeypatch.setattr(transcriber, "decode_audio", broken)
    media = _import(client, pid, footage / "a_h264.mp4")
    drain(api_settings)
    assert _transcript(client, media["id"])["status"] == "audio_unreadable"
    monkeypatch.setattr(transcriber, "decode_audio", decode)  # e.g. the disk is back
    client.post(f"/api/media/{media['id']}/process")
    drain(api_settings)
    assert _transcript(client, media["id"])["status"] == "done" and engine.calls == 1


# --- the engine wrapper, with a stand-in for the model object -----------------------------------


class _Word:
    def __init__(self, start: float, end: float, word: str) -> None:
        self.start, self.end, self.word, self.probability = start, end, word, 0.87654


class _Segment:
    avg_logprob, no_speech_prob, compression_ratio = -0.31234, 0.1, 1.2

    def __init__(self, start: float, end: float, text: str, words: list[_Word]) -> None:
        self.start, self.end, self.text, self.words = start, end, text, words


class _Info:
    language, language_probability, duration_after_vad = "en", 0.91239, 1.5


class _Model:
    """Returns fixed segments the way faster-whisper does; fails first if told to."""

    def __init__(self, segments: list[_Segment], fail: Exception | None = None) -> None:
        self.segments, self.fail, self.languages = segments, fail, list[str | None]()

    def transcribe(self, _audio: Any, language: str | None, **_: Any) -> Any:
        self.languages.append(language)
        if self.fail is not None:
            raise self.fail
        return iter(self.segments), _Info()


def _wrapper(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, models: dict[str, _Model], device: str
) -> transcriber.ModelChoice:
    """Route the wrapper's model loading to stand-ins, as if `device` had been detected."""
    _install_model(settings)

    def load(_path: str, wanted: str, _compute: str) -> _Model:
        return models[wanted]

    monkeypatch.setattr(transcriber, "_load", load)

    def detected(_cfg: TranscribeConfig) -> tuple[str, str]:
        return device, "int8"

    monkeypatch.setattr(transcriber, "_device", detected)
    return transcriber.choose_model(settings)


def test_wrapper_cleans_segments_clamps_times_and_reports_no_speech(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np

    audio = np.zeros(2 * transcriber.SAMPLE_RATE, dtype=np.float32)  # 2 s
    spoken = _Segment(
        0.5, 2.6, "  Hello there. ", [_Word(0.5, 0.9, " Hello"), _Word(1.0, 2.6, " there.")]
    )
    model = _Model([_Segment(0.0, 0.3, " ... ", [_Word(0.0, 0.3, " ...")]), spoken])
    choice = _wrapper(monkeypatch, settings, {"cpu": model}, "cpu")
    seen: list[float] = []
    out = transcriber.transcribe(choice, audio, settings.transcribe, seen.append, lambda: None)
    (only,) = out["segments"]  # the punctuation-only segment is dropped
    assert (only["text"], only["start"], only["end"]) == ("Hello there.", 0.5, 2.0)
    assert only["words"] == [[0.5, 0.9, "Hello", 0.8765], [1.0, 2.0, "there.", 0.8765]]
    assert (out["language"], out["language_probability"], out["device"]) == ("en", 0.9124, "cpu")
    assert model.languages == [None] and seen == [1.3]

    model.segments = [_Segment(0.0, 0.3, " ♪ ", [])]
    quiet = transcriber.transcribe(choice, audio, settings.transcribe, seen.append, lambda: None)
    assert quiet["segments"] == [] and quiet["language"] is None

    fixed = settings.transcribe.model_copy(update={"language": "ta"})
    transcriber.transcribe(choice, audio, fixed, seen.append, lambda: None)
    assert model.languages[-1] == "ta"
    model.fail = ValueError("'xx' is not a valid language code")
    with pytest.raises(InvalidInputError, match="rejected the settings"):
        transcriber.transcribe(choice, audio, fixed, seen.append, lambda: None)


def test_wrapper_falls_back_to_the_cpu_only_when_the_gpu_was_picked_automatically(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np

    audio = np.zeros(transcriber.SAMPLE_RATE, dtype=np.float32)
    good = _Model([_Segment(0.1, 0.9, "Okay.", [_Word(0.1, 0.9, " Okay.")])])
    models = {"cuda": _Model([], RuntimeError("libcudnn not found")), "cpu": good}
    choice = _wrapper(monkeypatch, settings, models, "cuda")
    out = transcriber.transcribe(choice, audio, settings.transcribe, lambda _f: None, lambda: None)
    assert (out["device"], out["compute_type"]) == ("cpu", "int8") and len(out["segments"]) == 1

    forced = settings.transcribe.model_copy(update={"device": "cuda"})
    with pytest.raises(TranscriptionError, match="failed while transcribing on cuda"):
        transcriber.transcribe(choice, audio, forced, lambda _f: None, lambda: None)


# --- doctor and CLI ----------------------------------------------------------------------------


def test_doctor_and_cli_report_the_speech_model(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = check_speech_model(settings, "lite")
    assert missing.status == "warn" and not missing.required
    assert missing.fix == "uv run cinemind models pull" and "not downloaded" in (
        missing.detail or ""
    )
    _install_model(settings.model_copy(update={"model_tier": "lite"}))
    assert check_speech_model(settings, "lite").status == "ok"

    monkeypatch.setattr("cinemind.cli.get_settings", lambda: settings)
    runner = CliRunner()
    listing = runner.invoke(cli_app, ["models", "list"])
    assert listing.exit_code == 0 and "large-v3" in listing.output
    unknown = runner.invoke(cli_app, ["models", "pull", "huge"])
    assert unknown.exit_code == 2 and "Unknown speech model" in unknown.output
    # Large downloads ask first; answering no downloads nothing.
    refused = runner.invoke(cli_app, ["models", "pull", "large-v3"], input="n\n")
    assert refused.exit_code == 1 and "3091 MB" in refused.output


# --- the real model (only when it has been downloaded) -----------------------------------------


@pytest.mark.model
def test_real_model_transcribes_synthesised_speech_and_ignores_a_tone(
    tmp_path: Path, footage: Path
) -> None:
    real = Settings()
    choice = transcriber.choose_model(real)
    if not choice.ready or shutil.which("say") is None:
        pytest.skip("needs the downloaded speech model and the macOS `say` command")
    sentence = "The quick brown fox jumps over the lazy dog near the old stone bridge."
    spoken = tmp_path / "spoken.aiff"
    subprocess.run(["say", "-o", str(spoken), sentence], check=True, timeout=60)  # noqa: S603, S607

    audio = transcriber.decode_audio(spoken, lambda: None)
    seen: list[float] = []
    result = transcriber.transcribe(choice, audio, real.transcribe, seen.append, lambda: None)
    words = [w for seg in result["segments"] for w in seg["words"]]
    heard = " ".join(str(w[2]).lower().strip(".,") for w in words)
    assert result["language"] == "en"
    for expected in ("quick", "brown", "fox", "lazy", "dog", "bridge"):
        assert expected in heard
    starts = [w[0] for w in words]
    assert starts == sorted(starts) and starts[0] >= 0 and words[-1][1] <= len(audio) / 16000
    assert seen and seen[-1] <= 1.0

    tone = transcriber.decode_audio(footage / "d_audio.wav", lambda: None)
    nothing = transcriber.transcribe(choice, tone, real.transcribe, seen.append, lambda: None)
    assert nothing["segments"] == [] and nothing["language"] is None
