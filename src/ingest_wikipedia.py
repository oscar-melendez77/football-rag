import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
RAW_DIR = Path("data/raw/wikipedia")
MATCH_GLOBS = ["data/raw/matches/run_date=*/*.json", "data/raw/matches_backfill/*/*.json"]
REPO_URL = "https://github.com/oscar-melendez77/football-rag"
MAX_RETRIES = 4
SECONDS_BETWEEN_CALLS = 1.0
SEARCH_CANDIDATES = 5
WIKIDATA_BATCH = 50
FOOTBALL_CLUB_QID = "Q476028"
KEEP_PROPERTIES = {
    "P31": "instance_of",
    "P571": "inception",
    "P115": "home_venue",
    "P17": "country",
    "P118": "league",
    "P1448": "official_name",
    "P856": "official_website",
}

_last_call = [0.0]


def ascii_safe(text):
    return str(text).encode("ascii", "replace").decode("ascii")


def build_user_agent():
    load_dotenv()
    email = os.getenv("CONTACT_EMAIL")
    if not email:
        print("[ERR] CONTACT_EMAIL missing in .env (Wikimedia requires contact info in the User-Agent)")
        sys.exit(1)
    return f"football-rag/0.1 ({REPO_URL}; {email}) python-requests/{requests.__version__}"


def throttle():
    elapsed = time.time() - _last_call[0]
    if elapsed < SECONDS_BETWEEN_CALLS:
        time.sleep(SECONDS_BETWEEN_CALLS - elapsed)
    _last_call[0] = time.time()


def retry_wait(response, attempt):
    retry_after = response.headers.get("Retry-After") if response is not None else None
    try:
        return max(int(retry_after), 1)
    except (TypeError, ValueError):
        return 2 ** attempt * 5


def api_get(url, params, user_agent):
    headers = {"User-Agent": user_agent}
    params = {**params, "format": "json", "formatversion": 2}
    for attempt in range(1, MAX_RETRIES + 1):
        throttle()
        try:
            response = requests.get(url, params=params, headers=headers, timeout=30)
        except requests.RequestException as exc:
            wait = 2 ** attempt * 5
            print(f"[RETRY] attempt={attempt} network error: {ascii_safe(exc)} sleeping {wait}s")
            time.sleep(wait)
            continue

        if response.status_code == 200:
            return response.json()

        if response.status_code == 429 or response.status_code >= 500:
            wait = retry_wait(response, attempt)
            print(f"[RETRY] attempt={attempt} status={response.status_code} sleeping {wait}s")
            time.sleep(wait)
            continue

        print(f"[ERR] status={response.status_code} body={ascii_safe(response.text[:200])}")
        return None

    print(f"[ERR] failed after {MAX_RETRIES} attempts url={url}")
    return None


def load_teams():
    teams = {}
    for pattern in MATCH_GLOBS:
        for path in glob.glob(pattern):
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            code = payload.get("competition")
            for match in payload.get("matches", []):
                for side in ("homeTeam", "awayTeam"):
                    team = match.get(side) or {}
                    team_id = team.get("id")
                    if not team_id or not team.get("name"):
                        continue
                    entry = teams.setdefault(team_id, {
                        "team_id": team_id,
                        "team_name": team["name"],
                        "short_name": team.get("shortName"),
                        "tla": team.get("tla"),
                        "competitions": set(),
                    })
                    if code:
                        entry["competitions"].add(code)
    for entry in teams.values():
        entry["competitions"] = sorted(entry["competitions"])
    return sorted(teams.values(), key=lambda t: t["team_name"])


def fetch_claims(qids, user_agent):
    claims_by_qid = {}
    for i in range(0, len(qids), WIKIDATA_BATCH):
        batch = qids[i:i + WIKIDATA_BATCH]
        body = api_get(WIKIDATA_API, {
            "action": "wbgetentities",
            "ids": "|".join(batch),
            "props": "claims",
        }, user_agent)
        if not body:
            continue
        for qid, entity in body.get("entities", {}).items():
            claims = entity.get("claims", {})
            claims_by_qid[qid] = {name: claims.get(prop, []) for prop, name in KEEP_PROPERTIES.items()}
    return claims_by_qid


def is_football_club(claims):
    for statement in claims.get("instance_of", []):
        value = statement.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(value, dict) and value.get("id") == FOOTBALL_CLUB_QID:
            return True
    return False


def search_candidates(team_name, user_agent):
    body = api_get(WIKIPEDIA_API, {
        "action": "query",
        "list": "search",
        "srsearch": f"{team_name} football club",
        "srnamespace": 0,
        "srlimit": SEARCH_CANDIDATES,
    }, user_agent)
    if not body:
        return []
    return [r["title"] for r in body.get("query", {}).get("search", [])]


