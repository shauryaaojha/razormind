"""FastAPI entry point.

Pinned to a **single uvicorn worker** (docs/01-architecture.md#concurrency-and-state):
SSE subscribers and the asyncio task running an execution share process memory.
The trigger for changing that is documented in decisions.md D-12, not left to
be discovered under load.
"""

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import get_settings
from routes import agent, executions, health, provenance, reconciliation

__all__ = ["API_PREFIX", "app", "create_app"]

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(
        title="RazorMind API",
        version="0.1.0",
        description=(
            "Agentic financial computation and reconciliation. "
            "The LLM decides what to compute; deterministic code decides what the number is."
        ),
    )

    # The web app is a separate origin in every environment, including local.
    # `Last-Event-ID` has to be allowed explicitly or a dropped SSE stream
    # cannot resume: the browser sends the header and the preflight refuses it.
    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-RazorMind-User", "Last-Event-ID", "Accept"],
    )

    # /health stays at the root as well as under the prefix: container health
    # checks and load balancers look for it there, and it is the one endpoint
    # that carries no auth.
    app.include_router(health.router)

    v1 = APIRouter(prefix=API_PREFIX)
    v1.include_router(health.router)
    v1.include_router(agent.router)
    v1.include_router(reconciliation.router)
    v1.include_router(executions.router)
    v1.include_router(provenance.router)
    app.include_router(v1)
    return app


app = create_app()
