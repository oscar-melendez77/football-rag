from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

PROJECT_DIR = "/opt/airflow/project"
COMPETITIONS = "PL ELC PD SA BL1 FL1 DED PPL CL"
START_DATE = pendulum.datetime(2026, 10, 16, tz="UTC")

default_args = {
    "owner": "oscar",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


def upload_task(source):
    return BashOperator(
        task_id=f"upload_{source}",
        bash_command=f"python src/upload_to_gcs.py --source {source}",
        cwd=PROJECT_DIR,
        trigger_rule="all_done",
    )


with DAG(
    dag_id="football_daily",
    description="Daily ingestion of matches and Guardian articles, then upload to GCS",
    schedule="0 12 * * *",
    start_date=START_DATE,
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

    ingest_matches >> upload_task("matches")
    ingest_guardian >> upload_task("guardian")


with DAG(
    dag_id="football_rss",
    description="RSS snapshots every 3 hours, then upload to GCS",
    schedule="0 */3 * * *",
    start_date=START_DATE,
    catchup=False,
    default_args=default_args,
    tags=["football", "ingestion", "bronze"],
) as rss_dag:

    ingest_rss = BashOperator(
        task_id="ingest_rss",
        bash_command="python src/ingest_rss.py",
        cwd=PROJECT_DIR,
    )

    ingest_rss >> upload_task("rss")


with DAG(
    dag_id="football_fpl",
    description="Fantasy Premier League snapshots every 6 hours: player availability and injuries",
    schedule="15 */6 * * *",
    start_date=START_DATE,
    catchup=False,
    default_args={**default_args, "retry_delay": timedelta(minutes=20)},
    tags=["football", "ingestion", "bronze"],
) as fpl_dag:

    ingest_fpl = BashOperator(
        task_id="ingest_fpl",
        bash_command="python src/ingest_fpl.py",
        cwd=PROJECT_DIR,
    )

    ingest_fpl >> upload_task("fpl")