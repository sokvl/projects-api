# Base for the dependency stages: Poetry and the lock file
FROM python:3.12-slim AS poetry
RUN pip install --no-cache-dir poetry==2.5.1
ENV POETRY_VIRTUALENVS_IN_PROJECT=true
WORKDIR /app
COPY pyproject.toml poetry.lock ./

# API dependencies in a local .venv
FROM poetry AS builder
RUN poetry install --only main --no-root

# Frontend dependencies (NiceGUI) in a separate .venv
FROM poetry AS ui-builder
RUN poetry install --only ui --no-root

# Frontend image, built only with `--target ui` (see compose.yaml)
FROM python:3.12-slim AS ui
RUN useradd --create-home appuser
WORKDIR /app
COPY --from=ui-builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY frontend ./frontend
RUN mkdir .nicegui && chown appuser .nicegui
USER appuser
EXPOSE 8080
CMD ["python", "frontend/ui.py"]

# API runtime image with only the .venv and the code, no Poetry. Last, so it is the default target.
FROM python:3.12-slim
RUN useradd --create-home appuser
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
