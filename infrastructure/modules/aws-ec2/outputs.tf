output "instance_id" {
  description = "EC2 host id. Use with: aws ssm start-session --target <id>"
  value       = aws_instance.host.id
}

output "instance_public_ip" {
  value = aws_instance.host.public_ip
}

output "security_group_id" {
  description = "Host SG. Grant this ingress on Aurora's SG to lock the DB down."
  value       = aws_security_group.host.id
}

output "role_arn" {
  value = aws_iam_role.host.arn
}
