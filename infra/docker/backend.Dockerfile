FROM ghcr.io/astral-sh/uv:0.8.3-python3.12-bookworm-slim@sha256:74b8fe8ec5931f3930cfb6c87b46aeb1dbd497a609f6abf860fd0f4390f8b040 AS base

RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_HTTP_TIMEOUT=300 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY services/api/pyproject.toml ./services/api/pyproject.toml
COPY services/worker/pyproject.toml ./services/worker/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages --all-groups --no-install-workspace

FROM base AS development

COPY services ./services
COPY config ./config
# Repository-level validation modules are imported by the API acceptance tests.
# Keep them in the runtime image so `docker compose exec api pytest` exercises
# the same release checks as the host suite.
COPY scripts ./scripts

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages --all-groups

WORKDIR /app/services/api

CMD ["uvicorn", "vav.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS production

RUN groupadd --system --gid 10001 vav \
    && useradd --system --uid 10001 --gid vav --home-dir /app --shell /usr/sbin/nologin vav

COPY services ./services
COPY scripts ./scripts
COPY config ./config

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages --no-dev \
    && chown -R vav:vav /app

WORKDIR /app/services/api
USER 10001:10001
CMD ["uvicorn", "vav.main:app", "--host", "0.0.0.0", "--port", "8000"]
