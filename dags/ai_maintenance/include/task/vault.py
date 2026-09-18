"""Edit this dictionary to configure the project and each agent. Never put key values here."""
from copy import deepcopy
import re
from pathlib import Path



# Relative prompt paths are resolved from the ai_maintenance directory.
# Use actual API model IDs; the placeholders keep the DAG unconfigured/paused.
vault = {
    "project_id": "my_project",
    "repository": "/maintenance/repository",
    "base_branch": "main",
    "review_branch": "codex/ai-maintenance",
    "worktree": "/maintenance/worktrees/my_project",
    "state_root": "/opt/airflow/ai-maintenance-state",
    # Existing local Git checkout by default. Alternatives:
    # "source": {"kind": "github", "url": "https://github.com/OWNER/REPO.git"},
    # "source": {"kind": "files", "path": "/absolute/path/to/input"},
    "paths": {"documentation": ["README.md", "docs"], "backlog": ["TASKS.md"]},
    "allowed_changes": ["README.md", "docs/*.md", "TASKS.md"],
    "allow_test_authorship": False,
    "include_uncommitted": False,
    "requested_task": "",
    "validation_commands": [],
    "shared_prompt": "AI/prompts/shared.md",
    "agents": {
        "bob": {
            "provider": "openai",
            "model": "CONFIGURE_API_MODEL_ID",
            "api_key_env": "OPENAI_API_KEY",
            "prompt": "AI/prompts/bob.md",
        },
        "alice": {
            "provider": "openai",
            "model": "CONFIGURE_API_MODEL_ID",
            "api_key_env": "OPENAI_API_KEY",
            "prompt": "AI/prompts/alice.md",
        },
        "quinn": {
            "provider": "gemini",
            "model": "CONFIGURE_API_MODEL_ID",
            "api_key_env": "GEMINI_API_KEY",
            "prompt": "AI/prompts/quinn.md",
        },
        "aria": {
            "provider": "gemini",
            "model": "CONFIGURE_API_MODEL_ID",
            "api_key_env": "GEMINI_API_KEY",
            "prompt": "AI/prompts/aria.md",
        },
        "mira": {
            "provider": "gemini",
            "model": "CONFIGURE_API_MODEL_ID",
            "api_key_env": "GEMINI_API_KEY",
            "prompt": "AI/prompts/mira.md",
        },
        "rowan": {
            "provider": "gemini",
            "model": "CONFIGURE_API_MODEL_ID",
            "api_key_env": "GEMINI_API_KEY",
            "prompt": "AI/prompts/rowan.md",
        },
    },
    "linear": {
        "enabled": False,
        "api_key_env": "LINEAR_API_KEY",
        "team_id": "CONFIGURE_TEAM_ID",
        "enrolled_issues": {},
    },
    "limits": {
        "start_tolerance_minutes": 15,
        "request_timeout_seconds": 120,
        "max_output_tokens": 6000,
    },
}


def validate(config):
    if not isinstance(config, dict):
        raise TypeError('Vault configuration must be a native dictionary')
    required = {'project_id', 'repository', 'base_branch', 'worktree', 'state_root',
                'paths', 'allowed_changes', 'agents', 'linear'}
    if required - config.keys():
        raise ValueError('Missing project configuration: ' + ', '.join(sorted(required - config.keys())))
    for name in ('paths', 'agents', 'linear'):
        if not isinstance(config[name], dict):
            raise TypeError(name + ' must be a native dictionary')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', config['project_id']):
        raise ValueError('Invalid project_id')
    config.setdefault('review_branch', 'codex/ai-maintenance')
    config.setdefault('include_uncommitted', False)
    config.setdefault('allow_test_authorship', False)
    config.setdefault('requested_task', '')
    config.setdefault('limits', {})
    for key in ('include_uncommitted', 'allow_test_authorship'):
        if type(config[key]) is not bool:
            raise TypeError(key + ' must be a native boolean')
    if config['include_uncommitted']:
        raise ValueError('Uncommitted input is not supported yet; use committed base content')
    if config['base_branch'] == config['review_branch'] or not config['review_branch'].startswith('codex/'):
        raise ValueError('Review branch must be a distinct codex/ branch')
    for key in ('repository', 'worktree', 'state_root'):
        if not isinstance(config[key], str) or not Path(config[key]).is_absolute():
            raise ValueError(key + ' must be an absolute runtime path')
        config[key] = str(Path(config[key]).resolve())
    repo, work, state = (Path(config[k]) for k in ('repository', 'worktree', 'state_root'))
    if any(a == b or a in b.parents or b in a.parents for a, b in ((repo, work), (repo, state), (work, state))):
        raise ValueError('Repository, worktree and durable state must be separate non-nested directories')
    if not isinstance(config['allowed_changes'], list) or not all(
        isinstance(p, str) and not p.startswith('/') and '..' not in Path(p).parts
        and p not in ('*', '**', '**/*') for p in config['allowed_changes']
    ):
        raise ValueError('allowed_changes must contain narrow relative path patterns')
    for key in ('documentation', 'backlog', 'tests'):
        paths = config['paths'].get(key, [])
        if not isinstance(paths, list) or not all(isinstance(p, str) and not Path(p).is_absolute()
                                                 and '..' not in Path(p).parts for p in paths):
            raise TypeError('paths must contain relative path lists')
    if type(config['linear'].get('enabled', False)) is not bool:
        raise TypeError('linear.enabled must be a native boolean')
    if not isinstance(config['limits'], dict):
        raise TypeError('limits must be a native dictionary')
    for role in ('bob', 'alice', 'quinn', 'aria', 'mira', 'rowan'):
        settings = config['agents'].get(role)
        if not isinstance(settings, dict):
            raise ValueError('Missing agent configuration: ' + role)
        if settings.get('provider') not in ('openai', 'gemini'):
            raise ValueError('Agent provider must be openai or gemini')
        if not isinstance(settings.get('model'), str) or not settings['model']:
            raise ValueError('Each agent needs an API model ID')
        prompt = settings.get('prompt')
        if not isinstance(prompt, str) or not prompt:
            raise ValueError('Each agent needs a prompt path')
    for section, settings in [('linear', config['linear']), *config['agents'].items()]:
        env = settings.get('api_key_env', '')
        if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', env):
            raise ValueError(section + '.api_key_env must name an environment variable')
        if any(k in settings for k in ('api_key', 'token', 'password', 'authorization')):
            raise ValueError('Secrets must be environment references')
    for key, value in {'start_tolerance_minutes': 15, 'request_timeout_seconds': 120,
                       'max_output_tokens': 6000}.items():
        config['limits'].setdefault(key, value)
        if type(config['limits'][key]) is not int or config['limits'][key] <= 0:
            raise TypeError('Execution limits must be positive native integers')
    if config['limits']['start_tolerance_minutes'] > 60:
        raise ValueError('Start tolerance cannot extend past wind-down')
    commands = config.setdefault('validation_commands', [])
    if not isinstance(commands, list):
        raise TypeError('validation_commands must be a list')
    ids = set()
    for check in commands:
        if not isinstance(check, dict) or not isinstance(check.get('id'), str) or check['id'] in ids:
            raise ValueError('Validation checks require unique string IDs')
        argv = check.get('argv')
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise TypeError('Validation argv must be a nonempty string list; shell strings are forbidden')
        if type(check.get('timeout_seconds', 120)) is not int or check.get('timeout_seconds', 120) <= 0:
            raise TypeError('Validation timeout must be a positive integer')
        ids.add(check['id'])
    return config


def get_vault():
    """Return an independent dictionary through XCom, without resolving secrets."""
    return validate(deepcopy(vault))
