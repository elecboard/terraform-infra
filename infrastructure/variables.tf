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
