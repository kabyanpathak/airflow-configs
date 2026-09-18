"""Weekly slots and durable cross-task lease; stale executions do no work."""
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ai_maintenance.include.task.runtime import read_json, utcnow, write_json
from ai_maintenance.include.task.vault import validate


def eligibility(config, run_id, scheduled_at=None, now=None, controlled_review=False):
    config = validate(config)
    if type(controlled_review) is not bool:
        raise TypeError('controlled_review must be a native boolean')
    now = now or utcnow()
    local = now.astimezone(ZoneInfo('America/Los_Angeles'))
    slot = local.replace(hour=12, minute=0, second=0, microsecond=0)
    slot -= timedelta(days=(slot.weekday() + 1) % 7)
    project = Path(config['state_root']) / config['project_id']
    project.mkdir(parents=True, exist_ok=True)
    slot_key = slot.date().isoformat()
    if controlled_review:
        slot_key = 'manual-' + hashlib.sha256(run_id.encode()).hexdigest()[:16]
        prior = read_json(project / 'slots' / slot_key / 'run.json', {})
        slot = (datetime.fromisoformat(prior['soft_deadline']) - timedelta(hours=1)
                if prior else local)
    run = {'eligible': False, 'noop': True, 'run_id': run_id,
           'project_state_dir': str(project), 'state_dir': str(project / 'slots' / slot_key),
           'worktree': config['worktree'], 'slot': slot_key,
           'soft_deadline': (slot + timedelta(hours=1)).isoformat(),
           'hard_deadline': (slot + timedelta(hours=2)).isoformat()}
    if scheduled_at and not controlled_review:
        scheduled = datetime.fromisoformat(str(scheduled_at)).astimezone(slot.tzinfo)
        if abs((scheduled - slot).total_seconds()) > config['limits']['start_tolerance_minutes'] * 60:
            run['reason'] = 'stale scheduled execution'
            return run
    previous = read_json(Path(run['state_dir']) / 'run.json', {})
    retry = previous.get('run_id') == run_id
    if local < slot or local >= datetime.fromisoformat(run['hard_deadline']) or (
        not retry and local > slot + timedelta(minutes=config['limits']['start_tolerance_minutes'])
    ):
        run['reason'] = 'outside weekly start tolerance'
        return run
    lock_path = project / 'lock.json'
    # flock serializes lease replacement; the lease persists between Airflow tasks.
    import fcntl
    with (project / '.lock.guard').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        lock = read_json(lock_path, {})
        if lock and lock.get('run_id') != run_id and datetime.fromisoformat(lock['hard_deadline']) > now:
            raise RuntimeError('Another maintenance run owns this project')
        if previous.get('complete'):
            run['reason'] = 'weekly slot already completed'
            return run
        run.update(eligible=True, noop=False)
        run['config_digest'] = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        if previous and previous.get('config_digest') != run['config_digest']:
            raise ValueError('Configuration changed during this slot; use a new controlled review or weekly slot')
        write_json(lock_path, {'run_id': run_id, 'hard_deadline': run['hard_deadline']})
        write_json(Path(run['state_dir']) / 'run.json', run)
    return run
