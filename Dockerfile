# The app as one image: the API and, built in the first stage, the frontend it serves.
#   docker build -t dottie .
FROM node:25-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# dependencies first, so a code change does not reinstall them
COPY pyproject.toml uv.lock .python-version README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

# the app finds alembic.ini, migrations/ and frontend/dist relative to src/: keep the repository's layout
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
COPY --from=frontend /app/frontend/dist ./frontend/dist
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

RUN useradd --uid 1000 --create-home app
USER app
ENV PATH="/app/.venv/bin:$PATH" HOST=0.0.0.0 PORT=8000
EXPOSE 8000
CMD ["dottie"]
