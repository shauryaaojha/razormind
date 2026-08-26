"""FastAPI entry point.

Pinned to a **single uvicorn worker** (docs/01-architecture.md#concurrency-and-state):
SSE subscribers and the asyncio task running an execution share process memory.
The trigger for changing that is documented in decisions.md D-12, not left to
be discovered under load.
"""

from fastapi import APIRouter, FastAPI

from routes import health, reconciliation

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

    # /health stays at the root as well as under the prefix: container health
    # checks and load balancers look for it there, and it is the one endpoint
    # that carries no auth.
    app.include_router(health.router)

    v1 = APIRouter(prefix=API_PREFIX)
    v1.include_router(health.router)
    v1.include_router(reconciliation.router)
    app.include_router(v1)
    return app


app = create_app()
