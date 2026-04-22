# Copyright (c) HashiCorp, Inc.
# SPDX-License-Identifier: MPL-2.0

variable "ami_id" {
  type        = string
  description = "AMI id for instance."
}

variable "instance_name" {
  type        = string
  description = "Electronic Board Instance."
}

variable "project_name" {
  type        = string
  description = "Infrastructure to deploy EB's services."

  default = "terraform-eb"
}

variable "instance_type" {
  type        = string
  description = "Instance type for the EC2 instance."

  default = "t3.micro"
}
