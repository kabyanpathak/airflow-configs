# Local Airflow

Official Apache Airflow 3.3.2 in Docker Compose, using SQLite, LocalExecutor,
and no user login. No Astro CLI or Astronomer account is required.

## Run

Install Docker Desktop with Homebrew if it is not installed:

```sh
brew install --cask docker-desktop
open -a Docker
```

Complete Docker Desktop's first-run setup and wait for the engine to start.
On a fresh clone, run `cp .env.example .env` once. This working folder already
has `.env`; keep your existing secrets when editing it.

```sh
docker compose up --build -d
docker compose ps
docker compose logs -f airflow
```

Open http://localhost:8080. Everyone reaching the UI has administrator access;
the published port is bound to this computer's loopback address only.

```sh
docker compose stop                 # Stop; preserve the container and data
docker compose down                 # Remove containers; preserve the data volume
docker compose up --build -d         # Apply dependency/configuration changes
docker compose exec airflow airflow dags list-import-errors
```

`docker compose down --volumes` deletes the SQLite database, logs, and other
persisted Airflow state. Use it only when you intentionally want a fresh start.

## Layout and configuration

- `compose.yaml`: one service running `airflow standalone`, which starts the API
  server, scheduler, DAG processor, and triggerer and initializes the database.
- `Dockerfile`: official image plus your `requirements.txt` dependencies.
- `dags/`: your DAG code, mounted read-only; edits appear without image rebuilds.
- `plugins/` and `include/`: mounted read-only for plugins and supporting files.
- `.env`: ignored local environment settings and secrets, passed into the container.
- `airflow-data`: Docker-managed volume mounted at `/opt/airflow`, persisting the
  SQLite database, configuration, and logs across container recreation.

Add pinned Python packages/providers to `requirements.txt` and rebuild. For OS
packages, add an explicit `USER root` / `RUN apt-get ...` section to the Dockerfile,
then switch back to `USER airflow`. The official image does not process Astro's
`packages.txt` or `airflow_settings.yaml`.

Compose's `environment` values override matching `.env` entries. Edit the Compose
file to change those values. Task concurrency is limited to two for this small
SQLite development environment. Do not scale this service to multiple replicas.

## Authentication

`.env` selects SimpleAuthManager and sets
`AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS=True`. No user login is needed.
Airflow's internal execution API tokens still exist; they are part of task
execution, not an additional login you need to configure. Public API clients may
still need an anonymous token from SimpleAuthManager's token endpoint.

`airflow standalone` forces SimpleAuthManager. When adding your own auth manager,
replace standalone with separately launched API server, scheduler, DAG processor,
and triggerer services, configure the shared keys they need, and remove the
all-admins setting. Do this before exposing Airflow beyond your machine.

## Secrets

Keep credentials out of DAG source. Use Airflow connection IDs and resolve their
values inside tasks. For example, in the ignored `.env`:

```dotenv
AIRFLOW_CONN_MY_API={"conn_type":"http","host":"https://api.example.com","password":"replace-me"}
```

```python
from airflow.sdk import Connection, task

@task
def call_api():
    connection = Connection.get("my_api")
    # Use connection.host and connection.password with your API client.
    # Do not print or return credentials.
```

OAuth JSON files can live in `secrets/`, which Git and Docker builds ignore.
They are not automatically available inside the container: mount the needed
files explicitly and use container paths in your script configuration. A token
file that your OAuth library refreshes needs a writable mount.

For deployed environments, use an Airflow secrets backend. Keep secrets out of
logs, task return values (XCom), and rendered templates. `.gitignore` does not
encrypt files or remove previous commits; rotate any accidentally committed key.

## Moving to Kubernetes later

Use Compose for this local environment. DAG code and Python dependencies can
carry over to Kubernetes. The deployment itself needs a new configuration:

1. Replace SQLite with PostgreSQL (or another backend supported by the Helm chart).
2. Build and publish your image; deliver DAGs through the image, Git sync, or volumes.
3. Configure the official Airflow Helm chart, executor, secret injection, storage,
   logs, networking, and authentication.
4. Start a fresh metadata database or plan a separate migration of needed metadata.
   Airflow schema upgrades do not convert a SQLite database into PostgreSQL.

This is a manageable deployment migration, not a direct conversion of this
single-container setup. Kubernetes does not inherently require KubernetesExecutor;
choose the executor based on how you want tasks to run.

## References

- [Official Docker image customization](https://airflow.apache.org/docs/docker-stack/build.html)
- [SimpleAuthManager](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/auth-manager/simple/index.html)
- [Airflow Helm chart](https://airflow.apache.org/docs/helm-chart/stable/index.html)
