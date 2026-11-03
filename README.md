# Projects API

## Run locally

```bash
docker compose up --build
```

The API is available at http://localhost:8000 (`GET /health`, docs at `/docs`).

## Development

```bash
poetry install
poetry run pre-commit install   # ruff and mypy run on every commit
```

Run the checks by hand:

```bash
poetry run ruff check .
poetry run ruff format .
poetry run mypy app tests
```
