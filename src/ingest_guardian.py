import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_URL = "https://content.guardianapis.com/search"
PAGE_SIZE = 50
MAX_RETRIES = 3
MIN_SECONDS_BETWEEN_CALLS = 1.1
FIELDS = "headline,trailText,bodyText,byline,wordcount,shortUrl,lastModified"
DAILY_DIR = Path("data/raw/guardian")
BACKFILL_DIR = Path("data/raw/guardian_backfill")

_last_call_time = [0.0]


def ascii_safe(text):
    return str(text).encode("ascii", "replace").decode("ascii")


def load_api_key():
    load_dotenv()
    key = os.getenv("GUARDIAN_API_KEY")
    if not key:
        print("[ERR] GUARDIAN_API_KEY missing in .env")
        sys.exit(1)
    return key


def get_window(lookback):
    today = date.today()
    date_from = today - timedelta(days=lookback)
    return date_from.isoformat(), today.isoformat()


def throttle():
    elapsed = time.time() - _last_call_time[0]
    if elapsed < MIN_SECONDS_BETWEEN_CALLS:
        time.sleep(MIN_SECONDS_BETWEEN_CALLS - elapsed)
    _last_call_time[0] = time.time()


def fetch_page(api_key, section, date_from, date_to, page):
    params = {
        "api-key": api_key,
        "section": section,
        "from-date": date_from,
        "to-date": date_to,
        "page": page,
        "page-size": PAGE_SIZE,
        "order-by": "oldest",
        "show-fields": FIELDS,
        "show-tags": "keyword",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        throttle()
        try:
            response = requests.get(BASE_URL, params=params, timeout=30)
        except requests.RequestException as exc:
            wait = 2 ** attempt
            print(f"[RETRY] page={page} attempt={attempt} network error: {ascii_safe(exc)} sleeping {wait}s")
            time.sleep(wait)
            continue

        status = response.status_code

        if status == 200:
            body = response.json().get("response", {})
            if body.get("status") != "ok":
                print(f"[ERR] page={page} api status={ascii_safe(body.get('status'))} message={ascii_safe(body.get('message'))}")
                return None
            return body

        if status == 429 or status >= 500:
            wait = 2 ** attempt
            print(f"[RETRY] page={page} attempt={attempt} status={status} sleeping {wait}s")
            time.sleep(wait)
            continue

        print(f"[ERR] page={page} status={status} body={ascii_safe(response.text[:200])}")
        return None

    print(f"[ERR] page={page} failed after {MAX_RETRIES} attempts")
    return None


def fetch_all(api_key, section, date_from, date_to):
    articles_by_id = {}
    page = 1
    total_pages = 1
    total_reported = 0

    while page <= total_pages:
        body = fetch_page(api_key, section, date_from, date_to, page)
        if body is None:
            return None, 0
        total_pages = body.get("pages", 0)
        total_reported = body.get("total", 0)
        for article in body.get("results", []):
            articles_by_id[article["id"]] = article
        print(f"[INFO] page {page}/{total_pages} collected={len(articles_by_id)}")
        if total_pages == 0:
            break
        page += 1

    articles = sorted(articles_by_id.values(), key=lambda a: a.get("webPublicationDate", ""))
    return articles, total_reported


def get_output_dir(mode, run_date, date_from, date_to):
    if mode == "backfill":
        return BACKFILL_DIR / f"window={date_from}_{date_to}"
    return DAILY_DIR / f"run_date={run_date}"


def save_raw(payload, section, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{section}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def parse_args():
    parser = argparse.ArgumentParser(description="Ingest Guardian football articles")
    parser.add_argument("--section", default="football")
    parser.add_argument("--lookback", type=int, default=2)
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    args = parser.parse_args()
    if bool(args.date_from) != bool(args.date_to):
        parser.error("--date-from and --date-to must be used together")
    return args


def main():
    args = parse_args()
    api_key = load_api_key()
    run_date = date.today().isoformat()

    if args.date_from:
        date_from, date_to = args.date_from, args.date_to
        mode = "backfill"
    else:
        date_from, date_to = get_window(args.lookback)
        mode = "daily"

    out_dir = get_output_dir(mode, run_date, date_from, date_to)
    print(f"[INFO] mode={mode} run_date={run_date} section={args.section} window={date_from}..{date_to} out={out_dir}")

    articles, total_reported = fetch_all(api_key, args.section, date_from, date_to)
    if articles is None:
        print("[ERR] run failed, nothing saved")
        sys.exit(1)

    with_body = sum(1 for a in articles if a.get("fields", {}).get("bodyText"))

    payload = {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": mode,
        "source": "guardian",
        "section": args.section,
        "date_from": date_from,
        "date_to": date_to,
        "total_reported": total_reported,
        "article_count": len(articles),
        "articles": articles,
    }
    path = save_raw(payload, args.section, out_dir)

    print(f"[OK] {args.section} articles={len(articles)} reported={total_reported} with_body={with_body} -> {path}")
    if len(articles) != total_reported:
        print(f"[WARN] collected {len(articles)} but API reported {total_reported}")


if __name__ == "__main__":
    main()