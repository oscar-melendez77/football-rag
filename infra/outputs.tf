output "bucket_name" {
  value = google_storage_bucket.lake.name
}

output "bucket_url" {
  value = google_storage_bucket.lake.url
}

output "datasets" {
  value = [for d in google_bigquery_dataset.layers : d.dataset_id]
}