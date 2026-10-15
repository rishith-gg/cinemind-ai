"""Application settings. The only place configuration is read (env vars + cinemind.toml)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from cinemind.core.embed_config import EmbedConfig, SceneConfig
from cinemind.core.face_config import FaceConfig
from cinemind.core.quality_config import QualityConfig
from cinemind.core.ranking_config import RankingConfig
from cinemind.core.rough_cut_config import RoughCutConfig
from cinemind.core.search_config import SearchConfig
from cinemind.core.transcribe_config import TranscribeConfig

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

# <repo>/backend/src/cinemind/core/config.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[4]

ModelTier = Literal["auto", "lite", "balanced", "quality"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CINEMIND_",
        toml_file=REPO_ROOT / "cinemind.toml",
        env_file=REPO_ROOT / ".env",  # machine-specific values (gitignored)
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("data")
    media_roots: list[Path] = []
    model_tier: ModelTier = "auto"
    max_job_attempts: int = 3
    max_upload_mb: int = 2048
    proxy_max_height: int = 720
    # Shot detection (PySceneDetect). threshold None = the detector's own default.
    shot_detector: Literal["adaptive", "content"] = "adaptive"
    shot_threshold: float | None = None
    shot_min_len_s: float = 0.5
    keyframes_per_shot: int = 3
    quality: QualityConfig = QualityConfig()
    transcribe: TranscribeConfig = TranscribeConfig()
    faces: FaceConfig = FaceConfig()
    embed: EmbedConfig = EmbedConfig()
    scenes: SceneConfig = SceneConfig()
    search: SearchConfig = SearchConfig()
    ranking: RankingConfig = RankingConfig()
    rough_cut: RoughCutConfig = RoughCutConfig()
    worker_poll_seconds: float = 0.5
    # Importable modules that register extra stage chains (used by tests and plugins).
    extra_stage_modules: list[str] = []

    @property
    def data_path(self) -> Path:
        """Absolute data directory (relative values resolve against the repo root)."""
        return self.data_dir if self.data_dir.is_absolute() else REPO_ROOT / self.data_dir

    @property
    def db_path(self) -> Path:
        return self.data_path / "cinemind.db"

    @property
    def models_path(self) -> Path:
        """Downloaded models (fetched once by `cinemind models pull`, never while processing)."""
        return self.data_path / "models"

    def project_dir(self, project_id: str) -> Path:
        return self.data_path / "projects" / project_id

    @field_validator("host")
    @classmethod
    def _local_only(cls, value: str) -> str:
        # Non-negotiable #7: never listen on a network interface.
        if value not in LOCAL_HOSTS:
            raise ValueError("host must be 127.0.0.1, localhost or ::1 (CineMind is local-only)")
        return value

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
