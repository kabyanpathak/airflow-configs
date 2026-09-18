"""Register the paused weekly Airflow maintenance DAG with DAG Factory."""
from pathlib import Path
import sys

from dagfactory import load_yaml_dags

# Airflow 3 bundle parsers do not always add the bundle root to sys.path.
DAGS_ROOT = str(Path(__file__).resolve().parent.parent)
if DAGS_ROOT not in sys.path:
    sys.path.insert(0, DAGS_ROOT)
load_yaml_dags(globals_dict=globals(), dags_folder=str(Path(__file__).parent / 'Configs'))
if 'ai_maintenance' not in globals():
    raise RuntimeError('DAG Factory did not register ai_maintenance; inspect YAML errors above')
