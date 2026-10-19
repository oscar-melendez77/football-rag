from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, Asset

PROJECT_DIR = "/opt/airflow/project"
COMPETITIONS = "PL ELC PD SA BL1 FL1 DED PPL CL"
START_DATE = pendulum.datetime(2026, 10, 16, tz="UTC")
BRONZE_RAW_FILES = Asset("bigquery://football-rag/football_bronze/raw_files")

default_args = {
    "owner": "oscar",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


def upload_task(source):
    return BashOperator(
        task_id=f"upload_{source}",
        bash_command=f"python -u src/upload_to_gcs.py --source {source}",
        cwd=PROJECT_DIR,
        trigger_rule="all_done",
    )


def load_task(source):
    return BashOperator(
        task_id=f"load_{source}",
        bash_command=f"python -u src/load_bronze.py --source {source}",
        cwd=PROJECT_DIR,
        outlets=[BRONZE_RAW_FILES],
    )


def ingest_upload_load(source, ingest):
    ingest >> upload_task(source) >> load_task(source)


with DAG(
    dag_id="football_daily",
    description="Daily matches and Guardian articles: ingest, upload to GCS, load to BigQuery bronze",
    schedule="0 12 * * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["football", "ingestion", "bronze"],
) as daily_dag:

    ingest_upload_load("matches", BashOperator(
        task_id="ingest_matches",
        bash_command=f"python -u src/ingest_matches.py --competitions {COMPETITIONS} --lookback 3 --lookahead 7",
        cwd=PROJECT_DIR,
    ))

    ingest_upload_load("guardian", BashOperator(
        task_id="ingest_guardian",
        bash_command="python -u src/ingest_guardian.py --lookback 2",
        cwd=PROJECT_DIR,
    ))


with DAG(
    dag_id="football_rss",
    description="RSS snapshots every 3 hours: ingest, upload, load",
    schedule="0 */3 * * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["football", "ingestion", "bronze"],
) as rss_dag:

    ingest_upload_load("rss", BashOperator(
        task_id="ingest_rss",
        bash_command="python -u src/ingest_rss.py",
        cwd=PROJECT_DIR,
    ))


with DAG(
    dag_id="football_fpl",
    description="Fantasy Premier League snapshots every 6 hours: ingest, upload, load",
    schedule="15 */6 * * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args={**default_args, "retry_delay": timedelta(minutes=20)},
    tags=["football", "ingestion", "bronze"],
) as fpl_dag:

    ingest_upload_load("fpl", BashOperator(
        task_id="ingest_fpl",
        bash_command="python -u src/ingest_fpl.py",
        cwd=PROJECT_DIR,
    ))


with DAG(
    dag_id="football_wikipedia",
    description="Weekly Wikipedia + Wikidata snapshot: ingest, upload, load",
    schedule="30 13 * * 1",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args={**default_args, "retry_delay": timedelta(minutes=15)},
    tags=["football", "ingestion", "bronze"],
) as wikipedia_dag:

    ingest_upload_load("wikipedia", BashOperator(
        task_id="ingest_wikipedia",
        bash_command="python -u src/ingest_wikipedia.py",
        cwd=PROJECT_DIR,
        execution_timeout=timedelta(minutes=30),
    ))


with DAG(
    dag_id="football_odds",
    description="Daily match-winner odds for 6 leagues (~180 of 500 free monthly credits): ingest, upload, load",
    schedule="45 11 * * *",
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args={**default_args, "retries": 1, "retry_delay": timedelta(minutes=30)},
    tags=["football", "ingestion", "bronze"],
) as odds_dag:

    ingest_upload_load("odds", BashOperator(
        task_id="ingest_odds",
        bash_command="python -u src/ingest_odds.py",
        cwd=PROJECT_DIR,
    ))