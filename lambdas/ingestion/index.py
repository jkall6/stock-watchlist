from datetime import date, timedelta
import json
import logging
import os
import urllib.request
import boto3
import time

logger = logging.getLogger()
logger.setLevel(logging.INFO)

WATCHLIST = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA']
TABLE_NAME = os.environ["DYNAMODB_TABLE"]
SECRET_NAME = os.environ["SECRET_NAME"]
REGION = os.environ.get("AWS_REGION", "us-east-1")


def get_api_key():
    client = boto3.client('secretsmanager', region_name=REGION)
    response = client.get_secret_value(SecretId=SECRET_NAME)
    secret = json.loads(response['SecretString'])
    return secret["api_key"]


def get_stock_info(ticker, api_key, target_date, retries=3):
    url = f"https://api.massive.com/v1/open-close/{ticker}/{target_date}?apiKey={api_key}"
    req = urllib.request.Request(url, headers={'User-Agent': 'stock-watchlist/1.0'})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                return data
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(f"Rate limited on {ticker}, retrying in {wait}s (attempt {attempt+1}/{retries})")
                time.sleep(wait)
                continue
            logger.error(f"HTTP error for {ticker} on {target_date}: {e.code} - {e.reason}")
            return None
        except Exception as e:
            logger.error(f"Error fetching data for {ticker} on {target_date}: {str(e)}")
            return None
    logger.error(f"All retries exhausted for {ticker}")
    return None


def calculate_percentage_change(open_price, close_price):
    if open_price == 0:
        return 0
    return ((close_price - open_price) / open_price) * 100


def lambda_handler(event, context):
    target_date = event.get("test_date") or str(date.today() - timedelta(days=1))
    day_of_week = date.fromisoformat(target_date).weekday()

    if day_of_week >= 5:
        logger.info(f"Skipping {target_date} - weekend, markets closed.")
        return {'statusCode': 200, 'body': json.dumps(f"Skipped {target_date} - weekend")}

    try:
        api_key = get_api_key()
    except Exception as e:
        logger.error(f"Error retrieving API key: {str(e)}")
        raise

    results = []
    for ticker in WATCHLIST:
        stock_info = get_stock_info(ticker, api_key, target_date)
        time.sleep(0.5)
        if not stock_info:
            logger.warning(f"No data returned for {ticker} on {target_date}")
            continue
        try:
            open_price = float(stock_info['open'])
            close_price = float(stock_info['close'])
            percentage_change = calculate_percentage_change(open_price, close_price)
            results.append({
                'ticker': ticker,
                'open': open_price,
                'close': close_price,
                'percentage_change': percentage_change,
                'abs_change': abs(percentage_change)
            })
            logger.info(f"{ticker}: open={open_price}, close={close_price}, change={percentage_change:.2f}%")
        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Error processing {ticker}: {str(e)} | Raw: {stock_info}")
            continue

    if not results:
        logger.warning(f"No valid stock data for {target_date}")
        return {'statusCode': 200, 'body': json.dumps(f"No valid data for {target_date}")}

    dynamodb = boto3.resource('dynamodb', region_name=REGION)
    table = dynamodb.Table(TABLE_NAME)

    for stock in results:
        item = {
            "date": target_date,
            "ticker": stock['ticker'],
            "percentage_change": str(round(stock['percentage_change'], 4)),
            "open_price": str(round(stock['open'], 2)),
            "close_price": str(round(stock['close'], 2))
        }
        try:
            table.put_item(Item=item)
            logger.info(f"Saved {stock['ticker']} at {stock['percentage_change']:.2f}% on {target_date}")
        except Exception as e:
            logger.error(f"DynamoDB write error for {stock['ticker']}: {str(e)}")
            raise

    winner = max(results, key=lambda x: x['abs_change'])
    logger.info(f"Top mover: {winner['ticker']} at {winner['percentage_change']:.2f}% on {target_date}")
    return {'statusCode': 200, 'body': json.dumps(f"Saved {len(results)} tickers. Top mover: {winner['ticker']}")}