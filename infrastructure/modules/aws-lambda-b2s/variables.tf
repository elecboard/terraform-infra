variable "project_name" {
  type        = string
  description = "Project name used to name resources."
}

variable "db_user" {
  type        = string
  description = "Database master username."
  sensitive   = true
}

variable "db_password" {
  type        = string
  description = "Database master password."
  sensitive   = true
}

variable "db_host" {
  type        = string
  description = "Database host endpoint."
}

variable "db_name" {
  type        = string
  description = "Database name."
}

variable "db_schema" {
  type        = string
  description = "Database schema."
}

variable "s3_bucket_id" {
  type        = string
  description = "ID (name) of the S3 bucket to watch for uploads."
}

variable "s3_bucket_arn" {
  type        = string
  description = "ARN of the S3 bucket to watch for uploads."
}

variable "s3_trigger_prefix" {
  type        = string
  description = "S3 key prefix that triggers the Lambda (e.g. buy2sell/)."
  default     = "buy2sell/"
}
