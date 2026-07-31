FROM ghcr.io/astral-sh/uv:0.8.3-python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY services/api/pyproject.toml ./services/api/pyproject.toml
COPY services/worker/pyproject.toml ./services/worker/pyproject.toml

RUN uv sync --frozen --all-packages --all-groups --no-install-workspace

COPY services ./services

RUN uv sync --frozen --all-packages --all-groups

WORKDIR /app/services/api

CMD ["uvicorn", "vav.main:app", "--host", "0.0.0.0", "--port", "8000"]
