variable "project_name" {
  type        = string
  description = "Infrastructure to deploy EB's services."
}

variable "db_name" {
  type        = string
  description = "Initial database name for Aurora PostgreSQL."

  default = "ebdb"
}

variable "db_master_username" {
  type        = string
  description = "Master username for Aurora PostgreSQL database."
  sensitive   = true

  default = "postgres"
}

variable "db_master_password" {
  type        = string
  description = "Master password for Aurora PostgreSQL database."
  sensitive   = true
}

variable "rds_min_capacity" {
  type        = number
  description = "Minimum capacity units for Aurora Serverless v2."

  default = 0.5
}

variable "rds_max_capacity" {
  type        = number
  description = "Maximum capacity units for Aurora Serverless v2."

  default = 1
}
