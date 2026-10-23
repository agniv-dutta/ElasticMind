# Security groups -------------------------------------------------------------

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb-sg"
  description = "Public HTTP to the ALB"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "tasks" {
  name        = "${local.name}-tasks-sg"
  description = "Target app + backend tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "From ALB"
    from_port       = 8001
    to_port         = 8001
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  ingress {
    description = "Backend API (optional public)"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ALB -------------------------------------------------------------------------

resource "aws_lb" "main" {
  name               = "${local.name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
}

resource "aws_lb_target_group" "target" {
  name        = "${local.name}-tg"
  port        = 8001
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.target.arn
  }
}

# ECS -------------------------------------------------------------------------

resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_task_definition" "target" {
  family                   = "${local.name}-target"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.target_task.arn

  container_definitions = jsonencode([{
    name      = "target-app"
    image     = "${aws_ecr_repository.target_app.repository_url}:latest"
    essential = true
    portMappings = [{ containerPort = 8001, protocol = "tcp" }]
    environment = [
      { name = "TARGET_APP_PORT", value = "8001" },
      { name = "TARGET_APP_CPU_BURN_MS", value = "40" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.target.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "target"
      }
    }
  }])
}

resource "aws_ecs_service" "target" {
  name            = "${local.name}-target"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.target.arn
  desired_count   = var.target_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.target.arn
    container_name   = "target-app"
    container_port   = 8001
  }

  lifecycle {
    ignore_changes = [desired_count] # managed at runtime by the autoscaler
  }
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "${local.name}-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.controller_task.arn

  container_definitions = jsonencode([{
    name      = "backend"
    image     = "${aws_ecr_repository.backend.repository_url}:latest"
    essential = true
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment = [
      { name = "ELASTICMIND_ACTUATOR", value = "aws" },
      { name = "ELASTICMIND_ENV", value = var.environment },
      { name = "ELASTICMIND_DB_URL", value = "sqlite:////data/elasticmind.db" },
      { name = "ELASTICMIND_ECS_CLUSTER", value = aws_ecs_cluster.main.name },
      { name = "ELASTICMIND_ECS_SERVICE", value = aws_ecs_service.target.name },
      { name = "ELASTICMIND_MODEL_S3_URI", value = "s3://${aws_s3_bucket.artifacts.bucket}/${var.model_s3_prefix}/lightgbm.joblib" },
      { name = "ELASTICMIND_AWS_ALB_LOAD_BALANCER", value = aws_lb.main.arn_suffix },
      { name = "ELASTICMIND_AWS_ALB_TARGET_GROUP", value = aws_lb_target_group.target.arn_suffix },
      { name = "ELASTICMIND_AWS_TELEMETRY_PERIOD_S", value = "60" },
      { name = "ELASTICMIND_AWS_TELEMETRY_STALE_AFTER_S", value = "180" },
      { name = "ELASTICMIND_MIN_REPLICAS", value = tostring(var.target_min_count) },
      { name = "ELASTICMIND_MAX_REPLICAS", value = tostring(var.target_max_count) },
      { name = "AWS_REGION", value = var.aws_region },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.backend.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "backend"
      }
    }
  }])
}

resource "aws_ecs_service" "backend" {
  name            = "${local.name}-backend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = var.backend_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true
  }
}
