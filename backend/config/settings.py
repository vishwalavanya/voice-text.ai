from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    APP_NAME: str = "Realtime Multilingual Voice AI Agent"
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    SAMBANOVA_API_KEY: str = Field(default="")
    DEEPGRAM_API_KEY: str = Field(default="")
    REDIS_URL: str = Field(default="")
    DATABASE_URL: str = Field(default="")

    SAMBANOVA_BASE_URL: str = "https://api.sambanova.ai/v1"
    SAMBANOVA_MODEL: str = "Meta-Llama-3.3-70B-Instruct"

    DEEPGRAM_STT_MODEL: str = "flux-general-en"
    DEEPGRAM_TTS_MODEL: str = "aura-2-thalia-en"
    AUDIO_ENCODING: str = "linear16"
    AUDIO_SAMPLE_RATE: int = 16000

    REDIS_TTL_SECONDS: int = 3600
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    SQL_ECHO: bool = False

    CORS_ORIGINS: list[str] = ["*"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> list[str]:
        if isinstance(value, str):
            if value.strip() == "*":
                return ["*"]
            return [v.strip() for v in value.split(",") if v.strip()]
        if isinstance(value, list):
            return [str(v) for v in value]
        return ["*"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

