"""Materialize explicitly owned GitHub mirrors or local-file snapshots."""
import os
import re
import shutil
from pathlib import Path

from ai_maintenance.include.task.runtime import git, read_json, write_json


def _overlaps(left, right):
    return left == right or left in right.parents or right in left.parents


def _excluded(name):
    lowered = name.lower()
    return (lowered in {'.git', '.ssh', '.aws', '.azure', '.gnupg', '__pycache__',
                        'node_modules', '.venv', 'venv', 'credentials', 'credentials.json',
                        'secrets.json', 'secrets.yaml', 'secrets.yml', 'id_rsa', 'id_ed25519'}
            or lowered.startswith('.env') or lowered.endswith(('.pem', '.key', '.p12', '.pfx')))


def _copy_files(source, repository):
    if source.is_file():
        if _excluded(source.name):
            raise ValueError('Refusing to snapshot a credential file')
        shutil.copyfile(source, repository / source.name)
        return
    for current, directories, files in os.walk(source, followlinks=False):
        current = Path(current)
        directories[:] = sorted(name for name in directories
                                 if not _excluded(name) and not (current / name).is_symlink())
        destination = repository / current.relative_to(source)
        destination.mkdir(parents=True, exist_ok=True)
        for name in sorted(files):
            original = current / name
            if not _excluded(name) and not original.is_symlink() and original.is_file():
                shutil.copyfile(original, destination / name)


def prepare_source(config, run):
    """Return config after refreshing a managed source once per weekly slot.

    An absent source (or kind=git) uses the configured local Git checkout directly.
    No existing directory is adopted as a managed snapshot or mirror.
    """
    source = config.get('source')
    if source is None or (isinstance(source, dict) and source.get('kind') == 'git'):
        return config
    if not isinstance(source, dict) or source.get('kind') not in ('github', 'files'):
        raise ValueError('source.kind must be git, github, or files')
    repository = Path(config['repository'])
    marker_path = Path(run['project_state_dir']) / 'source.json'
    identity = {'kind': source['kind'], 'repository': str(repository), 'base_branch': config['base_branch']}
    if source['kind'] == 'github':
        url = source.get('url', '')
        if not isinstance(url, str) or not re.fullmatch(
            r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?/?', url
        ):
            raise ValueError('GitHub source must be an HTTPS github.com owner/repository URL without credentials')
        identity['url'] = url
    else:
        raw_path = source.get('path', '')
        if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
            raise ValueError('Local file source requires an absolute path')
        original = Path(raw_path)
        if original.is_symlink():
            raise ValueError('Local source must not be a symlink')
        original = original.resolve()
        if not original.exists() or not (original.is_file() or original.is_dir()):
            raise ValueError('Local source must be an existing file or directory')
        if any(_overlaps(original, Path(config[key]).resolve()) for key in ('repository', 'worktree', 'state_root')):
            raise ValueError('Local source must not overlap managed repository, worktree, or durable state')
        identity['path'] = str(original)
    marker = read_json(marker_path, {})
    if marker and any(marker.get(key) != value for key, value in identity.items()):
        raise ValueError('Managed source ownership configuration changed')
    if repository.is_symlink() or (repository.exists() and not marker):
        raise ValueError('Refusing to adopt an unowned source repository')
    if marker and not repository.exists():
        raise ValueError('Owned source repository is missing; inspect source state before recovery')
    if marker.get('slot') == run['slot']:
        return config
    if source['kind'] == 'github':
        if not repository.exists():
            repository.parent.mkdir(parents=True, exist_ok=True)
            git(repository.parent, 'clone', '--bare', '--single-branch', '--branch',
                config['base_branch'], identity['url'], str(repository))
        else:
            if git(repository, 'rev-parse', '--is-bare-repository') != 'true':
                raise ValueError('Managed GitHub source must remain a bare repository')
            if git(repository, 'remote', 'get-url', 'origin') != identity['url']:
                raise ValueError('Managed source remote changed')
            git(repository, 'fetch', '--no-tags', 'origin',
                '+' + config['base_branch'] + ':refs/heads/' + config['base_branch'])
    else:
        if not repository.exists():
            repository.mkdir(parents=True)
            git(repository, 'init', '-b', config['base_branch'])
        elif git(repository, 'branch', '--show-current') != config['base_branch']:
            raise ValueError('Managed file source branch changed')
        # Only this explicit managed repository is disposable; never the input path.
        for child in repository.iterdir():
            if child.name == '.git':
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        _copy_files(original, repository)
        git(repository, 'add', '--all')
        if not marker or git(repository, 'status', '--porcelain'):
            git(repository, '-c', 'user.name=AI Maintenance Snapshot', '-c',
                'user.email=ai-maintenance@localhost', '-c', 'commit.gpgSign=false',
                'commit', '--allow-empty', '-m', 'Snapshot configured local source')
    write_json(marker_path, {**identity, 'slot': run['slot']})
    return config
