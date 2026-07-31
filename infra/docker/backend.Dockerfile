FROM ghcr.io/astral-sh/uv:0.8.3-python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY services ./services

RUN uv sync --frozen --all-packages --no-dev

WORKDIR /app/services/api

CMD ["uvicorn", "vav.main:app", "--host", "0.0.0.0", "--port", "8000"]

