"""Check the installed runtime without executing any project DAGs."""

import importlib
import subprocess
import sys

import pytest


def test_dependency_versions_are_compatible():
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True)


@pytest.mark.parametrize("module", ["airflow", "dagfactory"])
def test_core_packages_import(module):
    importlib.import_module(module)


def test_installed_providers_load():
    from airflow.providers_manager import ProvidersManager

    # Airflow discovers the providers installed by the image/requirements.txt.
    providers = ProvidersManager().providers
    assert providers, "No Airflow providers were discovered"
    for distribution in providers:
        namespace = distribution.removeprefix("apache-airflow-providers-")
        importlib.import_module("airflow.providers." + namespace.replace("-", "."))
