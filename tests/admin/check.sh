#!/usr/bin/env bash
# Run from the repository root. CI uses an isolated Compose project.
set -euo pipefail

docker compose build
docker compose run --rm --no-deps \
  --volume "$PWD:/workspace:ro" --workdir /workspace \
  --entrypoint bash airflow -euc '
    pip install --no-cache-dir -r tests/requirements.txt
    ruff check --no-cache --select E4,E7,E9,F dags plugins include tests --exclude tests/local
    python -m pytest -p no:cacheprovider tests/admin
  '

# The Compose healthcheck verifies the database, scheduler, DAG processor,
# and triggerer through the running API server.
docker compose up --detach --wait --wait-timeout 300
