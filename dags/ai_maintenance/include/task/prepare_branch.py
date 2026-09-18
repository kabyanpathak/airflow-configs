"""Own only an explicitly registered disposable Git worktree."""
from pathlib import Path

from ai_maintenance.include.task.runtime import git, read_json, require_run, write_json


def prepare_branch(config, run):
    if not require_run(config, run):
        return run
    from ai_maintenance.include.task.source import prepare_source
    prepare_source(config, run)
    repo = config['repository']
    work = Path(config['worktree'])
    branch = config['review_branch']
    base = git(repo, 'rev-parse', '--verify', 'refs/heads/' + config['base_branch'])
    marker_path = Path(run['project_state_dir']) / 'worktree.json'
    marker = read_json(marker_path, {})
    identity = {'repository': repo, 'worktree': str(work), 'branch': branch}
    registered = git(repo, 'worktree', 'list', '--porcelain')
    if marker and any(marker.get(k) != v for k, v in identity.items()):
        raise ValueError('Worktree ownership configuration changed')
    reuse = marker.get('slot') == run['slot'] and work.exists()
    if work.exists():
        if not marker or not any(
            'worktree ' + str(work) in block.splitlines()
            and 'branch refs/heads/' + branch in block.splitlines()
            for block in registered.split('\n\n')
        ):
            raise ValueError('Refusing to modify an unowned worktree')
        if not reuse:
            git(repo, 'worktree', 'remove', '--force', str(work))
    if not reuse:
        # Existing branches are only disposable after this pipeline recorded ownership.
        branches = git(repo, 'for-each-ref', '--format=%(refname)', 'refs/heads/' + branch)
        if branches and not marker:
            raise ValueError('Refusing to reset an unowned existing branch')
        work.parent.mkdir(parents=True, exist_ok=True)
        git(repo, 'worktree', 'add', '-B', branch, str(work), base)
        write_json(marker_path, {**identity, 'slot': run['slot'], 'base_commit': base})
    else:
        base = marker['base_commit']
    run['base_commit'] = base
    last = read_json(Path(run['project_state_dir']) / 'last_review.json', {})
    findings = read_json(Path(run['project_state_dir']) / 'linear_findings.json', {})
    history = read_json(Path(run['project_state_dir']) / 'findings.json', {})
    unfinished = read_json(Path(run['project_state_dir']) / 'last_handoff.json', {}).get('complete') is False
    pending = any(read_json(path, {}).get('status') == 'pending'
                  for path in (Path(run['project_state_dir']) / 'linear_journal').glob('*.json'))
    pending = pending or any(Path(run['project_state_dir']).glob('**/*pending*.json'))
    due = any(record.get('status') != 'resolved' for record in history.values())
    due = due or any(identity not in history for identity in findings)
    run['noop'] = bool(last.get('base_commit') == base and last.get('config_digest') == run['config_digest']
                       and not due and not unfinished and not pending and not config.get('requested_task'))
    run['reason'] = 'unchanged committed content' if run['noop'] else 'review due'
    previous_commit = last.get('base_commit')
    try:
        run['changed_paths'] = git(repo, 'diff', '--name-only', previous_commit, base).splitlines() if previous_commit else git(repo, 'ls-tree', '-r', '--name-only', base).splitlines()
    except RuntimeError:
        # A rewritten/pruned source history needs a full bounded review.
        run['changed_paths'] = git(repo, 'ls-tree', '-r', '--name-only', base).splitlines()
    from ai_maintenance.include.task.validation import validate_base
    validate_base(config, run)
    write_json(Path(run['state_dir']) / 'run.json', run)
    return run
