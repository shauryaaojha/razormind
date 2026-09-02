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
    llm_enabled: bool = False

    #: Which vendor sits behind ``llm/provider.py``. Named explicitly rather
    #: than inferred from whichever key happens to be present: two keys in one
    #: environment would otherwise pick a model by accident, and "which model
    #: answered" is a question a finance audit is entitled to a firm answer to
    #: (D-57).
    llm_provider: Literal["anthropic", "groq", "gemini"] = "anthropic"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"

    #: Groq serves open-weight models on a free tier. The largest one that
    #: supports a forced tool call, because the smaller ones degrade on the
    #: explainer, and the way they degrade is a claim whose prose rounds a
    #: figure its own structured field got right -- which the grounding gate
    #: catches, but only by discarding the answer (D-57).
    #:
    #: Groq's catalogue moves. `GET /openai/v1/models` on your own key is the
    #: only authority on what it currently holds; a retired model is a 404 at
    #: request time, not a startup failure.
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"

    #: Gemini is the free tier that actually fits: a million-token context
    #: rather than Groq's eight thousand tokens a minute, which is what decides
    #: whether the explainer's evidence brief can be sent at all (D-58).
    #:
    #: `-lite` rather than `gemini-flash-latest` because on the free tier the
    #: larger model answers 503 far more often than it answers, and its thinking
    #: budget is spent before the forced call is emitted. A model that returns
    #: an answer beats a better model that returns a capacity error.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-flash-lite-latest"

    #: Below this, the intent parser asks rather than assumes
    #: (docs/05-agent-runtime.md#intent). Guessing a comparison period is the
    #: single easiest way to produce a confidently wrong finance answer.
    intent_confidence_threshold: Decimal = Decimal("0.75")

    intent_timeout_seconds: int = Field(default=30, ge=1)
    explain_timeout_seconds: int = Field(default=60, ge=1)

    #: Browser origins allowed to call the API. A list rather than ``*``: the
    #: caller identity travels in a header, and a wildcard origin on an endpoint
    #: that reads one is an invitation to every other page the user has open.
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings are read once per process."""
    return Settings()
