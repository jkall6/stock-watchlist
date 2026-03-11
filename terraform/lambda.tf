resource "aws_lambda_function" "ingestion" {
  function_name    = "${var.project_name}-ingestion"
  filename         = "${path.module}/ingestion.zip"
  source_code_hash = filebase64sha256("${path.module}/ingestion.zip")
  handler          = "index.lambda_handler"
  runtime          = "python3.11"
  role             = aws_iam_role.lambda_exec.arn
  timeout          = 30

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.movers.name
      SECRET_NAME    = var.secret_name
    }
  }

  tags = {
    Project = var.project_name
  }
}

resource "aws_lambda_function" "retrieval" {
  function_name    = "${var.project_name}-retrieval"
  filename         = "${path.module}/retrieval.zip"
  source_code_hash = filebase64sha256("${path.module}/retrieval.zip")
  handler          = "index.lambda_handler"
  runtime          = "python3.11"
  role             = aws_iam_role.lambda_exec.arn
  timeout          = 30

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.movers.name
      SECRET_NAME    = var.secret_name
    }
  }

  tags = {
    Project = var.project_name
  }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.retrieval.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingestion.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_cron.arn
}