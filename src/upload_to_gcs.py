import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from google.api_core import exceptions as gcp_exceptions
from google.cloud import storage

DATA_ROOT = Path("data")
SOURCES = {
    "matches": DATA_ROOT / "raw" / "matches",
    "guardian": DATA_ROOT / "raw" / "guardian",
    "fpl": DATA_ROOT / "raw" / "fpl",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Upload one day of bronze files to GCS")
    parser.add_argument("--source", required=True, choices=sorted(SOURCES))
    parser.add_argument("--run-date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    return parser.parse_args()


def main():
    args = parse_args()

    bucket_name = os.getenv("GCS_BUCKET")
    if not bucket_name:
        print("[ERR] GCS_BUCKET is not set")
        sys.exit(1)

    local_dir = SOURCES[args.source] / f"run_date={args.run_date}"
    if not local_dir.exists():
        print(f"[ERR] nothing to upload, folder not found: {local_dir}")
        sys.exit(1)

    files = sorted(local_dir.rglob("*.json"))
    if not files:
        print(f"[ERR] folder exists but has no json files: {local_dir}")
        sys.exit(1)

    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        total_bytes = 0
        for path in files:
            object_name = path.relative_to(DATA_ROOT).as_posix()
            blob = bucket.blob(object_name)
            blob.upload_from_filename(str(path), content_type="application/json")
            total_bytes += path.stat().st_size
    except gcp_exceptions.GoogleAPIError as exc:
        print(f"[ERR] upload failed: {str(exc).encode('ascii', 'replace').decode()}")
        sys.exit(1)

    print(f"[OK] source={args.source} run_date={args.run_date} files={len(files)} bytes={total_bytes} -> gs://{bucket_name}/raw/{args.source}/run_date={args.run_date}/")


if __name__ == "__main__":
    main()