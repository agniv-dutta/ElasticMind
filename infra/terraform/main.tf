terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }

  # Optional remote state (create the bucket + table first, then uncomment).
  # backend "s3" {
  #   bucket         = "elasticmind-tfstate"
  #   key            = "elasticmind/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "elasticmind-tflock"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "elasticmind"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name        = "elasticmind"
  account_id  = data.aws_caller_identity.current.account_id
  azs         = slice(data.aws_availability_zones.available.names, 0, 2)
  common_tags = {
    Project     = "elasticmind"
    Environment = var.environment
  }
}
