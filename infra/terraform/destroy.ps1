# Safe teardown for Windows PowerShell. Usage: .\destroy.ps1
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "==> ElasticMind terraform destroy"
Write-Host "This removes the VPC, ECS cluster/services, ALB, ECR repos, S3 bucket,"
Write-Host "IAM roles, log groups and budget. Data in the artifacts bucket is deleted."
$confirm = Read-Host "Type 'destroy' to confirm"
if ($confirm -ne "destroy") {
    Write-Host "aborted"
    exit 1
}

terraform destroy
