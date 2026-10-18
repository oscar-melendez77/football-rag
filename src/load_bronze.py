import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from google.api_core import exceptions as gcp_exceptions
from google.cloud import bigquery, storage

TABLE = "football_bronze.raw_files"
BATCH_SIZE = 25
RUN_DATE_PATTERN = re.compile(r"run_date=(\d{4}-\d{2}-\d{2})")
WINDOW_PATTERN = re.compile(r"window=\d{4}-\d{2}-\d{2}_(\d{4}-\d{2}-\d{2})")


def ascii_safe(text):
    return str(text).encode("ascii", "replace").decode("ascii")


def parse_args():
    parser = argparse.ArgumentParser(description="Load raw JSON files from the lake into BigQuery bronze")
    parser.add_argument("--source", help="Lake folder under raw/, e.g. matches, guardian, rss, fpl, wikipedia, odds")
    parser.add_argument("--run-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--all", action="store_true", help="Load every file (or every file of --source), ignoring --run-date")
    args = parser.parse_args()
    if not args.all and not args.source:
        parser.error("use --source with --run-date, or --all")
    return args


def run_date_from_path(path):
    match = RUN_DATE_PATTERN.search(path) or WINDOW_PATTERN.search(path)
    return match.group(1) if match else None


def list_objects(bucket, args):
    if args.all:
        prefix = f"raw/{args.source}/" if args.source else "raw/"
    else:
        prefix = f"raw/{args.source}/run_date={args.run_date}/"
    return [b for b in bucket.list_blobs(prefix=prefix) if b.name.endswith(".json")]


def build_row(blob, loaded_at):
    parts = blob.name.split("/")
    if len(parts) < 3:
        return None, "unexpected path"
    run_date = run_date_from_path(blob.name)
    if not run_date:
        return None, "no run_date or window in path"
    try:
        payload = json.loads(blob.download_as_text(encoding="utf-8"))
    except ValueError:
        return None, "invalid JSON"
    return {
        "source": parts[1],
        "object_path": blob.name,
        "run_date": run_date,
        "loaded_at": loaded_at,
        "payload": payload,
    }, None


def delete_existing(bq, table_ref, paths):
    query = f"DELETE FROM `{table_ref}` WHERE object_path IN UNNEST(@paths)"
    config = bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter("paths", "STRING", paths)])
    job = bq.query(query, job_config=config)
    job.result()
    return job.num_dml_affected_rows or 0


def load_rows(bq, table, rows):
    config = bigquery.LoadJobConfig(
        schema=table.schema,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    job = bq.load_table_from_json(rows, table, job_config=config)
    job.result()
    return job.output_rows or 0


def main():
    load_dotenv()
    args = parse_args()
    project = os.getenv("GCP_PROJECT")
    bucket_name = os.getenv("GCS_BUCKET")
    if not project or not bucket_name:
        print("[ERR] GCP_PROJECT and GCS_BUCKET must be set")
        sys.exit(1)

    table_ref = f"{project}.{TABLE}"
    loaded_at = datetime.now(timezone.utc).isoformat()

    try:
        bq = bigquery.Client(project=project)
        table = bq.get_table(table_ref)
        bucket = storage.Client(project=project).bucket(bucket_name)
        blobs = list_objects(bucket, args)
    except gcp_exceptions.GoogleAPIError as exc:
        print(f"[ERR] setup failed: {ascii_safe(exc)}")
        sys.exit(1)

    if not blobs:
        print("[ERR] no files found for this selection")
        sys.exit(1)
    print(f"[INFO] files_found={len(blobs)} table={table_ref}")

    total_deleted = 0
    total_loaded = 0
    skipped = 0
    try:
        for i in range(0, len(blobs), BATCH_SIZE):
            rows = []
            for blob in blobs[i:i + BATCH_SIZE]:
                row, reason = build_row(blob, loaded_at)
                if row is None:
                    print(f"[SKIP] {ascii_safe(blob.name)} reason={reason}")
                    skipped += 1
                    continue
                rows.append(row)
            if not rows:
                continue
            total_deleted += delete_existing(bq, table_ref, [r["object_path"] for r in rows])
            total_loaded += load_rows(bq, table, rows)
            print(f"[INFO] batch {i // BATCH_SIZE + 1} loaded={len(rows)} running_total={total_loaded}")
    except gcp_exceptions.GoogleAPIError as exc:
        print(f"[ERR] load failed: {ascii_safe(exc)}")
        sys.exit(1)

    print(f"[OK] loaded={total_loaded} replaced={total_deleted} skipped={skipped} -> {table_ref}")
    if skipped and total_loaded == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()