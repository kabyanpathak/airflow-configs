"""Compile committed project Python files without executing their code."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FILES = sorted(
    path
    for directory in ("dags", "plugins", "include", "tests")
    for path in (ROOT / directory).rglob("*.py")
    if not path.is_relative_to(ROOT / "tests" / "local")
)


@pytest.mark.parametrize("path", FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_python_compiles(path):
    compile(path.read_bytes(), str(path), "exec")
