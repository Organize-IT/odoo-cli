# Contributing

`AGENTS.md` is the specification: architecture, invariants and the definition
of done. Read it first — this file only covers the mechanics.

## Setup

```bash
uv sync --group dev
uvx pre-commit install     # ruff, mypy and hygiene hooks on commit
```

## The loop

```bash
uv run pytest -q                       # fast: mocked JSON-RPC, no network
uv run ruff check && uv run ruff format
uv run mypy
uv run pytest -q --cov --cov-report=term-missing
```

Against a real Odoo, which is the only way to know a field or method still
exists on a given version:

```bash
ODOO_VERSION=18.0 scripts/start-odoo.sh
ODOO_URL=http://localhost:8069 ODOO_DB=test ODOO_LOGIN=admin ODOO_API_KEY=admin \
ODOO_ALLOW_WRITES=1 uv run pytest -m integration -o addopts=""
docker compose -f docker/odoo-compose.yml down -v
```

## Pull requests

One concern per PR. The body says what changed and why, and what you ran. CI
runs the unit suite on Python 3.11–3.13 and builds the docs on every PR; the
Odoo 17/18/19 integration matrix runs on `main` and on tags.

## Releasing

1. Bump `src/odoocli/_version.py` and move the unreleased CHANGELOG entries
   under the new version.
2. Merge to `main`, wait for the integration matrix to pass.
3. Tag `vX.Y.Z` and push it. The publish workflow builds and uploads to PyPI
   through trusted publishing.
