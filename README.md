# Stock Watchlist

An AWS application that tracks daily stock performance for `AAPL`, `MSFT`, `GOOGL`, `AMZN`, and `TSLA`. An EventBridge-scheduled Lambda fetches closing prices each weekday via the Massive API and stores all five stocks per date in DynamoDB. A second Lambda serves the data through API Gateway to a static frontend hosted on S3. During market hours, the frontend displays live quotes via Finnhub.

**Live demo:** (http://stock-watchlist-frontend-28aaae23.s3-website-us-east-1.amazonaws.com/)

---

## Features
 
- Five watchlist cards showing close price, % change, open, and close — updated live every 5 minutes during market hours via Finnhub
- Gold badge on the card with the highest positive % gain each session
- Daily winners history table — one row per trading day, sortable by any column, paginated 5 rows per page
- Date picker to look up any past date — fetches from Massive if not already in the database, persists in the browser across refreshes
- Stock detail modal with a price chart (Yahoo Finance), crosshair hover showing exact price and % from range start, range stats, and a plain-English short-term momentum signal
- Fully automated deploys via GitHub Actions on every push to `main`

## Architecture
 
```
┌─────────────────────────────────────────────────────────┐
│                        AWS                              │
│                                                         │
│  EventBridge (weekdays 4pm ET)                          │
│       │                                                 │
│       ▼                                                 │
│  Lambda: Ingestion ──── Massive API (open/close prices) │
│       │                                                 │
│       ▼                                                 │
│  DynamoDB (date + ticker composite key)                 │
│       │                                                 │
│       ▼                                                 │
│  Lambda: Retrieval ◄─── API Gateway (GET /movers)       │
│       │                                                 │
│       ├── Default:   history from DynamoDB              │
│       │              + live quotes from Finnhub         │
│       ├── ?date=:    specific date lookup               │
│       │              (DynamoDB → Massive fallback)      │
│       └── ?ticker=:  chart candles from Yahoo Finance   │
│                      + momentum signal                  │
│                                                         │
│  S3 (static frontend: index.html)                       │
└─────────────────────────────────────────────────────────┘
```

### Data Sources
 
| Source | Used For |
|--------|----------|
| **Massive API** | Daily open/close ingestion (weekday cron) and on-demand date lookups |
| **Finnhub** | Live quotes during market hours (free tier: `/quote` endpoint only) |
| **Yahoo Finance** | Full chart history across all ranges (1D intraday through 5Y weekly) |

---

## Design Decisions
 
**Two Lambdas instead of one** — ingestion and retrieval are kept separate so the daily cron job is fully decoupled from frontend traffic. A failure or change in one doesn't affect the other.
 
**Composite DynamoDB key (date + ticker)** — allows efficient querying of all five tickers for a given date with a single `query` call rather than a scan. The ingestion Lambda always writes exactly five records per run.
 
**Three data sources** — Finnhub's free tier doesn't include historical point data, only live quotes. Massive covers daily open and close price for date lookups but would be too slow for full chart history (one call per day per stock). Yahoo Finance returns a full range in a single call at no cost, making it the right fit for charting. Each source fills a gap the others don't cover for free.
 
---

## Deploy

**1. Store API keys in Secrets Manager**

**2. Package Lambdas and apply infrastructure**

**3. Upload frontend**



## CI/CD (GitHub Actions)

Every push to main automatically packages the Lambdas, runs terraform apply, and uploads the frontend.

**1. Add secrets to GitHub**

Go to repo → Settings → Secrets and variables → Actions and add:

| Secret | Value |
|--------|-------|
| `AWS_ACCESS_KEY_ID` | Your AWS access key |
| `AWS_SECRET_ACCESS_KEY` | Your AWS secret key |

**2. Push to main**


See progress under the Actions tab.
