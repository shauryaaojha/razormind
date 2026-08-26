# RazorMind API.
#
# Python is pinned to a minor version on purpose (docs/12-tech-stack.md):
# `random.Random` stream semantics are only stable within a minor release, and
# the seeded fixture's checksums depend on them. A bump here is a fixture
# change, not a maintenance chore.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/apps/api/src \
    RAZORMIND_IN_CONTAINER=1

WORKDIR /app

# Dependencies are installed from pyproject.toml alone, before the source is
# copied, so an edit to a .py file does not reinstall the world.
COPY pyproject.toml ./
RUN mkdir -p apps/api/src \
    && touch apps/api/src/main.py \
    && pip install -e ".[dev]"

COPY . .

EXPOSE 8000

# Single worker, always. SSE subscribers and the asyncio task running an
# execution share process memory (docs/decisions.md D-12).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
