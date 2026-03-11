output "api_url" {
  value       = "${aws_api_gateway_stage.prod.invoke_url}/movers"
  description = "The REST API endpoint"
}

output "frontend_url" {
  value       = "http://${aws_s3_bucket_website_configuration.frontend.website_endpoint}"
  description = "The public S3 website URL"
}

output "s3_bucket_name" {
  value       = aws_s3_bucket.frontend.bucket
  description = "S3 bucket name for uploading the frontend"
}