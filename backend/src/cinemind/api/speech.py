"""Spoken languages: which languages a project's footage is in (detection picks among them, and
some can be "detect only"), and the language of one clip when the user knows it. Changing either
queues the affected clips again; finished stages other than the transcript are skipped."""

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from cinemind.api.deps import SessionDep, SettingsDep
from cinemind.api.media import ERRORS, get_asset, get_project
from cinemind.core.errors import InvalidInputError
from cinemind.core.transcribe_config import SpeechLanguages, whisper_languages
from cinemind.db.models import MediaAsset
from cinemind.pipeline.importer import enqueue_ingest
from cinemind.pipeline.transcribe_stages import project_speech

router = APIRouter(tags=["transcripts"])


class SpeechLanguagesOut(SpeechLanguages):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    # Every language code the speech model knows, for the picker.
    available: list[str]
    # Clips queued again because of this change (0 when only read).
    queued: int = 0


class ClipLanguage(BaseModel):
    # A language code, or None to detect it among the project's languages.
    language: str | None


class ClipLanguageOut(ClipLanguage):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    queued: bool


def _out(speech: SpeechLanguages, queued: int = 0) -> SpeechLanguagesOut:
    return SpeechLanguagesOut(
        **speech.model_dump(), available=sorted(whisper_languages()), queued=queued
    )


@router.get(
    "/api/projects/{project_id}/speech-languages",
    response_model=SpeechLanguagesOut,
    responses=ERRORS,
    operation_id="getSpeechLanguages",
)
def get_speech_languages(project_id: str, session: SessionDep) -> SpeechLanguagesOut:
    """The languages spoken in the project's footage (empty = detect any)."""
    get_project(session, project_id)
    return _out(project_speech(session, project_id))


@router.put(
    "/api/projects/{project_id}/speech-languages",
    response_model=SpeechLanguagesOut,
    responses=ERRORS,
    operation_id="setSpeechLanguages",
)
def set_speech_languages(
    project_id: str, body: SpeechLanguages, session: SessionDep, settings: SettingsDep
) -> SpeechLanguagesOut:
    """Set the spoken languages and queue every clip again (only transcripts and what is made
    from them are redone)."""
    project = get_project(session, project_id)
    project.settings = {**project.settings, "speech": body.model_dump()}
    session.flush()
    assets = session.query(MediaAsset).filter(MediaAsset.project_id == project_id).all()
    for asset in assets:
        enqueue_ingest(session, settings, asset)
    session.commit()
    return _out(body, len(assets))


@router.put(
    "/api/media/{media_id}/speech-language",
    response_model=ClipLanguageOut,
    responses=ERRORS,
    operation_id="setClipSpeechLanguage",
)
def set_clip_speech_language(
    media_id: str, body: ClipLanguage, session: SessionDep, settings: SettingsDep
) -> ClipLanguageOut:
    """Set (or clear) the language of this clip's speech and transcribe it again."""
    asset = get_asset(session, media_id)
    if body.language is not None and body.language not in whisper_languages():
        raise InvalidInputError(f"'{body.language}' is not a language the speech model knows.")
    asset.speech_language = body.language
    session.flush()
    enqueue_ingest(session, settings, asset)
    session.commit()
    return ClipLanguageOut(language=body.language, queued=True)
