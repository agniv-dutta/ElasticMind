# CloudWatch dashboard: predicted vs actual load, capacity, forecast error, SLA, cost.
# CloudWatch is the ONLY monitoring tool used (no Grafana/Prometheus).

locals {
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Predicted vs Actual Load (ElasticMind)"
          region = var.aws_region
          view   = "timeSeries"
          metrics = [
            ["ElasticMind", "PredictedLoad", "Service", "elasticmind-target"],
            ["ElasticMind", "ActualLoad", "Service", "elasticmind-target"],
          ]
          period = 60
          stat   = "Average"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Capacity: Desired vs Running"
          region = var.aws_region
          view   = "timeSeries"
          metrics = [
            ["ElasticMind", "DesiredCapacity", "Service", "elasticmind-target"],
            ["ElasticMind", "RunningCapacity", "Service", "elasticmind-target"],
          ]
          period = 60
          stat   = "Maximum"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "Forecast Error (MAPE %)"
          region = var.aws_region
          view   = "timeSeries"
          metrics = [
            ["ElasticMind", "ForecastMAPE", "Service", "elasticmind-target"],
          ]
          period = 60
          stat   = "Average"
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "SLA Violations"
          region = var.aws_region
          view   = "timeSeries"
          metrics = [
            ["ElasticMind", "SLAViolations", "Service", "elasticmind-target"],
          ]
          period = 60
          stat   = "Sum"
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "Estimated Cost (simulated)"
          region = var.aws_region
          view   = "timeSeries"
          metrics = [
            ["ElasticMind", "EstimatedCost", "Service", "elasticmind-target"],
          ]
          period = 60
          stat   = "Average"
        }
      },
    ]
  })
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${local.name}-overview"
  dashboard_body = local.dashboard_body
}
