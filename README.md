# Personal Airflow Configuration

This is my personal Airflow configuration and will be actively maintained.

**Airflow version:** 3.3.2

Runs locally with Docker Compose, SQLite, and LocalExecutor. User login is disabled;
the UI is available only on this machine at http://localhost:8080.
Run the commands below from this project directory.

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
