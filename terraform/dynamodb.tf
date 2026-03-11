resource "aws_dynamodb_table" "movers" {
  name         = "stock-watchlist-movers-v2"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "date"
  range_key    = "ticker"

  attribute {
    name = "date"
    type = "S"
  }

  attribute {
    name = "ticker"
    type = "S"
  }
}