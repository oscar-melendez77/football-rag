import argparse
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from google.cloud import bigquery
from sentence_transformers import SentenceTransformer

MODEL_NAME = "intfloat/multilingual-e5-small"
CHUNK_WORDS = 200
OVERLAP_WORDS = 40
ARTICLES_PER_BATCH = 100
ENCODE_BATCH = 64
ARTICLES_TABLE = "football_silver.articles"
CHUNKS_TABLE = "football_gold.article_chunks"

HASH_SQL = "to_hex(md5(concat(coalesce(a.title, ''), '|', coalesce(a.body, a.summary, ''))))"


def chunk_words(text):
    words = text.split()
    if len(words) <= CHUNK_WORDS:
        return [" ".join(words)]
    step = CHUNK_WORDS - OVERLAP_WORDS
    chunks = []
    for start in range(0, len(words), step):
        chunks.append(" ".join(words[start:start + CHUNK_WORDS]))
        if start + CHUNK_WORDS >= len(words):
            break
    return chunks


def fetch_pending(bq, project, limit):
    limit_sql = f"limit {int(limit)}" if limit else ""
    query = f"""
        select
            a.article_id, a.url, a.publisher, a.language, a.title,
            coalesce(a.body, a.summary) as text,
            a.published_at,
            {HASH_SQL} as content_hash
        from `{project}.{ARTICLES_TABLE}` as a
        left join (
            select distinct article_id, content_hash
            from `{project}.{CHUNKS_TABLE}`
        ) as c
            on c.article_id = a.article_id
            and c.content_hash = {HASH_SQL}
        where c.article_id is null
          and coalesce(a.body, a.summary, '') != ''
        order by a.published_at desc
        {limit_sql}
    """
    return list(bq.query(query).result())


def delete_old_chunks(bq, project, article_ids):
    query = f"delete from `{project}.{CHUNKS_TABLE}` where article_id in unnest(@ids)"
    config = bigquery.QueryJobConfig(query_parameters=[bigquery.ArrayQueryParameter("ids", "STRING", article_ids)])
    job = bq.query(query, job_config=config)
    job.result()
    return job.num_dml_affected_rows or 0


def load_rows(bq, project, rows):
    table = bq.get_table(f"{project}.{CHUNKS_TABLE}")
    config = bigquery.LoadJobConfig(
        schema=table.schema,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    job = bq.load_table_from_json(rows, table, job_config=config)
    job.result()
    return job.output_rows or 0


def build_chunks(articles):
    items = []
    for a in articles:
        for i, piece in enumerate(chunk_words(a["text"])):
            items.append((a, i, piece))
    return items


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Embed new or changed articles into football_gold.article_chunks")
    parser.add_argument("--limit", type=int, help="Only embed the N most recent pending articles (for testing)")
    args = parser.parse_args()

    project = os.getenv("GCP_PROJECT")
    if not project:
        print("[ERR] GCP_PROJECT is not set")
        sys.exit(1)

    bq = bigquery.Client(project=project)
    pending = fetch_pending(bq, project, args.limit)
    print(f"[INFO] pending_articles={len(pending)}")
    if not pending:
        print("[OK] nothing to embed")
        return

    print(f"[INFO] loading model {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME, device="cpu")

    total_chunks = 0
    total_replaced = 0
    for start in range(0, len(pending), ARTICLES_PER_BATCH):
        batch = pending[start:start + ARTICLES_PER_BATCH]
        items = build_chunks(batch)
        inputs = [f"passage: {a['title'] or ''}. {piece}" for a, _, piece in items]
        vectors = model.encode(inputs, batch_size=ENCODE_BATCH, normalize_embeddings=True, show_progress_bar=False)

        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for (a, i, piece), vector in zip(items, vectors):
            rows.append({
                "chunk_id": f"{a['article_id']}-{i}",
                "article_id": a["article_id"],
                "chunk_index": i,
                "content_hash": a["content_hash"],
                "url": a["url"],
                "publisher": a["publisher"],
                "language": a["language"],
                "title": a["title"],
                "published_at": a["published_at"].isoformat() if a["published_at"] else None,
                "chunk_text": piece,
                "embedding": [float(x) for x in vector],
                "embedding_model": MODEL_NAME,
                "embedded_at": now,
            })

        total_replaced += delete_old_chunks(bq, project, [a["article_id"] for a in batch])
        total_chunks += load_rows(bq, project, rows)
        print(f"[INFO] articles {start + len(batch)}/{len(pending)} chunks_so_far={total_chunks}")

    print(f"[OK] articles={len(pending)} chunks={total_chunks} old_chunks_replaced={total_replaced} -> {project}.{CHUNKS_TABLE}")


if __name__ == "__main__":
    main()