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

## Local tests

```sh
python -m pytest tests/local
```

## AI maintenance DAG

Edit **`dags/ai_maintenance/include/task/vault.py`**. Its `vault` dictionary holds
project paths, Linear settings, checks, and every agent's provider, model, prompt
path, and credential environment-variable name. There is no external JSON
configuration to create. The task returns a copy of that dictionary through XCom;
only the task making an API request resolves the credential.

For each agent, choose `provider: "openai"` or `provider: "gemini"`, and replace
`CONFIGURE_API_MODEL_ID` with an actual API model ID. Bob and Alice default to the
OpenAI provider; specialists default to Gemini. These are editable choices, not
restrictions. Put `OPENAI_API_KEY`, `GEMINI_API_KEY`, and optionally `LINEAR_API_KEY`
in `.env`. Compose explicitly injects these into the container. Provider API
credentials are required; the DAG does not use a browser subscription or login.
Relative prompt paths are resolved from the `ai_maintenance` directory.

The main outputs to read are **Linear issues** and **Bob's workday report**:

- Bob writes `state_root/project_id/latest_report.md` after publication, explaining
  agent work, checks, findings, applied proposals, Linear results, and unfinished work.
- Each run also retains its report at `state_root/project_id/slots/<slot>/report.md`.
  The final Airflow task logs and returns the report path. Mount `state_root` to a
  host directory if you want to open reports directly on your Mac.
- If Bob cannot finish before the deadline or a provider fails, the report clearly
  labels its fallback and includes his last saved review and recorded outcomes.
- Internal JSON files retain locks, evidence, and publication journals for retries
  and deduplication. These are automatic bookkeeping, not files you need to edit.

### Choose the input

| Input | Vault settings |
| --- | --- |
| Local Git checkout | Set `repository` and `base_branch`; omit `source`. Reviews committed base content. |
| Public GitHub repo | Set `source` to `{"kind": "github", "url": "https://github.com/OWNER/REPO.git"}` and `repository` to a new managed mirror directory. |
| Local file/folder | Set `source` to `{"kind": "files", "path": "/absolute/input/path"}` and `repository` to a new managed snapshot directory. Inputs are only read. |

Use separate absolute paths for `repository`, `worktree`, and `state_root`. Set
`paths.documentation`, `paths.backlog`, and narrow `allowed_changes` patterns for
the project. Copy `compose.maintenance.example.yaml` to `compose.maintenance.yaml`
and edit its mounts to match the vault. For host-side Git inspection, mount the
repository and worktree parent at identical absolute host/container paths. Add a
read-only mount for local-file inputs. Then start with:

```sh
docker compose -f compose.yaml -f compose.maintenance.yaml up -d
```

Approved documentation/status proposals stay in the disposable review worktree.
Use `git diff` there to inspect them. That worktree refreshes at the next weekly
review: copy wanted changes elsewhere first. No production implementation, pushes,
or automatic review-branch commits are enabled. File inputs use commits only in
their managed source snapshot. Models receive bounded source samples and recorded
checks; they do not execute arbitrary commands or browse the entire repository.

### Test before scheduling

The DAG starts paused. All maintenance tests live in the existing ignored local
test folder, so they remain on this machine and are not added to CI:

```sh
python -m pytest tests/local
```

Configure the project and real API model IDs, leave Linear disabled, and run a
controlled review at any time:

```sh
docker compose exec airflow airflow dags trigger ai_maintenance \
  --conf '{"controlled_review": true}'
```

Read Bob's report and inspect the worktree. Model and Linear calls have only been
mocked in automated tests; no paid live review has been performed during development.
When ready, set `linear.enabled` and `linear.team_id` in the vault (optional
`linear.project_id`) and test publication. Then enable scheduling:

```sh
docker compose exec airflow airflow dags unpause ai_maintenance
```

Weekly operation starts Sunday at noon America/Los_Angeles, rejects starts more
than 15 minutes late, and does not catch up missed weeks. New investigations stop
at 1 PM; remaining model calls and publication stop at 2 PM. A controlled review
uses fixed one-hour/two-hour deadlines from its initial start, retained on retries.
Specialists run sequentially; Rowan requires an explicit `requested_task`.

### Checks and issue handling

`validation_commands` contains only checks you configure, for example:

```python
"validation_commands": [
    {"id": "unit", "argv": ["python", "-m", "pytest", "tests"], "timeout_seconds": 120},
],
```

Checks run in a fresh checkout of the base commit, with credential variables
excluded and process-group cancellation. Use trusted checks: a worktree is not an
OS sandbox. Agent proposals cannot count as completed owner fixes.

Linear findings carry evidence, severity, confidence, and verification steps.
Durable identities and journals avoid duplicate creation, and human changes pause
automatic updates. Keep `linear.enrolled_issues` empty for basic finding publication.
Existing development issues can be enrolled explicitly with an `issue_id`,
`acceptance_criteria`, `verification_checks` mapping each criterion to a configured
check ID, `expected_state_id`, and `completed_state_id`. Without verified evidence
on the reviewed base and the expected remote state, issues remain open. A
`regression_check` must succeed only when it proves a regression before reopening
an enrolled issue using its `open_state_id`.

To retry a failed run, clear eligibility and downstream tasks within the original
deadline to reacquire the lease. Completed model outputs are reused when their
inputs remain unchanged. Ambiguous Linear actions are reconciled before retry;
unresolved creation stops rather than risking a duplicate. Cleanup preserves
upstream failures and always attempts a readable report. Email callbacks remain
deferred.
