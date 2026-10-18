import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_URL = "https://api.the-odds-api.com/v4"
RAW_DIR = Path("data/raw/odds")
DEFAULT_LEAGUES = [
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
]
REGIONS = "eu"
MARKETS = "h2h"
MIN_CREDITS_LEFT = 50
TIMEOUT = 30


def ascii_safe(text):
    return str(text).encode("ascii", "replace").decode("ascii")


def load_api_key():
    load_dotenv()
    key = os.getenv("ODDS_API_KEY")
    if not key:
        print("[ERR] ODDS_API_KEY missing in .env")
        sys.exit(1)
    return key


def credits_from(response):
    try:
        return int(float(response.headers.get("x-requests-remaining")))
    except (TypeError, ValueError):
        return None


def get_active_sports(api_key):
    response = requests.get(f"{BASE_URL}/sports", params={"apiKey": api_key}, timeout=TIMEOUT)
    if response.status_code != 200:
        print(f"[ERR] sports list status={response.status_code} body={ascii_safe(response.text[:200])}")
        return None, None
    active = {s["key"] for s in response.json() if s.get("active")}
    return active, credits_from(response)


def fetch_odds(api_key, sport_key):
    params = {
        "apiKey": api_key,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    response = requests.get(f"{BASE_URL}/sports/{sport_key}/odds", params=params, timeout=TIMEOUT)
    if response.status_code != 200:
        print(f"[ERR] {sport_key} status={response.status_code} body={ascii_safe(response.text[:200])}")
        return None, credits_from(response)
    return response.json(), credits_from(response)


def parse_args():
    parser = argparse.ArgumentParser(description="Daily snapshot of match-winner odds")
    parser.add_argument("--leagues", nargs="+", default=DEFAULT_LEAGUES)
    return parser.parse_args()


def main():
    args = parse_args()
    api_key = load_api_key()

    active, credits_left = get_active_sports(api_key)
    if active is None:
        sys.exit(1)
    print(f"[INFO] credits_left={credits_left} leagues_requested={len(args.leagues)}")

    now = datetime.now(timezone.utc)
    out_dir = RAW_DIR / f"run_date={now.strftime('%Y-%m-%d')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    saved = 0
    failed = 0
    for sport_key in args.leagues:
        if sport_key not in active:
            print(f"[SKIP] {sport_key} not active right now (off-season or wrong key), no credits spent")
            continue
        if credits_left is not None and credits_left < MIN_CREDITS_LEFT:
            print(f"[STOP] credits_left={credits_left} below safety floor {MIN_CREDITS_LEFT}, skipping the rest")
            break

        events, credits_after = fetch_odds(api_key, sport_key)
        if credits_after is not None:
            credits_left = credits_after
        if events is None:
            failed += 1
            continue

        payload = {
            "fetched_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "the-odds-api",
            "sport_key": sport_key,
            "regions": REGIONS,
            "markets": MARKETS,
            "event_count": len(events),
            "events": events,
        }
        path = out_dir / f"{sport_key}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

        bookmakers = sum(len(e.get("bookmakers", [])) for e in events)
        print(f"[OK] {sport_key} events={len(events)} bookmaker_quotes={bookmakers} credits_left={credits_left} -> {path}")
        saved += 1
        time.sleep(1)

    print(f"[OK] run complete saved={saved} failed={failed} credits_left={credits_left}")
    if failed or saved == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()