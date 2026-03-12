# Stock Watchlist

An AWS application that tracks daily stock performance for `AAPL`, `MSFT`, `GOOGL`, `AMZN`, and `TSLA`. An EventBridge-scheduled Lambda fetches closing prices each weekday via the Massive API and stores all five stocks per date in DynamoDB. A second Lambda serves the data through API Gateway to a static frontend hosted on S3. During market hours, the frontend displays live quotes via Finnhub.

**Live demo:** `YOUR_S3_URL_HERE`

---

## Need Beforehand

- Terraform
- AWS CLI 
- Massive key
- Finnhub key

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
