FROM ghcr.io/astral-sh/uv:0.13.9-python3.12-trixie-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    PYTHONPATH=/app/apps/api \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY apps/api/careerreach apps/api/careerreach
RUN uv sync --locked --no-dev

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "careerreach.main:app", "--host", "0.0.0.0", "--port", "8000"]
