output "alb_dns_name" {
  description = "Public DNS of the load balancer fronting the target app"
  value       = aws_lb.main.dns_name
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "target_service_name" {
  value = aws_ecs_service.target.name
}

output "backend_service_name" {
  value = aws_ecs_service.backend.name
}

output "backend_public_note" {
  description = "Reach the controller API via the task public IP on port 8000 (or add an ALB listener)"
  value       = "http://<backend-task-public-ip>:8000/docs"
}

output "ecr_backend_repo" {
  value = aws_ecr_repository.backend.repository_url
}

output "ecr_target_repo" {
  value = aws_ecr_repository.target_app.repository_url
}

output "artifacts_bucket" {
  value = aws_s3_bucket.artifacts.bucket
}

output "log_group_backend" {
  value = aws_cloudwatch_log_group.backend.name
}

output "log_group_target" {
  value = aws_cloudwatch_log_group.target.name
}
