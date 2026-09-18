#!/usr/bin/env bash
# Run from the repository root with Docker running and .env prepared.
set -euo pipefail

docker compose build

# Verify the database, scheduler, DAG processor, and triggerer through the
# running API server using the Compose healthcheck.
docker compose up --detach --wait --wait-timeout 300
