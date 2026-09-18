"""Apply audited maintenance proposals and journal idempotent Linear publication.

Only deterministic, separately recorded base verification can authorize closure;
agent claims by themselves never constitute completed owner implementation.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone
from urllib import request

from ai_maintenance.include.task.runtime import git, require_run


def _read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.publish-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _before_deadline(run):
    deadline = datetime.fromisoformat(run['hard_deadline'].replace('Z', '+00:00'))
    if deadline.tzinfo is None:
        raise ValueError('hard_deadline must have a timezone')
    remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
    if remaining <= 0:
        raise TimeoutError('Publication hard deadline reached')
    return remaining


def _safe_target(config, root, path):
    relative = Path(path)
    if relative.is_absolute() or not relative.parts or any(p in ('.', '..', '.git') for p in relative.parts):
        raise ValueError('Unsafe proposal path')
    allowed = config.get('allowed_changes', [])
    categories = config.get('paths', {})
    scope = categories.get('documentation', []) + categories.get('backlog', [])
    if config.get('allow_test_authorship') is True:
        scope += categories.get('tests', [])
    name = relative.as_posix()
    def scoped(pattern):
        return fnmatch.fnmatchcase(name, pattern) or name.startswith(pattern.rstrip('/') + '/')
    if not any(fnmatch.fnmatchcase(name, p) for p in allowed) or not any(scoped(p) for p in scope):
        raise ValueError('Proposal outside configured maintenance scope: ' + path)
    is_test = config.get('allow_test_authorship') is True and any(scoped(p) for p in categories.get('tests', []))
    if not is_test and relative.suffix.lower() not in {'.md', '.rst', '.txt', '.adoc'}:
        raise ValueError('Production/code file changes are forbidden')
    if any(part.startswith('.env') for part in relative.parts):
        raise ValueError('Environment file changes are forbidden')
    target = root / relative
    cursor = target
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError('Symlink proposal target is forbidden')
        cursor = cursor.parent
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('Proposal escapes worktree')
    return target


def _audit_worktree(root, run, selected):
    if git(root, 'rev-parse', 'HEAD') != run['base_commit']:
        raise ValueError('Review worktree HEAD changed unexpectedly')
    paths = set(git(root, 'diff', '--no-ext-diff', '--name-only', '-z', 'HEAD').split('\0'))
    paths.update(git(root, 'ls-files', '--others', '--exclude-standard', '-z').split('\0'))
    allowed = {p['path']: (p, target) for p, target in selected}
    for path in paths - {''}:
        if path not in allowed:
            raise ValueError('Unexpected worktree modification: ' + path)
        proposal, target = allowed[path]
        if not target.is_file() or target.is_symlink() or target.read_text() != proposal['content']:
            raise ValueError('Existing worktree change differs from audited proposal: ' + path)


def _linear_worker(connection, key, query, variables, timeout):
    try:
        payload = json.dumps({'query': query, 'variables': variables}).encode()
        req = request.Request('https://api.linear.app/graphql', data=payload,
                              headers={'Authorization': key, 'Content-Type': 'application/json'})
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise ValueError('Response too large')
        result = json.loads(raw)
        if result.get('errors'):
            raise ValueError('GraphQL rejected action')
        connection.send((True, result['data']))
    except Exception:
        connection.send((False, 'Linear request failed; action remains journaled'))
    finally:
        connection.close()


class Linear:
    def __init__(self, config, run):
        self.config, self.run = config, run
        self.key = os.environ[config['api_key_env']]

    def query(self, query, variables):
        timeout = min(20, _before_deadline(self.run))
        context = multiprocessing.get_context('spawn')
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_linear_worker, args=(sender, self.key, query, variables, timeout))
        try:
            process.start()
            sender.close()
            if not receiver.poll(min(timeout, _before_deadline(self.run))):
                raise TimeoutError('Linear request cancelled at execution deadline')
            try:
                success, value = receiver.recv()
            except EOFError:
                raise RuntimeError('Linear request failed; action remains journaled') from None
            if not success:
                raise RuntimeError(value)
            return value
        finally:
            receiver.close()
            sender.close()
            if process.pid:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=0.25)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=0.25)
                process.close()

    def find(self, marker):
        # Paginate the destination team, avoiding dependence on search indexing.
        after = None
        found = []
        while True:
            data = self.query('''query($team: ID!, $after: String) {
              issues(first: 100, after: $after, filter: {team: {id: {eq: $team}}}) {
                nodes {id title description updatedAt state {id}} pageInfo {hasNextPage endCursor}
              }}''', {'team': self.config['team_id'], 'after': after})['issues']
            found.extend(issue for issue in data['nodes'] if marker in (issue.get('description') or ''))
            if len(found) > 1:
                raise ValueError('Multiple issues have the same pipeline identity')
            if not data['pageInfo']['hasNextPage']:
                return found[0] if found else None
            after = data['pageInfo']['endCursor']

    def issue(self, issue_id):
        return self.query('query($id: String!) { issue(id: $id) {id title description updatedAt state {id}} }', {'id': issue_id})['issue']

    def mutate(self, issue_id, payload):
        if issue_id:
            data = self.query('''mutation($id: String!, $input: IssueUpdateInput!) {
              issueUpdate(id: $id, input: $input) {success issue {id updatedAt state {id}}}}''',
                              {'id': issue_id, 'input': payload})['issueUpdate']
        else:
            data = self.query('''mutation($input: IssueCreateInput!) {
              issueCreate(input: $input) {success issue {id updatedAt state {id}}}}''',
                              {'input': payload})['issueCreate']
        if not data.get('success') or not data.get('issue'):
            raise RuntimeError('Linear did not confirm publication')
        return data['issue']


def _transition(finding, enrollment, verification, run, issue):
    """No transition on incomplete evidence, changed base, or human state edits."""
    if enrollment.get('human_override', False):
        return None
    if issue['state']['id'] != enrollment.get('expected_state_id'):
        return None
    if verification.get('base_commit') != run.get('base_commit') or not run.get('base_commit'):
        return None
    proof = verification.get('issues', {}).get(finding['identity'], {})
    criteria = enrollment.get('acceptance_criteria', [])
    records = proof.get('criteria', [])
    if finding.get('status') == 'resolved' and criteria and all(
        any(r.get('criterion') == criterion and r.get('verified') is True and r.get('evidence') for r in records)
        for criterion in criteria
    ):
        return enrollment.get('completed_state_id')
    if finding.get('status') == 'open' and proof.get('regression_verified') is True and proof.get('regression_evidence'):
        return enrollment.get('open_state_id')
    return None


def _reconcile_pending(client, config, run, durable, mappings, history):
    """Recover every journal, including findings omitted from a later review."""
    recovered = []
    for path in sorted((durable / 'linear_journal').glob('*.json')):
        journal = _read(path, {})
        if journal.get('status') != 'pending':
            continue
        require_run(config, run, publication=True)
        identity = journal['identity']
        mapped = mappings.get(identity, {})
        enrollment = config['linear'].get('enrolled_issues', {}).get(identity, {})
        if mapped.get('human_override') or enrollment.get('human_override'):
            mappings[identity] = dict(mapped, human_override=True)
            _save(durable / 'linear_findings.json', mappings)
            _save(path, dict(journal, status='human_override'))
            continue
        digest = hashlib.sha256((str(config['project_id']) + ':' + identity).encode()).hexdigest()
        issue_id = journal.get('issue_id') or mapped.get('issue_id')
        issue = client.issue(issue_id) if issue_id else client.find('<!-- ai-maintenance:' + digest + ' -->')
        if not issue:
            raise RuntimeError('Unresolved Linear action; reconcile pending journal before retry')
        intended = journal['payload']
        matches = all(issue['state']['id'] == value if key == 'stateId' else issue.get(key) == value
                      for key, value in intended.items() if key not in ('teamId', 'projectId'))
        if not matches:
            # Creates are never resent. Changes since the recorded precondition are human-owned.
            if not journal.get('issue_id') or issue.get('updatedAt') != journal.get('expected_updated_at'):
                mappings[identity] = dict(mapped, issue_id=issue['id'], human_override=True)
                _save(durable / 'linear_findings.json', mappings)
                _save(path, dict(journal, status='human_override'))
                continue
            if 'stateId' in intended:
                proof = journal.get('resolution_verification') or {}
                finding = history.get(identity, {}).get('finding', {'identity': identity})
                if _transition(finding, enrollment, proof, run, issue) != intended['stateId']:
                    _save(path, dict(journal, status='superseded', reason='Resolution needs verification on current base'))
                    continue
            issue = client.mutate(issue['id'], intended)
        mappings[identity] = dict(mapped, issue_id=issue['id'], updated_at=issue.get('updatedAt'), state_id=issue['state']['id'])
        _save(durable / 'linear_findings.json', mappings)
        if intended.get('stateId') and intended['stateId'] == enrollment.get('completed_state_id') and identity in history:
            history[identity]['status'] = 'resolved'
            history[identity]['resolution_verification'] = journal.get('resolution_verification')
            _save(durable / 'findings.json', history)
        _save(path, dict(journal, status='complete', issue_id=issue['id']))
        recovered.append(issue['id'])
    return recovered


def publish(config, run):
    if not isinstance(config, dict) or not isinstance(run, dict):
        raise TypeError('config and run must be native dictionaries')
    if not require_run(config, run, publication=True):
        return run
    state = Path(run['state_dir'])
    durable = Path(run['project_state_dir'])
    bob = _read(state / 'bob_review.json', {})
    alice = _read(state / 'alice_review.json', {})
    if bob.get('approved') is not True or alice.get('approved') is not True:
        raise ValueError('Both Bob and Alice must approve publication')
    approved = set(bob.get('approved_proposal_ids', [])) & set(alice.get('approved_proposal_ids', []))
    proposals = []
    for role in ('quinn', 'aria', 'mira', 'rowan'):
        proposals.extend(_read(state / (role + '.json'), {}).get('proposals', []))
    ids = [p['id'] for p in proposals]
    if len(ids) != len(set(ids)) or not approved.issubset(set(ids)):
        raise ValueError('Ambiguous or missing approved proposal IDs')
    root = Path(run['worktree'])
    selected = [(p, _safe_target(config, root, p['path'])) for p in proposals if p['id'] in approved]
    if len({str(target) for _, target in selected}) != len(selected):
        raise ValueError('Multiple approved proposals target the same file')
    _audit_worktree(root, run, selected)
    for proposal, target in selected:
        require_run(config, run, publication=True)
        _before_deadline(run)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, pending = tempfile.mkstemp(dir=target.parent, prefix='.proposal-')
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(proposal['content'])
                stream.flush()
                os.fsync(stream.fileno())
            if target.exists():
                os.chmod(pending, target.stat().st_mode & 0o777)
            _before_deadline(run)
            os.replace(pending, target)
        finally:
            if os.path.exists(pending):
                os.unlink(pending)
    _audit_worktree(root, run, selected)
    result = {'applied_proposal_ids': sorted(approved), 'linear': [], 'complete': False}
    handoffs_complete = not any(_read(p, {}).get('status') in ('unfinished', 'deferred') for p in state.glob('*_handoff.json'))
    history_path = durable / 'findings.json'
    history = _read(history_path, {})
    for finding in bob.get('findings', []):
        prior = history.get(finding['identity'], {})
        remains_verified = (prior.get('status') == 'resolved' and finding.get('status') == 'resolved'
                            and prior.get('resolution_verification', {}).get('base_commit') == run.get('base_commit'))
        history[finding['identity']] = dict(prior, finding=finding, status='resolved' if remains_verified else 'open',
                                            base_commit=run.get('base_commit'), run_id=run['run_id'])
    _save(history_path, history)
    _save(state / 'publication.json', result)
    linear = config.get('linear', {})
    if linear.get('enabled') is not True:
        result['complete'] = handoffs_complete
        _save(state / 'publication.json', result)
        return run
    client = Linear(linear, run)
    mapping_path = durable / 'linear_findings.json'
    mappings = _read(mapping_path, {})
    verification = _read(state / 'base_verification.json', {})
    result['linear'].extend(_reconcile_pending(client, config, run, durable, mappings, history))
    for finding in bob.get('findings', []):
        require_run(config, run, publication=True)
        _before_deadline(run)
        if finding.get('kind') not in ('bug', 'investigation') or not finding.get('evidence') or not finding.get('verification_steps'):
            continue
        identity = finding['identity']
        digest = hashlib.sha256((str(config['project_id']) + ':' + identity).encode()).hexdigest()
        marker = '<!-- ai-maintenance:' + digest + ' -->'
        enrollment = linear.get('enrolled_issues', {}).get(identity, {})
        mapped = mappings.get(identity, {})
        if mapped.get('human_override') or enrollment.get('human_override'):
            continue
        issue_id = enrollment.get('issue_id') or mapped.get('issue_id')
        journal_path = durable / 'linear_journal' / (digest + '.json')
        issue = client.issue(issue_id) if issue_id else client.find(marker)
        if issue_id and not issue:
            raise RuntimeError('Mapped Linear issue is unavailable; refusing replacement creation')
        if issue:
            issue_id = issue['id']
            if mapped.get('updated_at') and issue.get('updatedAt') != mapped['updated_at']:
                mappings[identity] = dict(mapped, human_override=True)
            if mapped.get('human_override') or mappings.get(identity, {}).get('human_override') or enrollment.get('human_override'):
                _save(mapping_path, mappings)
                continue
        description = '\n\n'.join([finding.get('description', ''),
            'Severity: ' + str(finding.get('severity', 'unknown')) + '; confidence: ' + str(finding.get('confidence', 'unknown')),
            'Evidence:\n' + '\n'.join(finding['evidence']),
            'Verification:\n' + '\n'.join(finding['verification_steps']), marker])
        payload = {'title': finding['title'], 'description': description}
        if issue and enrollment:
            # Enrolled development descriptions belong to the owner.
            payload = {}
            transition = _transition(finding, enrollment, verification, run, issue)
            if transition:
                payload['stateId'] = transition
            else:
                continue
        elif not issue:
            payload['teamId'] = linear['team_id']
            if linear.get('project_id'):
                payload['projectId'] = linear['project_id']
        if issue and all(issue.get(k) == v for k, v in payload.items() if k != 'stateId') and 'stateId' not in payload:
            published = issue
        else:
            _save(journal_path, {'status': 'pending', 'identity': identity, 'issue_id': issue_id, 'payload': payload, 'expected_updated_at': issue.get('updatedAt') if issue else None, 'resolution_verification': verification if 'stateId' in payload else None})
            published = client.mutate(issue_id, payload)
        if payload.get('stateId') and payload['stateId'] == enrollment.get('completed_state_id'):
            history[identity]['status'] = 'resolved'
            history[identity]['resolution_verification'] = verification
            _save(history_path, history)
        mappings[identity] = {'issue_id': published['id'], 'updated_at': published.get('updatedAt'), 'state_id': published['state']['id']}
        _save(mapping_path, mappings)
        _save(journal_path, {'status': 'complete', 'identity': identity, 'issue_id': published['id'], 'resolution_verification': verification if 'stateId' in payload else None})
        result['linear'].append(published['id'])
        _save(state / 'publication.json', result)
    result['complete'] = handoffs_complete
    _save(state / 'publication.json', result)
    return run
