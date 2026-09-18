"""Small, durable primitives shared by maintenance tasks (no Airflow imports)."""
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc)


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def git(repo, *args):
    result = subprocess.run(
        ['git', '-c', 'core.hooksPath=/dev/null', '-C', str(repo), *args],
        capture_output=True, text=True, timeout=60, check=False,
    )
    if result.returncode:
        raise RuntimeError('Git operation failed: ' + args[0])
    return result.stdout.strip()


def require_run(config, run, publication=False):
    if not isinstance(config, dict) or not isinstance(run, dict):
        raise TypeError('Native config/run dictionaries are required')
    if not run.get('eligible') or run.get('noop'):
        return False
    if utcnow() >= datetime.fromisoformat(run['hard_deadline']):
        raise TimeoutError('Maintenance hard deadline reached')
    lock = read_json(Path(run['project_state_dir']) / 'lock.json', {})
    if lock.get('run_id') != run['run_id']:
        raise RuntimeError('Project lock ownership lost')
    return True
