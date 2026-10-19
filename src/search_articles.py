import argparse
import os
import sys

from dotenv import load_dotenv
from google.cloud import bigquery
from sentence_transformers import SentenceTransformer

MODEL_NAME = "intfloat/multilingual-e5-small"
CHUNKS_TABLE = "football_gold.article_chunks"
CANDIDATES = 20
PREVIEW_CHARS = 200


def ascii_safe(text):
    return str(text).encode("ascii", "replace").decode("ascii")


def search(bq, project, query_vector, language, top_articles):
    base = f"`{project}.{CHUNKS_TABLE}`"
    params = [bigquery.ArrayQueryParameter("query_vector", "FLOAT64", query_vector)]
    if language:
        base = f"(SELECT * FROM `{project}.{CHUNKS_TABLE}` WHERE language = @language)"
        params.append(bigquery.ScalarQueryParameter("language", "STRING", language))

    sql = f"""
        SELECT
            base.article_id, base.title, base.publisher, base.language,
            base.published_at, base.url, base.chunk_text, distance
        FROM VECTOR_SEARCH(
            TABLE {base} if False else {base},
            'embedding',
            (SELECT @query_vector AS embedding),
            top_k => {CANDIDATES},
            distance_type => 'COSINE'
        )
        ORDER BY distance
    """
    sql = sql.replace(f"TABLE {base} if False else {base}", f"{'TABLE ' + base if not language else base}")
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
    args = parser.parse_args()

    project = os.getenv("GCP_PROJECT")
    if not project:
        print("[ERR] GCP_PROJECT is not set")
        sys.exit(1)

    model = SentenceTransformer(MODEL_NAME, device="cpu")
    query_vector = model.encode(f"query: {args.question}", normalize_embeddings=True).tolist()

    bq = bigquery.Client(project=project)
    results = search(bq, project, query_vector, args.language, args.top)

    print(f"\nQuestion: {ascii_safe(args.question)}\n")
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