import argparse
import os
import sys
import time

import requests
from dotenv import load_dotenv
from google.cloud import bigquery
from sentence_transformers import SentenceTransformer

from search_articles import MODEL_NAME, detect_teams, load_aliases, search

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
TOP_ARTICLES = 5
PASSAGE_CHARS = 1200

SYSTEM_PROMPT = """You are a football analyst assistant.
Answer ONLY with the FACTS and SOURCES provided. Never use outside knowledge, even if you think you know the answer.
Rules:
- Cite every claim: [F] for facts from the data tables, [1]-[5] for article sources.
- Paraphrase. Never copy more than a few words from an article.
- If the facts and sources do not answer the question, say so clearly and briefly.
- Prefer FACTS for numbers (positions, results, odds, absences); use SOURCES for context and opinions.
- Answer in the same language as the question. Keep it under 180 words."""


def ascii_safe(text):
    return str(text).encode("ascii", "replace").decode("ascii")


def run(bq, sql, team_ids):
    config = bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter("ids", "INT64", team_ids)])
    return list(bq.query(sql, job_config=config).result())


def collect_facts(bq, project, team_ids):
    if not team_ids:
        return "No team identified in the question, so no table facts were retrieved."
    p = project
    lines = []

    for r in run(bq, f"""
        SELECT team_name, competitions, founded_year, form_last5, points_last5,
               domestic_competition, domestic_position, domestic_points, players_out, players_doubtful
        FROM `{p}.football_gold.team_profile` WHERE team_id IN UNNEST(@ids)""", team_ids):
        lines.append(
            f"TEAM {r['team_name']}: competitions={','.join(r['competitions'] or [])}, founded={r['founded_year']}, "
            f"form last 5 (newest first)={r['form_last5']} ({r['points_last5']} pts), "
            f"league={r['domestic_competition']} position={r['domestic_position']} points={r['domestic_points']}, "
            f"players out={r['players_out']}, doubtful={r['players_doubtful']}")

    for r in run(bq, f"""
        SELECT * FROM (
            SELECT t1.team_name AS team, r.kickoff_utc, r.competition_code, t2.team_name AS opponent,
                   r.is_home, r.goals_for, r.goals_against, r.result,
                   ROW_NUMBER() OVER (PARTITION BY r.team_id ORDER BY r.kickoff_utc DESC) AS rn
            FROM `{p}.football_gold.team_match_results` r
            JOIN `{p}.football_silver.teams` t1 ON t1.team_id = r.team_id
            JOIN `{p}.football_silver.teams` t2 ON t2.team_id = r.opponent_id
            WHERE r.team_id IN UNNEST(@ids))
        WHERE rn <= 5 ORDER BY team, kickoff_utc DESC""", team_ids):
        venue = "home" if r["is_home"] else "away"
        lines.append(f"RESULT {r['team']} {r['kickoff_utc']:%Y-%m-%d} {r['competition_code']} vs {r['opponent']} ({venue}): "
                     f"{r['goals_for']}-{r['goals_against']} {r['result']}")

    for r in run(bq, f"""
        SELECT kickoff_utc, competition_code, home_team_name, away_team_name, prob_home, prob_draw, prob_away
        FROM `{p}.football_gold.upcoming_fixtures`
        WHERE home_team_id IN UNNEST(@ids) OR away_team_id IN UNNEST(@ids)
        ORDER BY kickoff_utc LIMIT 3""", team_ids):
        odds = ("market odds home/draw/away = "
                f"{r['prob_home']:.0%}/{r['prob_draw']:.0%}/{r['prob_away']:.0%}") if r["prob_home"] is not None else "no odds yet"
        lines.append(f"FIXTURE {r['kickoff_utc']:%Y-%m-%d %H:%M} UTC {r['competition_code']}: "
                     f"{r['home_team_name']} vs {r['away_team_name']}, {odds}")

    for r in run(bq, f"""
        SELECT ta.team_name, pa.web_name, pa.status, pa.news, pa.chance_next_round
        FROM `{p}.football_silver.player_availability` pa
        JOIN `{p}.football_gold.team_availability` ta ON ta.fpl_code = pa.team_short_name
        WHERE pa.is_current AND pa.status IN ('injured', 'suspended', 'doubtful')
          AND ta.team_id IN UNNEST(@ids)
        ORDER BY ta.team_name, pa.status LIMIT 20""", team_ids):
        chance = f", chance next round {r['chance_next_round']}%" if r["chance_next_round"] is not None else ""
        lines.append(f"ABSENCE {r['team_name']}: {r['web_name']} {r['status']} - {r['news'] or 'no details'}{chance}")

    return "\n".join(lines) if lines else "No table facts found for the identified team(s)."


def format_sources(results):
    blocks = []
    for i, r in enumerate(results, start=1):
        date = r["published_at"].strftime("%Y-%m-%d") if r["published_at"] else "unknown date"
        text = " ".join(r["chunk_text"].split())[:PASSAGE_CHARS]
        blocks.append(f"[{i}] {r['publisher']} {date} | {r['title']}\n{text}")
    return "\n\n".join(blocks) if blocks else "No relevant articles found."


def call_llm(question, facts, sources):
    key = os.getenv("GROQ_API_KEY")
    if not key:
        print("[ERR] GROQ_API_KEY is not set")
        sys.exit(1)
    payload = {
        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "temperature": 0.2,
        "max_tokens": 600,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"QUESTION: {question}\n\nFACTS:\n{facts}\n\nSOURCES:\n{sources}"},
        ],
    }
    for attempt in range(1, 4):
        response = requests.post(GROQ_URL, json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=60)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        if response.status_code in (429, 500, 502, 503):
            wait = int(response.headers.get("retry-after", 2 ** attempt * 5))
            print(f"[RETRY] status={response.status_code} sleeping {wait}s")
            time.sleep(wait)
            continue
        print(f"[ERR] LLM call failed status={response.status_code} body={ascii_safe(response.text[:300])}")
        sys.exit(1)
    print("[ERR] LLM call failed after retries")
    sys.exit(1)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Ask the football assistant a question")
    parser.add_argument("question")
    parser.add_argument("--show-context", action="store_true", help="Print the facts sent to the LLM")
    args = parser.parse_args()

    project = os.getenv("GCP_PROJECT")
    if not project:
        print("[ERR] GCP_PROJECT is not set")
        sys.exit(1)

    bq = bigquery.Client(project=project)
    teams = detect_teams(args.question, load_aliases(bq, project))
    team_ids = list(teams)

    facts = collect_facts(bq, project, team_ids)
    model = SentenceTransformer(MODEL_NAME, device="cpu")
    vector = model.encode(f"query: {args.question}", normalize_embeddings=True).tolist()
    results = search(bq, project, vector, None, TOP_ARTICLES, team_ids)

    answer = call_llm(args.question, facts, format_sources(results))

    print(f"\nQuestion: {ascii_safe(args.question)}")
    print(f"Teams detected: {', '.join(teams.values()) if teams else 'none'}")
    if args.show_context:
        print(f"\n--- FACTS SENT TO THE MODEL ---\n{ascii_safe(facts)}")
    print(f"\n--- ANSWER ---\n{ascii_safe(answer)}\n")
    print("--- SOURCES ---")
    print("[F] football-rag tables (football-data.org, FPL, The Odds API)")
    for i, r in enumerate(results, start=1):
        print(f"[{i}] {r['publisher']} - {ascii_safe(r['title'])}\n    {r['url']}")


if __name__ == "__main__":
    main()