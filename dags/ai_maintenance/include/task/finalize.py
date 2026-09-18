"""Always preserve handoff and release the lease; never conceal upstream failures."""
from pathlib import Path
import hashlib
import json
import logging

from ai_maintenance.include.task.runtime import read_json, write_json


def write_report(config, run, complete):
    """Bob summarizes actual results after publication; failures get an honest fallback."""
    from .run_agent import _cached, _invoke, _redact, _save, prompt_text
    state = Path(run['state_dir'])
    publication = read_json(state / 'publication.json', {})
    bob = read_json(state / 'bob_review.json', {})
    evidence = {
        'run_id': run['run_id'], 'complete': complete, 'worktree': run['worktree'],
        'reason': run.get('reason'), 'publication': publication,
        'agents': {role: read_json(state / (role + '.json'), {})
                   for role in ('dispatch', 'quinn', 'aria', 'mira', 'rowan', 'bob_review', 'alice_review')},
        'checks': read_json(state / 'validation.json', {}),
        'unfinished': {p.stem: read_json(p) for p in state.glob('*_handoff.json')},
    }
    status = 'Completed' if complete else 'Incomplete — see unfinished work and Airflow task errors'
    facts = ('# Maintenance workday report\n\n'
             + '**Status:** ' + status + '\n\n'
             + '**Run:** ' + run['run_id'] + '\n\n'
             + '**Review worktree:** `' + run['worktree'] + '`\n\n'
             + '**Applied proposals:** ' + ', '.join(publication.get('applied_proposal_ids', [])) + '\n\n'
             + '**Linear issue IDs processed:** ' + ', '.join(publication.get('linear', [])) + '\n\n')
    if run.get('noop') or not run.get('eligible'):
        body = 'No model calls were needed: ' + run.get('reason', 'Run was not eligible')
    else:
        try:
            prompt = prompt_text(config, 'bob') + (
                '\nREPORT MODE. Return exactly {"report": "Markdown text"}. Write the owner a concise '
                'end-of-day report: what each agent did, checks and limitations, actionable findings, '
                'actual applied changes, actual Linear results, unfinished work, and next steps. '
                'Distinguish proposed/approved from published. Do not invent success or new work. '
                'Use only these recorded facts:\n' + json.dumps(evidence, sort_keys=True))
            digest = hashlib.sha256(prompt.encode()).hexdigest()
            response = _cached(run, 'bob_report', digest) or _invoke(config, run, 'bob', prompt, wind_down=True)
            if not isinstance(response, dict) or set(response) != {'report'} or not isinstance(response['report'], str) or not response['report'].strip():
                raise ValueError('Bob report must contain Markdown text')
            _save(run, 'bob_report', response, config, digest)
            body = '## Bob’s workday summary\n\n' + response['report']
        except Exception:
            # Always leave readable evidence even after the hard deadline or provider failure.
            body = ('## Report fallback\n\nBob could not write a fresh end-of-day report '
                    '(deadline, missing credentials, or model failure).\n\n'
                    + '### Bob’s last saved review\n\n' + bob.get('summary', 'No Bob review completed.')
                    + '\n\n### Recorded agent work\n\n'
                    + '\n'.join('- ' + role + ': ' + report.get('summary', report.get('reason', 'No completed output'))
                                for role, report in evidence['agents'].items())
                    + '\n\n### Unfinished work\n\n'
                    + '\n'.join('- ' + name + ': ' + record.get('reason', record.get('status', 'Incomplete'))
                                for name, record in evidence['unfinished'].items()))
    path = state / 'report.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(_redact(facts + body + '\n', config or {}))
    temporary.replace(path)
    logging.getLogger(__name__).info('Maintenance report: %s', path)
    return path


def finalize(config=None, run=None, **context):
    if not isinstance(run, dict) or not run.get('eligible'):
        result = {'status': 'no-op', 'reason': (run or {}).get('reason', 'vault or eligibility failed')}
        if isinstance(run, dict) and run.get('state_dir'):
            skipped = dict(run, state_dir=str(Path(run['project_state_dir']) / 'skipped' / hashlib.sha256(run['run_id'].encode()).hexdigest()[:16]))
            result['report'] = str(write_report(config, skipped, True))
        return result
    state = Path(run['state_dir'])
    # Publication writes its completion marker only after all bounded work succeeds.
    publication = read_json(state / 'publication.json', {})
    complete = bool(run.get('noop') or publication.get('complete'))
    dag_run = context.get('dag_run')
    task_instances = getattr(dag_run, 'get_task_instances', None)
    if callable(task_instances) and any(
        getattr(task, 'state', None) in ('failed', 'upstream_failed')
        for task in task_instances()
        if getattr(task, 'task_id', '') not in ('finalize', 'end')
    ):
        complete = False
    saved = read_json(state / 'run.json', run)
    saved['complete'] = complete
    write_json(state / 'run.json', saved)
    write_json(state / 'handoff.json', {
        'complete': complete, 'base_commit': run.get('base_commit'),
        'state_dir': str(state),
        'unfinished': {p.stem: read_json(p) for p in state.glob('*_handoff.json')},
        'artifacts': sorted(p.name for p in state.glob('*.json')),
        'next_step': 'Review local worktree and report' if complete else
                     'Revalidate saved evidence on the next base; reconcile pending publication before retry',
    })
    report = write_report(config, run, complete)
    import fcntl
    project = Path(run['project_state_dir'])
    with (project / '.lock.guard').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        lock = read_json(project / 'lock.json', {})
        if lock.get('run_id') == run['run_id']:
            latest = project / 'latest_report.md'
            temporary = latest.with_suffix('.tmp')
            temporary.write_text(report.read_text())
            temporary.replace(latest)
            write_json(project / 'last_handoff.json', read_json(state / 'handoff.json'))
            if complete and run.get('base_commit'):
                write_json(project / 'last_review.json', {
                    'base_commit': run['base_commit'], 'config_digest': run['config_digest'],
                })
            (project / 'lock.json').unlink()
    return {'complete': complete, 'report': str(report)}
