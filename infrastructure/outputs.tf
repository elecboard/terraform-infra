output "ecr_repository_url" {
  description = "ECR repository URL for the int-shopify image. Push target for the NestJS container."
  value       = module.aws-ecr.repository_url
}
