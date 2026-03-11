variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix for all resource names"
  type        = string
  default     = "stock-watchlist"
}

variable "secret_name" {
  description = "AWS Secrets Manager secret name"
  type        = string
  default     = "stock-watchlist/massive-api-key"
}