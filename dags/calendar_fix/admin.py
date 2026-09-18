"""Register Airflow DAGs from every YAML file in the adjacent configs directory."""

from pathlib import Path

from dagfactory import load_yaml_dags

CONFIGS_DIR = Path(__file__).resolve().parent / "configs"

load_yaml_dags(
    globals_dict=globals(),
    dags_folder=str(CONFIGS_DIR),
)
