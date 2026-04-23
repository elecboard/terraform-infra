output "cluster_endpoint" {
  description = "Writer endpoint for the Aurora cluster."
  value       = aws_rds_cluster.aurora.endpoint
}

output "cluster_identifier" {
  description = "Identifier of the Aurora cluster."
  value       = aws_rds_cluster.aurora.cluster_identifier
}
