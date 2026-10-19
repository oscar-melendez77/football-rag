resource "google_bigquery_table" "article_chunks" {
  dataset_id          = google_bigquery_dataset.layers["gold"].dataset_id
  table_id            = "article_chunks"
  description         = "Article passages with embeddings for semantic search (RAG)"
  deletion_protection = false

  clustering = ["publisher"]

  schema = jsonencode([
    { name = "chunk_id", type = "STRING", mode = "REQUIRED" },
    { name = "article_id", type = "STRING", mode = "REQUIRED" },
    { name = "chunk_index", type = "INT64", mode = "REQUIRED" },
    { name = "content_hash", type = "STRING", mode = "REQUIRED", description = "md5 of title + text; changes when the article changes" },
    { name = "url", type = "STRING", mode = "NULLABLE" },
    { name = "publisher", type = "STRING", mode = "NULLABLE" },
    { name = "language", type = "STRING", mode = "NULLABLE" },
    { name = "title", type = "STRING", mode = "NULLABLE" },
    { name = "published_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "chunk_text", type = "STRING", mode = "REQUIRED" },
    { name = "embedding", type = "FLOAT64", mode = "REPEATED", description = "Normalized embedding vector" },
    { name = "embedding_model", type = "STRING", mode = "REQUIRED" },
    { name = "embedded_at", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}