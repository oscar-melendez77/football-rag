from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

PROJECT_DIR = "/opt/airflow/project"
COMPETITIONS = "PL ELC PD SA BL1 FL1 DED PPL CL"

default_args = {
    "owner": "oscar",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="football_daily",
    description="Daily ingestion of matches and Guardian articles",
    schedule="0 12 * * *",
    start_date=pendulum.datetime(2026, 10, 16, tz="UTC"),
    catchup=False,
    default_args=default_args,
    tags=["football", "ingestion", "bronze"],
) as daily_dag:

    ingest_matches = BashOperator(
        task_id="ingest_matches",
        bash_command=f"python src/ingest_matches.py --competitions {COMPETITIONS} --lookback 3 --lookahead 7",
        cwd=PROJECT_DIR,
    )

    ingest_guardian = BashOperator(
        task_id="ingest_guardian",
        bash_command="python src/ingest_guardian.py --lookback 2",
        cwd=PROJECT_DIR,
    )


with DAG(
    dag_id="football_rss",
    description="RSS snapshots every 3 hours",
    schedule="0 */3 * * *",
    start_date=pendulum.datetime(2026, 10, 16, tz="UTC"),
    catchup=False,
    default_args=default_args,
    tags=["football", "ingestion", "bronze"],
) as rss_dag:

    ingest_rss = BashOperator(
        task_id="ingest_rss",
        bash_command="python src/ingest_rss.py",
        cwd=PROJECT_DIR,
    )