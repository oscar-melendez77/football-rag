from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, Asset

BRONZE_RAW_FILES = Asset("bigquery://football-rag/football_bronze/raw_files")
DBT = "/opt/airflow/dbt-venv/bin/dbt"
DBT_DIR = "/opt/airflow/project/dbt"
ML_PYTHON = "/opt/airflow/ml-venv/bin/python"
PROJECT_DIR = "/opt/airflow/project"

with DAG(
    dag_id="football_transform",
    description="Rebuild silver and gold with dbt, then embed new articles, whenever bronze is updated",
    schedule=[BRONZE_RAW_FILES],
    start_date=pendulum.datetime(2026, 10, 16, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "oscar",
        "retries": 1,
        "retry_delay": timedelta(minutes=5),
    },
    tags=["football", "transform", "silver", "gold", "dbt", "embeddings"],
) as transform_dag:

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f"{DBT} build --project-dir {DBT_DIR} --profiles-dir {DBT_DIR} --target prod",
        execution_timeout=timedelta(minutes=20),
    )

    embed_articles = BashOperator(
        task_id="embed_articles",
        bash_command=f"{ML_PYTHON} -u src/embed_articles.py",
        cwd=PROJECT_DIR,
        execution_timeout=timedelta(minutes=60),
    )

    dbt_build >> embed_articles