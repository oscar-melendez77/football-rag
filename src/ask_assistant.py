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
POSITION_NAMES = {"GK": "goalkeeper", "DEF": "defender", "MID": "midfielder", "FWD": "forward"}

SYSTEM_PROMPT = """You are a football analyst assistant.
Answer ONLY with the FACTS and SOURCES provided. Never use outside knowledge, even if you think you know the answer.
Rules:
- Cite every claim: [F] for facts from the data tables, [1]-[5] for article sources.
- Do not add anything that is not stated in the material: no player first names, positions, nationalities, clubs,
  trophies, titles, history, competition formats or stages unless they appear in FACTS or SOURCES.
- "unknown" or "no data" means the information is missing. Never treat missing data as zero or as "none".
- Do not derive counts that are not given (for example, games played); use them only if stated in FACTS.
- Keep each claim tied to the single source that states it. Do not combine details from different sources into one claim.
- If sources disagree, say so.
- Paraphrase. Never copy more than a few words from an article.
- If the facts and sources do not answer the question, say so clearly and briefly.
- Prefer FACTS for numbers (table positions, results, odds, absences); use SOURCES for context and opinions.
- Answer in the same language as the question. Keep it under 180 words."""


def known(value, suffix=""):
    return f"{value}{suffix}" if value is not None else "unknown"


