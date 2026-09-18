"""Host-side restart test; use only against the disposable CI Compose project."""

import os
import subprocess
import uuid


def compose(*args):
    return subprocess.run(
        ["docker", "compose", *args], check=True, text=True, capture_output=True
    ).stdout


def test_restart_preserves_database():
    assert os.environ.get("COMPOSE_PROJECT_NAME", "").startswith("airflow-ci"), (
        "Restart test requires an isolated airflow-ci* Compose project"
    )
    marker = uuid.uuid4().hex
    # A private table in the disposable SQLite database proves persistence
    # without relying on DAG runs or leaving test data in Airflow's tables.
    compose("exec", "-T", "airflow", "python", "-c", f"""
import os, sqlite3
with sqlite3.connect(os.path.join(os.environ['AIRFLOW_HOME'], 'airflow.db')) as db:
    db.execute('CREATE TABLE ci_restart_{marker} (value TEXT)')
    db.execute('INSERT INTO ci_restart_{marker} VALUES (?)', ('{marker}',))
""")
    try:
        compose("restart", "airflow")
        compose("up", "--detach", "--wait", "--wait-timeout", "300")
        compose("exec", "-T", "airflow", "python", "-c", f"""
import os, sqlite3
with sqlite3.connect(os.path.join(os.environ['AIRFLOW_HOME'], 'airflow.db')) as db:
    assert db.execute('SELECT value FROM ci_restart_{marker}').fetchone() == ('{marker}',)
""")
    finally:
        compose("exec", "-T", "airflow", "python", "-c", f"""
import os, sqlite3
with sqlite3.connect(os.path.join(os.environ['AIRFLOW_HOME'], 'airflow.db')) as db:
    db.execute('DROP TABLE IF EXISTS ci_restart_{marker}')
""")
