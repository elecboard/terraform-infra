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
