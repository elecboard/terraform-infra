# Root outputs for the int-shopify Docker host.
output "int_shopify_instance_id" {
  description = "EC2 host id. SSM in with: aws ssm start-session --target <id>"
  value       = module.aws-ec2-int-shopify.instance_id
}

output "int_shopify_instance_public_ip" {
  value = module.aws-ec2-int-shopify.instance_public_ip
}

output "int_shopify_host_sg" {
  description = "Host security group id (for locking Aurora's ingress down to it)."
  value       = module.aws-ec2-int-shopify.security_group_id
}
