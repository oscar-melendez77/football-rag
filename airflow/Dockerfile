FROM apache/airflow:3.3.2

RUN pip install --no-cache-dir feedparser python-dotenv

RUN python -m venv /opt/airflow/dbt-venv \
    && /opt/airflow/dbt-venv/bin/pip install --no-cache-dir "dbt-core>=1.10,<2" "dbt-bigquery>=1.10,<2"

RUN python -m venv /opt/airflow/ml-venv \
    && /opt/airflow/ml-venv/bin/pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && /opt/airflow/ml-venv/bin/pip install --no-cache-dir sentence-transformers google-cloud-bigquery python-dotenv