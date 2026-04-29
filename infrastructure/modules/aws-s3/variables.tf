variable "project_name" {
  type        = string
  description = "Project name used as a prefix for the S3 bucket name."
}

variable "bucket_suffix" {
  type        = string
  description = "Unique suffix appended to the bucket name to ensure global uniqueness."
}

variable "versioning_enabled" {
  type        = bool
  description = "Enable versioning on the S3 bucket."
  default     = true
}
