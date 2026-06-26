variable "project_name" {
  type        = string
  description = "Stack-wide name prefix (e.g. terraform-eb)."
}

variable "service_name" {
  type        = string
  description = "Service this host runs. Used for the instance Name tag (the CI deploy looks the host up by it), resource names and the /opt/<service> app directory."
  default     = "int-shopify"
}

variable "region" {
  type        = string
  description = "AWS region. Baked into the on-box deploy script."
}

variable "instance_type" {
  type        = string
  description = "EC2 host size. t3.small (2 vCPU / 2 GB) fits nestjs + redis with headroom."
  default     = "t3.small"
}

variable "root_volume_gb" {
  type        = number
  description = "Root EBS volume size (GB)."
  default     = 30
}

variable "ecr_repository_name" {
  type        = string
  description = "ECR repo the host pulls the app image from (pull-only IAM scope)."
  default     = "terraform-eb-int-shopify"
}

variable "dotenv_param_name" {
  type        = string
  description = "SSM SecureString the CI writes the app .env to; the host reads+decrypts it at deploy time."
  default     = "/int-shopify/deploy/dotenv"
}
