import argparse
import os
import re
import sys
import unicodedata

from dotenv import load_dotenv
from google.cloud import bigquery
from sentence_transformers import SentenceTransformer

MODEL_NAME = "intfloat/multilingual-e5-small"
CHUNKS_TABLE = "football_gold.article_chunks"
TAGS_TABLE = "football_gold.chunk_team_tags"
ALIASES_TABLE = "football_gold.team_aliases"
CANDIDATES = 20
PREVIEW_CHARS = 200


def ascii_safe(text):
    return str(text).encode("ascii", "replace").decode("ascii")


def normalize_text(text):
    text = unicodedata.normalize("NFD", (text or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_aliases(bq, project):
    rows = bq.query(f"SELECT alias, team_id FROM `{project}.{ALIASES_TABLE}`").result()
    return [(row["team_id"], row["alias"], re.compile(r"\b" + re.escape(row["alias"]) + r"\b")) for row in rows]


def detect_teams(question, aliases):
    text = normalize_text(question)
    found = {}
    for team_id, alias, pattern in aliases:
        if pattern.search(text):
            found.setdefault(team_id, alias)
    return found


def search(bq, project, query_vector, language, top_articles, team_ids=None):
    filters = []
    params = [bigquery.ArrayQueryParameter("query_vector", "FLOAT64", query_vector)]
    if language:
        filters.append("c.language = @language")
        params.append(bigquery.ScalarQueryParameter("language", "STRING", language))
    if team_ids:
        filters.append(f"c.chunk_id IN (SELECT chunk_id FROM `{project}.{TAGS_TABLE}` WHERE team_id IN UNNEST(@team_ids))")
        params.append(bigquery.ArrayQueryParameter("team_ids", "INT64", list(team_ids)))

    if filters:
        base = f"(SELECT c.* FROM `{project}.{CHUNKS_TABLE}` AS c WHERE {' AND '.join(filters)})"
    else:
        base = f"TABLE `{project}.{CHUNKS_TABLE}`"

    sql = f"""
        SELECT
            base.article_id, base.title, base.publisher, base.language,
            base.published_at, base.url, base.chunk_text, distance
        FROM VECTOR_SEARCH(
            {base},
            'embedding',
            (SELECT @query_vector AS embedding),
            top_k => {CANDIDATES},
            distance_type => 'COSINE'
        )
        ORDER BY distance
    """
    rows = list(bq.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result())

    best_per_article = {}
    for row in rows:
        if row["article_id"] not in best_per_article:
            best_per_article[row["article_id"]] = row
    return list(best_per_article.values())[:top_articles]


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Semantic search over football article passages")
    parser.add_argument("question", help="A question or topic in plain language (any language)")
    parser.add_argument("--language", choices=["en", "es"], help="Only search articles in this language")
    parser.add_argument("--top", type=int, default=5, help="Number of articles to show")
    parser.add_argument("--no-entity-filter", action="store_true", help="Disable filtering by teams named in the question")
    args = parser.parse_args()

    project = os.getenv("GCP_PROJECT")
    if not project:
        print("[ERR] GCP_PROJECT is not set")
        sys.exit(1)

    bq = bigquery.Client(project=project)
    teams = {} if args.no_entity_filter else detect_teams(args.question, load_aliases(bq, project))

    model = SentenceTransformer(MODEL_NAME, device="cpu")
    query_vector = model.encode(f"query: {args.question}", normalize_embeddings=True).tolist()
    results = search(bq, project, query_vector, args.language, args.top, list(teams))

    print(f"\nQuestion: {ascii_safe(args.question)}")
    print(f"Teams detected: {', '.join(teams.values()) if teams else 'none (no filter)'}\n")
    for rank, r in enumerate(results, start=1):
        similarity = 1 - r["distance"]
        date = r["published_at"].strftime("%Y-%m-%d") if r["published_at"] else "unknown date"
        preview = " ".join(r["chunk_text"].split())[:PREVIEW_CHARS]
        print(f"{rank}. [{similarity:.3f}] {r['publisher']} ({r['language']}) {date}")
        print(f"   {ascii_safe(r['title'])}")
        print(f"   {r['url']}")
        print(f"   ...{ascii_safe(preview)}...\n")


if __name__ == "__main__":
    main()