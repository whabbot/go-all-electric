FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN VITE_USE_MOCKS=false npm run build

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS backend
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
COPY backend/src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home app
WORKDIR /app
COPY --from=backend /app/.venv /app/.venv
COPY --from=frontend /build/dist /app/.venv/lib/python3.14/site-packages/gae/static
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PORT=8080
USER app
EXPOSE 8080
CMD ["python", "-m", "gae.server"]
