"""FastAPI entry point.

Pinned to a **single uvicorn worker** (docs/01-architecture.md#concurrency-and-state):
SSE subscribers and the asyncio task running an execution share process memory.
The trigger for changing that is documented in decisions.md D-12, not left to
be discovered under load.
"""

from fastapi import FastAPI

from routes import health

__all__ = ["app", "create_app"]


def create_app() -> FastAPI:
    app = FastAPI(
        title="RazorMind API",
        version="0.1.0",
        description=(
            "Agentic financial computation and reconciliation. "
            "The LLM decides what to compute; deterministic code decides what the number is."
        ),
    )
    app.include_router(health.router)
    return app


app = create_app()
