"""Application settings. Read from the environment, never hard-coded.

The service-role database key is deliberately absent from this model: it is
used only by the seeding job (docs/12-tech-stack.md#deployment), never by the
request path, so the API process has no way to reach for it.
"""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings"]


class Settings(BaseSettings):
    """Environment configuration. See ``.env.example``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["local", "ci", "staging", "production"] = "local"
    api_version: str = "0.1.0"

    database_url: str = "postgresql+asyncpg://razormind:razormind@localhost:5432/razormind"

    # Phase 6 onward. Absent means the provider is disabled, which is a
    # supported mode, not a failure: docs/12-tech-stack.md#failure-is-a-first-class-path.
    anthropic_api_key: str | None = None
    llm_enabled: bool = False
    llm_model: str = "claude-sonnet-5"

    #: Below this, the intent parser asks rather than assumes
    #: (docs/05-agent-runtime.md#intent). Guessing a comparison period is the
    #: single easiest way to produce a confidently wrong finance answer.
    intent_confidence_threshold: Decimal = Decimal("0.75")

    intent_timeout_seconds: int = Field(default=30, ge=1)
    explain_timeout_seconds: int = Field(default=60, ge=1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings are read once per process."""
    return Settings()
