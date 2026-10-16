variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment name"
  type        = string
  default     = "demo"
}

variable "vpc_cidr" {
  description = "CIDR block for the ElasticMind VPC"
  type        = string
  default     = "10.20.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDRs for the two public subnets (one per AZ). Public-only avoids NAT cost."
  type        = list(string)
  default     = ["10.20.0.0/24", "10.20.1.0/24"]
}

variable "target_desired_count" {
  description = "Initial desired task count for the target app service"
  type        = number
  default     = 2
}

variable "target_min_count" {
  description = "Minimum task count enforced by the autoscaler"
  type        = number
  default     = 1
}

variable "target_max_count" {
  description = "Maximum task count enforced by the autoscaler"
  type        = number
  default     = 10
}

variable "backend_desired_count" {
  description = "Desired task count for the backend controller service"
  type        = number
  default     = 1
}

variable "task_cpu" {
  description = "Fargate task CPU units (256 = 0.25 vCPU, keeps cost low)"
  type        = string
  default     = "256"
}

variable "task_memory" {
  description = "Fargate task memory (MiB)"
  type        = string
  default     = "512"
}

variable "budget_limit_usd" {
  description = "Monthly AWS budget threshold that triggers the alarm"
  type        = number
  default     = 30
}

variable "budget_alert_email" {
  description = "Email address for budget and alarm notifications"
  type        = string
  default     = ""
}

variable "model_s3_prefix" {
  description = "Prefix inside the artifacts bucket for trained models"
  type        = string
  default     = "models"
}
