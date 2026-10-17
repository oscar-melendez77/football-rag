terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_project_service" "storage" {
  service            = "storage.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "bigquery" {
  service            = "bigquery.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "iam" {
  service            = "iam.googleapis.com"
  disable_on_destroy = false
}

resource "google_storage_bucket" "lake" {
  name          = "football-rag-lake-${var.bucket_suffix}"
  location      = upper(var.region)
  storage_class = "STANDARD"

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  labels = {
    project = "football-rag"
    layer   = "bronze"
  }

  depends_on = [google_project_service.storage]
}

locals {
  datasets = {
    bronze = "Raw data loaded as-is from the lake"
    silver = "Cleaned, typed, deduplicated tables"
    gold   = "Business-ready models for analytics and RAG"
  }
}

resource "google_bigquery_dataset" "layers" {
  for_each = local.datasets

  dataset_id  = "football_${each.key}"
  description = each.value
  location    = var.region

  labels = {
    project = "football-rag"
    layer   = each.key
  }

  depends_on = [google_project_service.bigquery]
}

resource "google_service_account" "airflow" {
  account_id   = "airflow-pipeline"
  display_name = "Airflow pipeline"
  description  = "Identity used by Airflow tasks to write to the data lake"

  depends_on = [google_project_service.iam]
}

resource "google_storage_bucket_iam_member" "airflow_lake_writer" {
  bucket = google_storage_bucket.lake.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.airflow.email}"
}