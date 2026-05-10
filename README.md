# Portfolio Tracker & Analyzer

A simple, local-first stock portfolio tracker with technical analysis. Runs as a Streamlit web app on your laptop.

## Features

**Dashboard**
- Total value, cost basis, P&L (absolute and %)
- Allocation pie chart
- Per-position P&L bar chart
- Holdings table with current prices

**Manage Holdings**
- Add holdings (ticker, shares, purchase price, date) with ticker validation
- Remove holdings with one click

**Stock Analysis** (per stock)
- Candlestick chart with overlays: SMA 20/50/200, EMA 20, Bollinger Bands
- Volume bars
- RSI (14) with overbought/oversold lines
- MACD with histogram
- Per-stock metrics: period return, annualized volatility, Sharpe, max drawdown
- Company info: sector, industry, market cap, P/E, dividend yield, beta

**Performance**
- Portfolio value over time (1mo–5y)
- Comparison vs S&P 500 (normalized)
- Risk metrics: volatility, Sharpe, max drawdown, beta vs SPY
- Daily returns distribution

## Setup

```bash
# 1. Install dependencies (Python 3.9+ recommended)
pip install -r requirements.txt

# 2. Run the app
streamlit run app.py
```

Open http://localhost:8501 in your browser.

## Project Structure

```
portfolio-tracker/
├── app.py                  # Main Streamlit app (the 4 pages)
├── requirements.txt
├── README.md
├── data/
│   └── portfolio.json      # Your holdings live here
└── src/
    ├── portfolio.py        # Load / save / add / remove holdings
    ├── data_fetcher.py     # yfinance wrapper with caching
    ├── analytics.py        # Portfolio metrics & risk
    └── indicators.py       # SMA, EMA, RSI, MACD, Bollinger
```

## Adding Holdings

Two options:

1. **In the app:** Use the "Manage Holdings" page.
2. **Edit the JSON directly:** `data/portfolio.json`

```json
{
  "holdings": [
    {
      "ticker": "AAPL",
      "shares": 10,
      "purchase_price": 150.0,
      "purchase_date": "2024-01-15"
    }
  ]
}
```

The repo ships with sample holdings (AAPL, MSFT, VOO) — replace with your own or delete the file (the app will handle the empty state).

## Indicator Cheat-Sheet

| Indicator | What it tells you |
|-----------|-------------------|
| **SMA / EMA** | Trend direction. Price above MA = uptrend, below = downtrend. SMA 50/200 cross = "golden/death cross". |
| **RSI (14)** | Momentum. >70 overbought, <30 oversold. |
| **MACD** | Momentum + trend. Histogram crossing zero = momentum shift. |
| **Bollinger Bands** | Volatility envelope. Price near upper band = stretched up; near lower = stretched down. |
| **Sharpe Ratio** | Return per unit of risk. >1 good, >2 great. Uses 4% risk-free rate. |
| **Max Drawdown** | Largest peak-to-trough loss. |
| **Beta vs SPY** | Sensitivity to S&P 500. 1.0 = moves with market, >1 = more volatile, <1 = less. |

## Notes

- Yahoo Finance data has a ~15min delay on the free feed.
- API responses are cached for 5 min to avoid rate-limit issues.
- Performance history assumes you held *current* share counts for the entire selected period — it's a "how would my current book have done?" view, not a true time-weighted return for partial periods.
- This is for personal portfolio tracking, not investment advice.
