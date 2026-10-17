variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "Region for all resources. US regions keep Cloud Storage inside the always-free tier."
  type        = string
  default     = "us-central1"
}

variable "bucket_suffix" {
  description = "Suffix to make the bucket name globally unique"
  type        = string
}