# Personal Airflow Configuration

This is my personal Airflow configuration and will be actively maintained.


**Airflow version:** 3.3.2

Runs locally with Docker Compose, SQLite, and LocalExecutor. User login is disabled;
the UI is available only on this machine at http://localhost:8080.
Run the commands below from this project directory.

## Key
- U : update (continual work on something)
- Up : upgrade 
- A : add (adding something new)
- R : refactor


## Initial setup

Install and open Docker Desktop:

```sh
brew install --cask docker-desktop
open -a Docker
```

Complete Docker Desktop setup and wait for the engine to start. On a fresh clone,
create your local environment file (skip this if `.env` already exists):

```sh
cp .env.example .env
```

## Starting, stopping, and restarting

```sh
# First start: build the image and run in the background
docker compose up --build -d

# Start Airflow again
docker compose up -d

# Stop Airflow, preserving containers and data
docker compose stop

# Restart with the existing configuration
docker compose restart

# Stop and remove containers, preserving the data volume
docker compose down
```

Open http://localhost:8080 after startup. These commands manage the entire
standalone environment, including the scheduler, API server, DAG processor,
and triggerer.

## Applying changes

```sh
# Apply changes to .env or compose.yaml
docker compose up -d

# Rebuild after changing requirements.txt or Dockerfile
docker compose up --build -d
```

`docker compose restart` does not apply changed environment settings.
Add workflows to `dags/`; DAG edits are picked up without rebuilding.
Add pinned Python dependencies to `requirements.txt` and rebuild.

## Status, logs, and container access

```sh
# Check container status and health
docker compose ps

# Follow logs (Ctrl-C exits the viewer, not Airflow)
docker compose logs -f airflow

# Show the most recent 100 log lines
docker compose logs --tail=100 airflow

# Open a shell inside the running container
docker compose exec airflow bash

# Check the installed Airflow version
docker compose exec airflow airflow version
```

## Manual DAG operations

These commands require the Airflow container to be running. Replace `my_dag`
with your DAG ID, which may differ from the Python or YAML filename.

```sh
# List registered DAGs
docker compose exec airflow airflow dags list

# Check DAG import errors
docker compose exec airflow airflow dags list-import-errors

# Unpause a DAG
docker compose exec airflow airflow dags unpause my_dag

# Trigger a run manually
docker compose exec airflow airflow dags trigger my_dag

# Pause future scheduling (does not cancel running tasks)
docker compose exec airflow airflow dags pause my_dag

# List tasks in a DAG
docker compose exec airflow airflow tasks list my_dag
```

DAG Factory loads YAML definitions from `dags/calendar_fix/configs/` through
`dags/calendar_fix/admin.py`. Loading a definition registers it; triggering or
scheduling the DAG executes its tasks.

## Starting individual Airflow components manually

Normally, `standalone` starts all components automatically. Use these commands
only to debug individual components after the environment has been initialized.
Do not start an extra scheduler alongside the running standalone container.

First stop the normal environment:

```sh
docker compose stop
```

Then run the component you want to inspect in the foreground:

```sh
# Scheduler
docker compose run --rm --no-deps airflow scheduler

# API server and UI (publish the configured localhost port)
docker compose run --rm --no-deps --service-ports airflow api-server

# DAG processor
docker compose run --rm --no-deps airflow dag-processor

# Triggerer
docker compose run --rm --no-deps airflow triggerer
```

Each command starts a temporary container using the same image, environment,
and data volume. A single component is not a complete Airflow environment.
Ctrl-C stops the foreground component and `--rm` removes its temporary container.
Stop any manually launched components before returning to normal operation:

```sh
docker compose up -d
```

## Local secrets and stored data

Keep local credentials in `.env` or `secrets/`, which are ignored by Git.
Secret files require explicit mounts to be used inside Docker.

SQLite, logs, and runtime configuration persist in the `airflow-data` Docker
volume through stops, restarts, and container recreation.