def candidate_qids(titles, user_agent):
    body = api_get(WIKIPEDIA_API, {
        "action": "query",
        "prop": "pageprops",
        "ppprop": "wikibase_item",
        "redirects": 1,
        "titles": "|".join(titles),
    }, user_agent)
    if not body:
        return []
    query = body.get("query", {})
    redirect_to = {r["from"]: r["to"] for r in query.get("redirects", [])}
    normalized_to = {n["from"]: n["to"] for n in query.get("normalized", [])}
    qid_by_title = {p.get("title"): p.get("pageprops", {}).get("wikibase_item") for p in query.get("pages", [])}
    ordered = []
    for title in titles:
        resolved = normalized_to.get(title, title)
        resolved = redirect_to.get(resolved, resolved)
        ordered.append((resolved, qid_by_title.get(resolved)))
    return ordered


def resolve_title(team_name, user_agent):
    candidates = search_candidates(team_name, user_agent)
    if not candidates:
        return None, "no_results", []
    ordered = candidate_qids(candidates, user_agent)
    qids = [qid for _, qid in ordered if qid]
    claims_by_qid = fetch_claims(qids, user_agent) if qids else {}
    for title, qid in ordered:
        if qid and is_football_club(claims_by_qid.get(qid, {})):
            return title, "verified_candidate", candidates
    return candidates[0], "fallback_top_result", candidates


def fetch_page(title, user_agent):
    body = api_get(WIKIPEDIA_API, {
        "action": "query",
        "prop": "extracts|pageprops|info",
        "explaintext": 1,
        "inprop": "url",
        "redirects": 1,
        "titles": title,
    }, user_agent)
    if not body:
        return None
    pages = body.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return None
    page = pages[0]
    return {
        "wiki_title": page.get("title"),
        "wiki_pageid": page.get("pageid"),
        "wiki_url": page.get("fullurl"),
        "wiki_last_revised": page.get("touched"),
        "wikidata_id": page.get("pageprops", {}).get("wikibase_item"),
        "extract": page.get("extract", ""),
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Snapshot Wikipedia + Wikidata for every team in the matches data")
    parser.add_argument("--limit", type=int, help="Only process the first N teams (for testing)")
    return parser.parse_args()


def main():
    args = parse_args()
    user_agent = build_user_agent()
    teams = load_teams()
    if not teams:
        print("[ERR] no teams found in matches raw data")
        sys.exit(1)
    if args.limit:
        teams = teams[:args.limit]
    print(f"[INFO] teams to resolve={len(teams)}")

    records = []
    not_found = []
    for n, team in enumerate(teams, start=1):
        title, method, candidates = resolve_title(team["team_name"], user_agent)
        page = fetch_page(title, user_agent) if title else None
        resolution = {"resolution_method": method, "search_candidates": candidates}
        if not page:
            not_found.append(team["team_name"])
            records.append({**team, **resolution, "wiki_title": None})
            continue
        records.append({**team, **resolution, **page})
        if n % 20 == 0:
            print(f"[INFO] resolved {n}/{len(teams)}")

    qids = sorted({r["wikidata_id"] for r in records if r.get("wikidata_id")})
    claims_by_qid = fetch_claims(qids, user_agent)

    unverified = []
    for r in records:
        claims = claims_by_qid.get(r.get("wikidata_id"), {})
        r["wikidata_claims"] = claims
        r["is_football_club"] = is_football_club(claims)
        r["extract_chars"] = len(r.get("extract") or "")
        if r.get("wiki_title") and not r["is_football_club"]:
            unverified.append(f"{r['team_name']} -> {r['wiki_title']}")

    now = datetime.now(timezone.utc)
    out_dir = RAW_DIR / f"run_date={now.strftime('%Y-%m-%d')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "teams.json"
    payload = {
        "fetched_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "wikipedia",
        "license": "CC BY-SA 4.0 (Wikipedia text); CC0 (Wikidata)",
        "team_count": len(records),
        "teams": records,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    verified = sum(1 for r in records if r["is_football_club"])
    print(f"[OK] teams={len(records)} found={len(records) - len(not_found)} verified_clubs={verified} unverified={len(unverified)} not_found={len(not_found)} -> {path}")
    for item in unverified:
        print(f"[REVIEW] {ascii_safe(item)}")
    for name in not_found:
        print(f"[MISSING] {ascii_safe(name)}")
    if not_found and len(not_found) == len(records):
        print("[ERR] nothing resolved, likely blocked or misconfigured")
        sys.exit(1)


if __name__ == "__main__":
    main()