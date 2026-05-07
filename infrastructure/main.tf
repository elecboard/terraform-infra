# Copyright (c) HashiCorp, Inc.
# SPDX-License-Identifier: MPL-2.0

provider "aws" {
  region = var.region
}

provider "random" {}

data "aws_ami" "ubuntu" {
  most_recent = true

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  owners = ["099720109477"] # Canonical
}

resource "random_pet" "instance" {
  length = 2
}

module "ec2-instance" {
  source = "./modules/aws-ec2-instance"

  ami_id        = data.aws_ami.ubuntu.id
  instance_name = random_pet.instance.id
}

module "hello" {
  source  = "joatmon08/hello/random"
  version = "4.0.0"

  hello        = "World"
  second_hello = random_pet.instance.id

  secret_key = "secret"
}

module "aws-aurora" {
  source = "./modules/aws-aurora"

  project_name       = var.project_name
  db_master_password = var.db_master_password
}

module "aws-s3" {
  source = "./modules/aws-s3"

  project_name  = var.project_name
  bucket_suffix = random_pet.instance.id
}

module "aws-lambda-b2s" {
  source = "./modules/aws-lambda-b2s"

  project_name      = var.project_name
  db_user           = var.db_master_username
  db_password       = var.db_master_password
  db_host           = module.aws-aurora.cluster_endpoint
  db_name           = var.db_name
  db_schema         = var.db_schema
  s3_bucket_id      = module.aws-s3.bucket_id
  s3_bucket_arn     = module.aws-s3.bucket_arn
  s3_trigger_prefix = "buy2sell/"
}

module "aws-lambda-dreamland" {
  source = "./modules/aws-lambda-dreamland"

  project_name      = var.project_name
  db_user           = var.db_master_username
  db_password       = var.db_master_password
  db_host           = module.aws-aurora.cluster_endpoint
  db_name           = var.db_name
  db_schema         = var.db_schema
  s3_bucket_id      = module.aws-s3.bucket_id
  s3_bucket_arn     = module.aws-s3.bucket_arn
  s3_trigger_prefix = "dreamland/"
  images_url        = var.dreamland_images_url
  base_url          = var.dreamland_base_url
}

resource "aws_s3_bucket_notification" "lambda_triggers" {
  bucket = module.aws-s3.bucket_id

  lambda_function {
    lambda_function_arn = module.aws-lambda-b2s.function_arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "buy2sell/"
  }

  lambda_function {
    lambda_function_arn = module.aws-lambda-dreamland.function_arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "dreamland/"
  }

  depends_on = [
    module.aws-lambda-b2s,
    module.aws-lambda-dreamland,
  ]
}