For an intentional reset only, the following deletes that stored data:

```sh
docker compose down --volumes
```

## GitHub Actions CI

`.github/workflows/ci.yml` runs admin checks on every branch push: lint Python
with Ruff, compile Python files, lint YAML (including duplicate keys), validate
GitHub Actions with actionlint, and validate Docker Compose configuration.
Pull requests targeting
`master`, pushes to `master` (including merges), and manual workflow runs
additionally build and launch Airflow through `tests/Integration/check.sh`, wait
for its component healthcheck to pass, and run all committed test suites.
Other branch pushes run admin only, without building or starting Docker.
To block merges when validation fails, configure GitHub branch protection for
`master` to require the `tests` status check. Deployment is not configured.

```text
tests/
  local/         # Private experiments; only .gitkeep is committed
  admin/         # Python, YAML, workflow, and Compose checks
  Unit/          # Isolated function tests
  Integration/   # Build, startup, dependencies, providers, restart persistence
  E2E/           # Browser UI rendering and navigation
```

Unit remains a placeholder until shared helper logic exists. Tests do not execute
individual DAGs or check their business behavior; keep those experiments in local.
The integration suite builds and starts Airflow, checks dependency compatibility
and package/provider imports, restarts the service, waits for healthy components,
and verifies a temporary SQLite marker survives. The marker is removed afterward.
The browser test opens the DAG list (including an empty list), navigates Home,
and checks for JavaScript exceptions and failing same-origin HTTP responses.

Full runs use an isolated `airflow-ci` Compose project and the test override in
`tests/Integration/compose.yaml`: example environment settings and a random
localhost port, without reading local `.env` credentials. Runtime Python tests
run inside the image; restart and Chromium tests run on the host. No login is
required under the current example configuration; update E2E when auth changes.

Git tracks files, not empty directories. `tests/local/.gitkeep` preserves the
directory in fresh clones while its other contents, including subdirectories,
are ignored. Ignored files stay on your machine during normal branch switches,
but destructive cleanup such as `git clean -fdx` can remove them. GitHub runners
cannot run tests that were never committed. Gitignore also does not untrack files
that were already committed.

Run local experiments yourself in a Python environment with the project and test
dependencies installed:

```sh
python -m pytest tests/local
```

Promote a local test by moving it to Unit, Integration, or E2E and committing it:

```sh
mv tests/local/test_example.py tests/Unit/test_example.py
git add tests/Unit/test_example.py
```

To reproduce admin checks locally, install `tests/requirements.txt` in your
Python environment, install actionlint (`go install
github.com/rhysd/actionlint/cmd/actionlint@v1.7.12`), and make sure it is on PATH.
Run `bash tests/admin/check.sh`. Docker Compose is required for configuration
validation, but the Docker engine does not need to be running.

For integration/E2E, start Docker and use a disposable project:

```sh
export COMPOSE_PROJECT_NAME=airflow-ci-local
export COMPOSE_FILE=compose.yaml:tests/Integration/compose.yaml
bash tests/Integration/check.sh
docker compose exec -T airflow python -m pip check
docker compose run --rm --no-deps \
  --volume "$PWD:/workspace:ro" --workdir /workspace \
  --entrypoint bash airflow -euc '
    pip install -r tests/requirements.txt
    python -m pytest -p no:cacheprovider tests/admin tests/Unit tests/Integration --ignore=tests/Integration/test_restart.py
  '
python -m pytest tests/Integration/test_restart.py
python -m pip install -r tests/E2E/requirements.txt
python -m playwright install chromium
export AIRFLOW_TEST_URL="http://$(docker compose port airflow 8080)"
python -m pytest tests/E2E
# Remove only this disposable project's containers and data afterward.
docker compose down --volumes --remove-orphans
unset COMPOSE_PROJECT_NAME COMPOSE_FILE AIRFLOW_TEST_URL
```

GitHub CI performs cleanup automatically after each full run.
