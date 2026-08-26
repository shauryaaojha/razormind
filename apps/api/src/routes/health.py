"""Liveness. The only endpoint that exists in Phase 0."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from config.settings import Settings, get_settings

__all__ = ["Health", "router"]

router = APIRouter(tags=["health"])


class Health(BaseModel):
    """Process liveness. Says nothing about the database on purpose."""

    status: Literal["ok"]
    version: str
    environment: str


@router.get("/health")
async def health() -> Health:
    settings: Settings = get_settings()
    return Health(
        status="ok",
        version=settings.api_version,
        environment=settings.environment,
    )