class Assistant:
    def __init__(self):
        load_dotenv()
        self.project = os.getenv("GCP_PROJECT")
        self.groq_key = os.getenv("GROQ_API_KEY")
        self.groq_model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
        if not self.project or not self.groq_key:
            raise RuntimeError("GCP_PROJECT and GROQ_API_KEY must be set")
        self.bq = bigquery.Client(project=self.project)
        self.aliases = load_aliases(self.bq, self.project)
        self.model = SentenceTransformer(MODEL_NAME, device="cpu")

    def _run(self, sql, team_ids):
        config = bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter("ids", "INT64", team_ids)])
        return list(self.bq.query(sql, job_config=config).result())

    def collect_facts(self, team_ids):
        if not team_ids:
            return "No team identified in the question, so no table facts were retrieved."
        p = self.project
        lines = []

        for r in self._run(f"""
            SELECT pr.team_name, pr.competitions, pr.founded_year, pr.form_last5, pr.points_last5,
                   pr.domestic_competition, pr.domestic_position, pr.domestic_points, f.domestic_played,
                   pr.players_out, pr.players_doubtful
            FROM `{p}.football_gold.team_profile` pr
            LEFT JOIN `{p}.football_gold.team_form` f ON f.team_id = pr.team_id
            WHERE pr.team_id IN UNNEST(@ids)""", team_ids):
            absences = (f"players out={r['players_out']}, doubtful={r['players_doubtful']}"
                        if r["players_out"] is not None
                        else "absence data: not available for this team's league (no data, NOT zero)")
            lines.append(
                f"TEAM {r['team_name']}: competitions={','.join(r['competitions'] or [])}, founded={known(r['founded_year'])}, "
                f"form last 5 matches across all competitions (newest first)={known(r['form_last5'])} "
                f"({known(r['points_last5'], ' pts')}), league={known(r['domestic_competition'])} "
                f"table position={known(r['domestic_position'])}, league games played={known(r['domestic_played'])}, "
                f"league points={known(r['domestic_points'])}, {absences}")

        for r in self._run(f"""
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
                         f"{r['team']} {r['goals_for']}-{r['goals_against']} {r['opponent']}, result for {r['team']}: {r['result']}")

        for r in self._run(f"""
            SELECT kickoff_utc, competition_code, home_team_name, away_team_name, prob_home, prob_draw, prob_away
            FROM `{p}.football_gold.upcoming_fixtures`
            WHERE home_team_id IN UNNEST(@ids) OR away_team_id IN UNNEST(@ids)
            ORDER BY kickoff_utc LIMIT 3""", team_ids):
            home, away = r["home_team_name"], r["away_team_name"]
            odds = (f"market win probabilities: {home} {r['prob_home']:.0%}, draw {r['prob_draw']:.0%}, {away} {r['prob_away']:.0%}"
                    if r["prob_home"] is not None else "market odds: not available yet")
            lines.append(f"FIXTURE {r['kickoff_utc']:%Y-%m-%d %H:%M} UTC {r['competition_code']}: "
                         f"{home} (home) vs {away} (away), {odds}")

        for r in self._run(f"""
            SELECT ta.team_name, pa.web_name, pa.position, pa.status, pa.news, pa.chance_next_round
            FROM `{p}.football_silver.player_availability` pa
            JOIN `{p}.football_gold.team_availability` ta ON ta.fpl_code = pa.team_short_name
            WHERE pa.is_current AND pa.status IN ('injured', 'suspended', 'doubtful')
              AND ta.team_id IN UNNEST(@ids)
            ORDER BY ta.team_name, pa.status LIMIT 20""", team_ids):
            position = POSITION_NAMES.get(r["position"], "position unknown")
            chance = f", chance of playing next round {r['chance_next_round']}%" if r["chance_next_round"] is not None else ""
            lines.append(f"ABSENCE {r['team_name']}: {r['web_name']} ({position}) {r['status']} - "
                         f"{r['news'] or 'no details'}{chance}")

        return "\n".join(lines) if lines else "No table facts found for the identified team(s)."

    @staticmethod
    def format_sources(results):
        blocks = []
        for i, r in enumerate(results, start=1):
            date = r["published_at"].strftime("%Y-%m-%d") if r["published_at"] else "unknown date"
            text = " ".join(r["chunk_text"].split())[:PASSAGE_CHARS]
            blocks.append(f"[{i}] {r['publisher']} {date} | {r['title']}\n{text}")
        return "\n\n".join(blocks) if blocks else "No relevant articles found."

    def call_llm(self, question, facts, sources):
        payload = {
            "model": self.groq_model,
            "temperature": 0.2,
            "max_tokens": 1500,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"QUESTION: {question}\n\nFACTS:\n{facts}\n\nSOURCES:\n{sources}"},
            ],
        }
        for attempt in range(1, 4):
            response = requests.post(GROQ_URL, json=payload, headers={"Authorization": f"Bearer {self.groq_key}"}, timeout=90)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            if response.status_code in (429, 500, 502, 503):
                time.sleep(int(response.headers.get("retry-after", 2 ** attempt * 5)))
                continue
            raise RuntimeError(f"LLM call failed status={response.status_code}")
        raise RuntimeError("LLM call failed after retries")

    def ask(self, question):
        teams = detect_teams(question, self.aliases)
        team_ids = list(teams)
        facts = self.collect_facts(team_ids)
        vector = self.model.encode(f"query: {question}", normalize_embeddings=True).tolist()
        results = search(self.bq, self.project, vector, None, TOP_ARTICLES, team_ids)
        sources_text = self.format_sources(results)
        answer = self.call_llm(question, facts, sources_text)
        return {
            "question": question,
            "teams_detected": list(teams.values()),
            "answer": answer,
            "facts": facts,
            "sources": [
                {
                    "ref": i,
                    "publisher": r["publisher"],
                    "title": r["title"],
                    "url": r["url"],
                    "published_at": r["published_at"].strftime("%Y-%m-%d") if r["published_at"] else None,
                }
                for i, r in enumerate(results, start=1)
            ],
        }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Ask the football assistant a question")
    parser.add_argument("question")
    parser.add_argument("--show-context", action="store_true", help="Print the facts sent to the LLM")
    args = parser.parse_args()

    result = Assistant().ask(args.question)
    print(f"\nQuestion: {result['question']}")
    print(f"Teams detected: {', '.join(result['teams_detected']) or 'none'}")
    if args.show_context:
        print(f"\n--- FACTS SENT TO THE MODEL ---\n{result['facts']}")
    print(f"\n--- ANSWER ---\n{result['answer']}\n")
    print("--- SOURCES ---")
    print("[F] football-rag tables (football-data.org, FPL, The Odds API)")
    for s in result["sources"]:
        print(f"[{s['ref']}] {s['publisher']} - {s['title']}\n    {s['url']}")


if __name__ == "__main__":
    main()