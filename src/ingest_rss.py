import argparse
import calendar
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

CONFIG_PATH = Path("config/rss_feeds.json")
RAW_DIR = Path("data/raw/rss")
MAX_RETRIES = 3
TIMEOUT = 30
USER_AGENT = "football-rag/0.1 (portfolio project; RSS reader)"


def ascii_safe(text):
    return str(text).encode("ascii", "replace").decode("ascii")


def load_feeds(path):
    if not path.exists():
        print(f"[ERR] feed config not found: {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        feeds = json.load(f)
    names = [feed["name"] for feed in feeds]
    if len(names) != len(set(names)):
        print("[ERR] duplicate feed names in config")
        sys.exit(1)
    return feeds


def download_feed(url):
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            wait = 2 ** attempt
            print(f"[RETRY] attempt={attempt} network error: {ascii_safe(exc)} sleeping {wait}s")
            time.sleep(wait)
            continue

        status = response.status_code
        if status == 200:
            return response.content
        if status == 429 or status >= 500:
            wait = 2 ** attempt
            print(f"[RETRY] attempt={attempt} status={status} sleeping {wait}s")
            time.sleep(wait)
            continue

        print(f"[ERR] status={status} url={url}")
        return None

    print(f"[ERR] failed after {MAX_RETRIES} attempts url={url}")
    return None


def struct_to_iso(struct_time):
    if not struct_time:
        return None
    return datetime.fromtimestamp(calendar.timegm(struct_time), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_entries(content):
    parsed = feedparser.parse(content)
    entries = []
    for e in parsed.entries:
        entries.append({
            "id": e.get("id") or e.get("link"),
            "title": e.get("title"),
            "link": e.get("link"),
            "summary": e.get("summary"),
            "published": struct_to_iso(e.get("published_parsed")),
            "updated": struct_to_iso(e.get("updated_parsed")),
            "author": e.get("author"),
            "tags": [t.get("term") for t in e.get("tags", []) if t.get("term")],
        })
    feed_title = parsed.feed.get("title")
    bozo_reason = ascii_safe(parsed.get("bozo_exception")) if parsed.get("bozo") else None
    return feed_title, entries, bozo_reason


def save_raw(payload, feed_name, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{feed_name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def parse_args():
    parser = argparse.ArgumentParser(description="Snapshot football RSS feeds")
    parser.add_argument("--feeds", nargs="+", help="Only run these feed names")
    return parser.parse_args()


def main():
    args = parse_args()
    feeds = load_feeds(CONFIG_PATH)
    if args.feeds:
        feeds = [f for f in feeds if f["name"] in args.feeds]

    now = datetime.now(timezone.utc)
    run_date = now.strftime("%Y-%m-%d")
    run_ts = now.strftime("%H%M%S")
    out_dir = RAW_DIR / f"run_date={run_date}" / f"run_ts={run_ts}"
    print(f"[INFO] feeds={len(feeds)} out={out_dir}")

    total_entries = 0
    failed = 0

    for feed in feeds:
        name = feed["name"]
        content = download_feed(feed["url"])
        if content is None:
            print(f"[ERR] {name} skipped")
            failed += 1
            continue

        feed_title, entries, bozo_reason = parse_entries(content)
        if not entries:
            print(f"[ERR] {name} returned 0 entries bozo={bozo_reason}")
            failed += 1
            continue

        payload = {
            "fetched_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "rss",
            "feed_name": name,
            "feed_url": feed["url"],
            "feed_title": feed_title,
            "language": feed.get("language"),
            "entry_count": len(entries),
            "entries": entries,
        }
        path = save_raw(payload, name, out_dir)

        dated = sum(1 for e in entries if e["published"])
        warn = f" [WARN] malformed xml: {bozo_reason}" if bozo_reason else ""
        print(f"[OK] {name} lang={feed.get('language')} entries={len(entries)} with_date={dated} -> {path}{warn}")
        total_entries += len(entries)

    print(f"[OK] run complete feeds={len(feeds)} total_entries={total_entries} failed={failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()