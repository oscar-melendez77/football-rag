import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_URL = "https://api.football-data.org/v4"
MAX_DAYS_PER_REQUEST = 10
MAX_RETRIES = 3
DAILY_DIR = Path("data/raw/matches")
BACKFILL_DIR = Path("data/raw/matches_backfill")


def ascii_safe(text):
    return str(text).encode("ascii", "replace").decode("ascii")


def load_api_key():
    load_dotenv()
    key = os.getenv("FOOTBALL_DATA_KEY")
    if not key:
        print("[ERR] FOOTBALL_DATA_KEY missing in .env")
        sys.exit(1)
    return key


def get_window(lookback, lookahead):
    today = date.today()
    date_from = today - timedelta(days=lookback)
    date_to = today + timedelta(days=lookahead)
    return date_from.isoformat(), date_to.isoformat()


def chunk_dates(date_from, date_to, max_days=MAX_DAYS_PER_REQUEST):
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    if start > end:
        raise ValueError(f"date_from {date_from} is after date_to {date_to}")
    chunks = []
    while start <= end:
        chunk_end = min(start + timedelta(days=max_days - 1), end)
        chunks.append((start.isoformat(), chunk_end.isoformat()))
        start = chunk_end + timedelta(days=1)
    return chunks


def wait_seconds_from_headers(response, default):
    reset = response.headers.get("X-RequestCounter-Reset")
    try:
        return max(int(reset), default)
    except (TypeError, ValueError):
        return default


def respect_rate_limit(response):
    remaining = response.headers.get("X-Requests-Available-Minute")
    try:
        remaining = int(remaining)
    except (TypeError, ValueError):
        return
    if remaining <= 1:
        wait = wait_seconds_from_headers(response, 60)
        print(f"[WAIT] rate limit low (remaining={remaining}), sleeping {wait}s")
        time.sleep(wait)


def fetch_matches(api_key, code, date_from, date_to):
    url = f"{BASE_URL}/competitions/{code}/matches"
    headers = {"X-Auth-Token": api_key}
    params = {"dateFrom": date_from, "dateTo": date_to}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
        except requests.RequestException as exc:
            wait = 2 ** attempt
            print(f"[RETRY] {code} attempt={attempt} network error: {ascii_safe(exc)} sleeping {wait}s")
            time.sleep(wait)
            continue

        status = response.status_code

        if status == 200:
            respect_rate_limit(response)
            return response.json()

        if status == 429 or status >= 500:
            wait = 2 ** attempt
            if status == 429:
                wait = wait_seconds_from_headers(response, wait)
            print(f"[RETRY] {code} attempt={attempt} status={status} sleeping {wait}s")
            time.sleep(wait)
            continue

        print(f"[ERR] {code} status={status} body={ascii_safe(response.text[:200])}")
        return None

    print(f"[ERR] {code} failed after {MAX_RETRIES} attempts")
    return None


def fetch_competition(api_key, code, date_from, date_to):
    matches_by_id = {}
    for chunk_from, chunk_to in chunk_dates(date_from, date_to):
        payload = fetch_matches(api_key, code, chunk_from, chunk_to)
        if payload is None:
            return None
        for match in payload.get("matches", []):
            matches_by_id[match["id"]] = match
    return sorted(matches_by_id.values(), key=lambda m: m.get("utcDate", ""))


def get_output_dir(mode, run_date, date_from, date_to):
    if mode == "backfill":
        return BACKFILL_DIR / f"window={date_from}_{date_to}"
    return DAILY_DIR / f"run_date={run_date}"


def save_raw(payload, code, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{code}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def parse_args():
    parser = argparse.ArgumentParser(description="Ingest football matches from football-data.org")
    parser.add_argument("--competitions", nargs="+", default=["PL", "PD", "CL"])
    parser.add_argument("--lookback", type=int, default=3)
    parser.add_argument("--lookahead", type=int, default=7)
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    args = parser.parse_args()
    if bool(args.date_from) != bool(args.date_to):
        parser.error("--date-from and --date-to must be used together")
    return args


def main():
    args = parse_args()
    api_key = load_api_key()
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if args.date_from:
        date_from, date_to = args.date_from, args.date_to
        mode = "backfill"
    else:
        date_from, date_to = get_window(args.lookback, args.lookahead)
        mode = "daily"

    out_dir = get_output_dir(mode, run_date, date_from, date_to)
    print(f"[INFO] mode={mode} run_date={run_date} window={date_from}..{date_to} out={out_dir}")

    total_matches = 0
    failed = 0

    for code in [c.upper() for c in args.competitions]:
        matches = fetch_competition(api_key, code, date_from, date_to)
        if matches is None:
            failed += 1
            continue

        payload = {
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mode": mode,
            "competition": code,
            "date_from": date_from,
            "date_to": date_to,
            "match_count": len(matches),
            "matches": matches,
        }
        path = save_raw(payload, code, out_dir)

        counts = Counter(m.get("status", "UNKNOWN") for m in matches)
        scheduled = counts.get("SCHEDULED", 0) + counts.get("TIMED", 0)
        print(f"[OK] {code} matches={len(matches)} finished={counts.get('FINISHED', 0)} scheduled={scheduled} -> {path}")
        total_matches += len(matches)

    print(f"[OK] run complete competitions={len(args.competitions)} total_matches={total_matches} failed={failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()