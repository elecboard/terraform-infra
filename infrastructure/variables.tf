# Copyright (c) HashiCorp, Inc.
# SPDX-License-Identifier: MPL-2.0

variable "region" {
  type        = string
  description = "AWS region for all resources."

  default = "eu-central-1"
}

variable "project_name" {
  type        = string
  description = "Infrastructure to deploy EB's services."

  default = "terraform-eb"
}

variable "db_master_password" {
  type        = string
  description = "Master password for Aurora PostgreSQL database."
  sensitive   = true
}

variable "db_master_username" {
  type        = string
  description = "Master username for Aurora PostgreSQL database."
  sensitive   = true
  default     = "postgres"
}

variable "db_name" {
  type        = string
  description = "Initial database name."
  default     = "ebdb"
}

variable "db_schema" {
  type        = string
  description = "Database schema."
  default     = "public"
}

variable "dreamland_images_url" {
  type        = string
  description = "URL of the Dreamland image feed (leave empty to skip image sync)."
  default     = ""
}

variable "dreamland_base_url" {
  type        = string
  description = "Base URL for downloading individual Dreamland images."
  default     = ""
}
