import json
import boto3
import logging
import os
import urllib.request
import time
from datetime import date, timedelta, datetime
from boto3.dynamodb.conditions import Key, Attr

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

def fetch_finnhub_quote(ticker, finnhub_key):
    url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={finnhub_key}"
    req = urllib.request.Request(url, headers={'User-Agent': 'stock-watchlist/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
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
        logger.error(f"Finnhub quote error for {ticker}: {str(e)}")
        return None

def fetch_all_live_quotes(finnhub_key):
    quotes = []
    for ticker in WATCHLIST:
        q = fetch_finnhub_quote(ticker, finnhub_key)
        quotes.append(q if q else {'ticker': ticker, 'error': True})
        time.sleep(0.2)
    return quotes

def fetch_yahoo_candles(ticker, range_str):
    yahoo_params = {
        '1D': ('1d',  '5m'),
        '5D': ('5d',  '1d'),
        '1M': ('1mo', '1d'),
        '1Y': ('1y',  '1d'),
        '5Y': ('5y',  '1wk'),
    }.get(range_str, ('1mo', '1d'))
    yahoo_range, yahoo_interval = yahoo_params
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?interval={yahoo_interval}&range={yahoo_range}"
    )
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
        result    = data['chart']['result'][0]
        timestamps = result['timestamp']
        closes     = result['indicators']['quote'][0]['close']
        opens      = result['indicators']['quote'][0]['open']
        candles = []
        for i in range(len(timestamps)):
            if closes[i] is not None and opens[i] is not None:
                candles.append({
                    't': timestamps[i],
                    'c': round(closes[i], 2),
                    'o': round(opens[i],  2),
                })
        logger.info(f"Yahoo returned {len(candles)} candles for {ticker} {range_str}")
        return candles
    except Exception as e:
        logger.error(f"Yahoo Finance error for {ticker} {range_str}: {str(e)}")
        return []

def get_candles_from_dynamo(table, ticker, range_str):
    if range_str == '1D':
        return fetch_yahoo_candles(ticker, '1D')

    min_points = {'5D': 5, '1M': 20, '1Y': 200, '5Y': 200}.get(range_str, 20)
    days_back  = {'5D': 15, '1M': 45, '1Y': 400, '5Y': 1900}.get(range_str, 45)
    max_points = {'5D': 5,  '1M': 30, '1Y': 252, '5Y': 260}.get(range_str, 30)

    cutoff = str(date.today() - timedelta(days=days_back))
    try:
        response = table.scan(
            FilterExpression=Attr('ticker').eq(ticker) & Attr('date').gte(cutoff)
        )
        items = response.get('Items', [])
        items.sort(key=lambda x: x['date'])
        candles = []
        for item in items:
            try:
                d = datetime.strptime(item['date'], '%Y-%m-%d')
                candles.append({
                    't': int(d.timestamp()),
                    'c': float(item['close_price']),
                    'o': float(item['open_price']),
                })
            except Exception:
                pass
        candles = candles[-max_points:] if len(candles) > max_points else candles
    except Exception as e:
        logger.error(f"DynamoDB candle error for {ticker} {range_str}: {str(e)}")
        candles = []

    # Fall back to Yahoo Finance if not enough local data
    if len(candles) < min_points:
        logger.info(f"Only {len(candles)} DynamoDB points for {ticker} {range_str}, using Yahoo")
        candles = fetch_yahoo_candles(ticker, range_str)

    return candles

def calculate_momentum(candles):
    if len(candles) < 5:
        return {
            'signal':      'INSUFFICIENT_DATA',
            'label':       'Not enough data',
            'description': 'Insufficient price history to calculate momentum.',
        }
    closes  = [c['c'] for c in candles[-5:]]
    pct_5   = ((closes[-1] - closes[0]) / closes[0] * 100) if closes[0] else 0
    up_days = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
    dn_days = len(closes) - 1 - up_days

    if pct_5 > 3 and up_days >= 4:
        signal, label = 'STRONG_UP',   'Strong Upward Momentum'
        desc = f'Up {pct_5:.1f}% over the last 5 sessions with {up_days}/4 up days. Short-term trend is firmly positive.'
    elif pct_5 > 1 and up_days >= 3:
        signal, label = 'MILD_UP',     'Mild Upward Momentum'
        desc = f'Up {pct_5:.1f}% over the last 5 sessions. Modest positive short-term trend.'
    elif pct_5 < -3 and dn_days >= 4:
        signal, label = 'STRONG_DOWN', 'Strong Downward Momentum'
        desc = f'Down {abs(pct_5):.1f}% over the last 5 sessions with {dn_days}/4 down days. Short-term trend is firmly negative.'
    elif pct_5 < -1 and dn_days >= 3:
        signal, label = 'MILD_DOWN',   'Mild Downward Momentum'
        desc = f'Down {abs(pct_5):.1f}% over the last 5 sessions. Modest negative short-term trend.'
    else:
        signal, label = 'NEUTRAL',     'Neutral / Sideways'
        desc = f'Mixed price action over the last 5 sessions ({pct_5:+.1f}%). No clear short-term directional bias.'

    return {
        'signal':      signal,
        'label':       label,
        'description': desc,
        'pct_5day':    round(pct_5, 2),
        'up_days':     up_days,
        'down_days':   dn_days,
    }

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

def is_market_open():
    now    = datetime.utcnow()
    et_off = -4 if 3 <= now.month <= 11 else -5
    et     = now + timedelta(hours=et_off)
    if et.weekday() >= 5:
        return False
    et_time = et.hour + et.minute / 60
    return 9.5 <= et_time < 16.0

def lambda_handler(event, context):
    dynamodb = boto3.resource('dynamodb', region_name=REGION)
    table    = dynamodb.Table(TABLE_NAME)
    params   = event.get('queryStringParameters') or {}

    try:
        secrets     = get_secrets()
        massive_key = secrets.get('api_key')
        finnhub_key = secrets.get('finnhub_key')
    except Exception as e:
        logger.error(f"Could not load secrets: {str(e)}")
        return build_response(500, {'error': 'Configuration error'})

    # chart data for specific ticker and range (e.g. ?ticker=AAPL&range=1M). Range defaults to 1M if not provided. Momentum signal is based on last 5 closes within the selected range. Only fetches from Finnhub, no caching, since this is for interactive charting and not the main watchlist table. If you want to add caching here, consider using a separate DynamoDB table with a short TTL to avoid cluttering the main watchlist data.
    ticker_param = params.get('ticker')
    range_param  = params.get('range', '1M')
    if ticker_param:
        ticker   = ticker_param.upper()
        candles  = get_candles_from_dynamo(table, ticker, range_param)
        momentum = calculate_momentum(candles)
        return build_response(200, {
            'ticker':   ticker,
            'range':    range_param,
            'candles':  candles,
            'momentum': momentum,
        })

    # Date-specific data for watchlist table (\date=2024-06-01). Checks cache first, then Massive if not found.
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
            return build_response(200, {'movers': [], 'message': f'No data for {requested_date}'})

        def safe_pct(it):
            try: return abs(float(it['percentage_change']))
            except: return 0
        selected      = max(items, key=safe_pct)
        history       = get_history(table)
        history_dates = {m['date'] for m in history}
        if requested_date not in history_dates:
            history.extend(items)
            history.sort(key=lambda x: (x['date'], x['ticker']), reverse=True)
        return build_response(200, {'movers': history, 'selected': selected, 'source': 'cache'})

    # Historical data for watchlist table (most recent 5 trading days).
    history = get_history(table)
    if is_market_open() and finnhub_key:
        logger.info("Market open — fetching live Finnhub quotes")
        quotes = fetch_all_live_quotes(finnhub_key)
        return build_response(200, {'quotes': quotes, 'movers': history, 'live': True})
    else:
        logger.info("Market closed — returning stored data")
        return build_response(200, {'movers': history, 'live': False})