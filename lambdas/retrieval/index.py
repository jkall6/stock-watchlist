import json
import boto3
import logging
import os
import urllib.request
import time
from datetime import date, timedelta
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME  = os.environ["DYNAMODB_TABLE"]
SECRET_NAME = os.environ["SECRET_NAME"]
REGION      = os.environ.get("AWS_REGION", "us-east-1")
WATCHLIST   = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA']


def build_response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
        },
        'body': json.dumps(body)
    }


def get_secrets():
    client = boto3.client('secretsmanager', region_name=REGION)
    response = client.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(response['SecretString'])


# Finnhub live quote
def fetch_finnhub_quote(ticker, finnhub_key):
    url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={finnhub_key}"
    req = urllib.request.Request(url, headers={'User-Agent': 'stock-watchlist/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            # c=current price, o=open, pc=prev close, h=high, l=low
            if not data.get('c'):
                return None
            price      = data['c']
            open_price = data['o']
            prev_close = data['pc']
            change_pct = ((price - open_price) / open_price * 100) if open_price else 0
            return {
                'ticker':            ticker,
                'price':             round(price,      2),
                'open_price':        round(open_price, 2),
                'close_price':       round(price,      2), 
                'prev_close':        round(prev_close, 2),
                'percentage_change': round(change_pct, 4),
                'live':              True,
            }
    except Exception as e:
        logger.error(f"Finnhub error for {ticker}: {str(e)}")
        return None


def fetch_all_live_quotes(finnhub_key):
    quotes = []
    for ticker in WATCHLIST:
        q = fetch_finnhub_quote(ticker, finnhub_key)
        if q:
            quotes.append(q)
        else:
            quotes.append({'ticker': ticker, 'error': True})
        time.sleep(0.2) 
    return quotes


# DynamoDB queries
def get_items_for_date(table, target_date):
    try:
        response = table.query(
            KeyConditionExpression=Key('date').eq(target_date)
        )
        return response.get('Items', [])
    except Exception as e:
        logger.error(f"DynamoDB query error for {target_date}: {str(e)}")
        return []


def get_history(table, num_days=14, limit_dates=5):
    found_dates = []
    all_items   = []
    for i in range(1, num_days + 1):
        d     = str(date.today() - timedelta(days=i))
        items = get_items_for_date(table, d)
        if items:
            found_dates.append(d)
            all_items.extend(items)
        if len(found_dates) >= limit_dates:
            break
    all_items.sort(key=lambda x: (x['date'], x['ticker']), reverse=True)
    return all_items


# Check if market is currently open (weekdays 9:30-16:00 ET). Used to determine whether to fetch live quotes or rely on cached data.
def is_market_open():
    import datetime
    now     = datetime.datetime.utcnow()
    # Approximate DST: EDT (UTC-4) Mar-Nov, EST (UTC-5) Nov-Mar
    month   = now.month
    et_off  = -4 if 3 <= month <= 11 else -5
    et      = now + datetime.timedelta(hours=et_off)
    weekday = et.weekday()  # 0=Mon, 6=Sun
    if weekday >= 5:
        return False
    et_time = et.hour + et.minute / 60
    return 9.5 <= et_time < 16.0

def fetch_from_massive_all(target_date, api_key):
    results = []
    for ticker in WATCHLIST:
        url = f"https://api.massive.com/v1/open-close/{ticker}/{target_date}?apiKey={api_key}"
        req = urllib.request.Request(url, headers={'User-Agent': 'stock-watchlist/1.0'})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
            open_price  = float(data['open'])
            close_price = float(data['close'])
            pct = ((close_price - open_price) / open_price * 100) if open_price else 0
            results.append({
                'date':              target_date,
                'ticker':            ticker,
                'percentage_change': str(round(pct,         4)),
                'open_price':        str(round(open_price,  2)),
                'close_price':       str(round(close_price, 2))
            })
        except Exception as e:
            logger.warning(f"Could not fetch {ticker} from Massive: {str(e)}")
        time.sleep(0.5)
    return results

# Lambda handler: supports two modes — if ?date=YYYY-MM-DD is provided, looks up that date. Otherwise, returns recent history and live quotes if market is open.
def lambda_handler(event, context):
    dynamodb = boto3.resource('dynamodb', region_name=REGION)
    table    = dynamodb.Table(TABLE_NAME)
    params   = event.get('queryStringParameters') or {}

    try:
        secrets      = get_secrets()
        massive_key  = secrets.get('api_key')
        finnhub_key  = secrets.get('finnhub_key')
    except Exception as e:
        logger.error(f"Could not load secrets: {str(e)}")
        return build_response(500, {'error': 'Configuration error'})

    # Lookup for specific date: check cache first, then Massive API fallback if not found. Returns the single biggest mover for that date, along with the full history (including the newly fetched data if we had to go to Massive).
    requested_date = params.get('date')
    if requested_date:
        items = get_items_for_date(table, requested_date)

        if not items:
            logger.info(f"{requested_date} not in DB, fetching from Massive")
            items = fetch_from_massive_all(requested_date, massive_key)
            if items:
                for item in items:
                    try:
                        table.put_item(Item=item)
                    except Exception as e:
                        logger.warning(f"Could not save {item['ticker']}: {str(e)}")

        if not items:
            return build_response(200, {
                'movers':  [],
                'message': f'No data for {requested_date}'
            })

        def safe_pct(it):
            try: return abs(float(it['percentage_change']))
            except: return 0
        selected = max(items, key=safe_pct)

        history = get_history(table)
        history_dates = {m['date'] for m in history}
        if requested_date not in history_dates:
            history.extend(items)
            history.sort(key=lambda x: (x['date'], x['ticker']), reverse=True)

        return build_response(200, {
            'movers':   history,
            'selected': selected,
            'source':   'cache'
        })

    # Historical data for watchlist table (most recent 5 trading days).
    history = get_history(table)

    # Live quotes during market hours, stored data otherwise
    if is_market_open() and finnhub_key:
        logger.info("Market open — fetching live Finnhub quotes")
        quotes = fetch_all_live_quotes(finnhub_key)
        return build_response(200, {
            'quotes':  quotes,   # live watchlist cards
            'movers':  history,  # historical table
            'live':    True,
        })
    else:
        logger.info("Market closed — returning stored data")
        return build_response(200, {
            'movers': history,
            'live':   False,
        })