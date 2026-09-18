#!/usr/bin/env bash
# Run from the repository root with tests/requirements.txt installed.
set -euo pipefail

python -m ruff check --no-cache --select E4,E7,E9,F dags plugins include tests --exclude tests/local
python -m yamllint --strict .github dags plugins include tests compose.yaml .yamllint.yaml
actionlint -shellcheck= -pyflakes= .github/workflows/*.yml
docker compose -f compose.yaml -f tests/Integration/compose.yaml config --quiet
python -m pytest -p no:cacheprovider tests/admin
