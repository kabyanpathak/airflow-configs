FROM apache/airflow:3.3.2

# Keep Airflow pinned when installing your own Python dependencies.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" -r /tmp/requirements.txt
