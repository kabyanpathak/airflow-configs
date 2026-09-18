# Personal Airflow Configuration

This is my personal Airflow configuration and will be actively maintained.

**Airflow version:** 3.3.2

Runs locally with Docker Compose, SQLite, and LocalExecutor. User login is disabled;
the UI is available only on this machine at http://localhost:8080.

## Start

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

Build and start Airflow:

```sh
docker compose up --build -d
```

Open http://localhost:8080.

## Everyday commands

```sh
# Check container status
docker compose ps

# Follow logs (Ctrl-C exits the log viewer)
docker compose logs -f airflow

# Check DAG import errors
docker compose exec airflow airflow dags list-import-errors

# Trigger a DAG manually (replace my_dag with its ID)
docker compose exec airflow airflow dags trigger my_dag

# Apply dependency or configuration changes
docker compose up --build -d

# Stop Airflow, preserving data
docker compose stop

# Remove containers, preserving data
docker compose down
```

Add workflows to `dags/`; changes appear without rebuilding. Add Python dependencies
to `requirements.txt` and rebuild. Keep local credentials in `.env` or `secrets/`,
which are ignored by Git. Secret files require explicit mounts to be used in Docker.

SQLite, logs, and runtime configuration persist in the `airflow-data` Docker volume.
`docker compose down --volumes` deletes that data; use it only for an intentional reset.
