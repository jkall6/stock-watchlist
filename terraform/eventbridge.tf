resource "aws_cloudwatch_event_rule" "daily_cron" {
  name                = "${var.project_name}-daily-cron"
  description         = "Triggers ingestion Lambda daily after market close"
  schedule_expression = "cron(0 21 * * ? *)"

  tags = {
    Project = var.project_name
  }
}

resource "aws_cloudwatch_event_target" "ingestion_target" {
  rule      = aws_cloudwatch_event_rule.daily_cron.name
  target_id = "IngestionLambda"
  arn       = aws_lambda_function.ingestion.arn
}