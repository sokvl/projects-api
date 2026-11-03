# Stage 1: install dependencies with Poetry into a local .venv
FROM python:3.12-slim AS builder
RUN pip install --no-cache-dir poetry==2.5.1
ENV POETRY_VIRTUALENVS_IN_PROJECT=true
WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root

# Stage 2: runtime image with only the .venv and the code, no Poetry
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
# Apply migrations, then replace the shell with uvicorn so it receives stop signals
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
