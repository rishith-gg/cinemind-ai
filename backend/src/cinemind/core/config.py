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

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

# <repo>/backend/src/cinemind/core/config.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[4]

ModelTier = Literal["auto", "lite", "balanced", "quality"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CINEMIND_",
        toml_file=REPO_ROOT / "cinemind.toml",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path("data")
    media_roots: list[Path] = []
    model_tier: ModelTier = "auto"

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
            TomlConfigSettingsSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
