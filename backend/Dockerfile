# syntax=docker/dockerfile:1

# ---------- Stage 1: build the virtual environment ----------
FROM python:3.12-slim AS builder

# Same uv version as on the dev machine, copied from its official image
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first: this layer stays cached until pyproject.toml or uv.lock change,
# so editing our code doesn't trigger a full reinstall
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Then our own code
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# ---------- Stage 2: the small image that actually runs ----------
FROM python:3.12-slim AS runtime

# Never run as root inside a container
RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/v1/health')" || exit 1

CMD ["uvicorn", "airsight.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
