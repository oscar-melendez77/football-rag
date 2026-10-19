from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, Asset

BRONZE_RAW_FILES = Asset("bigquery://football-rag/football_bronze/raw_files")
DBT = "/opt/airflow/dbt-venv/bin/dbt"
DBT_DIR = "/opt/airflow/project/dbt"

with DAG(
    dag_id="football_transform",
    description="Rebuild and test the silver layer with dbt whenever bronze is updated",
    schedule=[BRONZE_RAW_FILES],
    start_date=pendulum.datetime(2026, 10, 16, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "oscar",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
    },
    tags=["football", "transform", "silver", "dbt"],
) as transform_dag:

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f"{DBT} build --project-dir {DBT_DIR} --profiles-dir {DBT_DIR} --target prod",
        execution_timeout=timedelta(minutes=20),
    )