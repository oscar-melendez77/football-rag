import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://fantasy.premierleague.com/api"
ENDPOINTS = {
    "bootstrap": "bootstrap-static/",
    "fixtures": "fixtures/",
}
RAW_DIR = Path("data/raw/fpl")
MAX_RETRIES = 3
TIMEOUT = 60
USER_AGENT = "football-rag/0.1 (portfolio project; low-frequency snapshots)"
STATUS_LABELS = {"a": "available", "d": "doubtful", "i": "injured", "s": "suspended", "u": "unavailable", "n": "not_in_squad"}


def ascii_safe(text):
    return str(text).encode("ascii", "replace").decode("ascii")


def fetch(path):
    url = f"{BASE_URL}/{path}"
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            wait = 2 ** attempt * 5
            print(f"[RETRY] {path} attempt={attempt} network error: {ascii_safe(exc)} sleeping {wait}s")
            time.sleep(wait)
            continue

        status = response.status_code
        if status == 200:
            try:
                return response.json()
            except ValueError:
                print(f"[ERR] {path} returned non-JSON content (site may be updating)")
                return None
        if status == 429 or status >= 500:
            wait = 2 ** attempt * 5
            print(f"[RETRY] {path} attempt={attempt} status={status} sleeping {wait}s")
            time.sleep(wait)
            continue

        print(f"[ERR] {path} status={status}")
        return None

    print(f"[ERR] {path} failed after {MAX_RETRIES} attempts")
    return None


def save_raw(payload, name, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return path


def summarize_bootstrap(data):
    players = data.get("elements", [])
    statuses = Counter(STATUS_LABELS.get(p.get("status"), "other") for p in players)
    with_news = sum(1 for p in players if p.get("news"))
    return f"players={len(players)} teams={len(data.get('teams', []))} with_news={with_news} statuses={dict(statuses)}"


def summarize_fixtures(data):
    finished = sum(1 for f in data if f.get("finished"))
    return f"fixtures={len(data)} finished={finished} upcoming={len(data) - finished}"


def main():
    now = datetime.now(timezone.utc)
    run_date = now.strftime("%Y-%m-%d")
    run_ts = now.strftime("%H%M%S")
    out_dir = RAW_DIR / f"run_date={run_date}" / f"run_ts={run_ts}"
    print(f"[INFO] snapshot out={out_dir}")

    failed = 0
    for name, path in ENDPOINTS.items():
        data = fetch(path)
        if data is None:
            failed += 1
            continue

        payload = {
            "fetched_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "fpl",
            "endpoint": path,
            "data": data,
        }
        saved = save_raw(payload, name, out_dir)

        summary = summarize_bootstrap(data) if name == "bootstrap" else summarize_fixtures(data)
        print(f"[OK] {name} {summary} -> {saved}")

    print(f"[OK] run complete endpoints={len(ENDPOINTS)} failed={failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()