# Portfolio Tracker & Analyzer

> **A local-first stock portfolio tracker with a built-in MCP server for Claude Desktop.**
> Talk to Claude naturally — it pulls live prices, technicals, SEC filings, and news from your portfolio without you opening the app.

![Python](https://img.shields.io/badge/Python-3.9%2B-blue) ![Streamlit](https://img.shields.io/badge/Streamlit-app-red) ![MCP](https://img.shields.io/badge/MCP-Claude%20Desktop-blueviolet) ![License](https://img.shields.io/badge/license-MIT-green)

---

## What is this?

Two tools in one repo:

| | Tool | What it does |
|---|------|--------------|
| 📊 | **Streamlit web app** | Visual dashboard: charts, P&L, technicals, AI summaries |
| 🤖 | **MCP server** | Connects Claude Desktop to your live portfolio data |

No cloud. No subscription beyond your own API keys. Runs entirely on your machine.

---

## MCP Server — Talk to Claude About Your Portfolio

Once connected, just ask Claude:

```
"Give me a full review of my portfolio this week."
"What's the technical setup for NVDA right now?"
"Any breaking news or SEC filings for my holdings today?"
"Compare GOOGL, META, and AMZN — which looks best technically?"
"What are the upcoming earnings dates for my holdings?"
```

Claude calls the right tools, fetches live data, and writes the analysis — all using your existing Claude subscription.

### 8 tools Claude can call

| Tool | What it does |
|------|--------------|
| `get_portfolio` | All holdings: live price, P&L, allocation weight |
| `get_portfolio_metrics` | Returns, Sharpe, max drawdown, beta vs S&P 500 |
| `get_technical_analysis` | RSI, MACD, SMA 20/50/200, Bollinger Bands, support/resistance |
| `get_fundamentals` | Valuation ratios, EPS beat/miss history, next earnings date |
| `get_news` | Latest headlines from Yahoo Finance + Google News |
| `get_sec_filings` | Recent 8-K/10-K/10-Q filings from SEC EDGAR |
| `get_breaking_news` | All fast sources scored by market impact (1–10) |
| `compare_stocks` | Side-by-side multi-stock comparison |

> The technical analysis, news, SEC, and comparison tools work for **any ticker** — not just your portfolio holdings.

### MCP Quick Setup

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Edit the Claude Desktop config**

Mac: `~/Library/Application Support/Claude/claude_desktop_config.json`
Windows: `%APPDATA%/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "portfolio-analyzer": {
      "command": "python",
      "args": ["/FULL/PATH/TO/portfolio-analyzer/mcp_server.py"]
    }
  }
}
```

**3. Restart Claude Desktop** — look for the 🔨 hammer icon in the chat bar.

See [MCP_SETUP.md](MCP_SETUP.md) for the full guide including troubleshooting.

---

## Streamlit App

### Setup

```bash
# 1. Install dependencies (Python 3.9+)
pip install -r requirements.txt

# 2. Add your OpenRouter API key (for AI summaries)
cp .env.example .env
# Edit .env and add your key from https://openrouter.ai/settings/keys

# 3. Run
streamlit run app.py
```

Open http://localhost:8501 in your browser.

### Pages

**Dashboard** — Total value, cost basis, P&L, allocation pie chart, holdings table

**Manage Holdings** — Add/remove positions with ticker validation

**Stock Analysis** — Candlestick chart with SMA/EMA/Bollinger overlays, RSI, MACD, volume, fundamentals, and an AI memo (Claude Sonnet 4.6)

**Performance** — Portfolio vs S&P 500 (normalized), volatility, Sharpe, drawdown, beta, returns distribution

**Summary** — Claude Sonnet 4.6 writes a personal investment memo (daily / weekly / monthly) covering winners/losers, SEC events, macro themes, and recommendations

**Monitor** — Real-time news alerts from SEC EDGAR, Business Wire, PR Newswire, Yahoo, and Google News — scored by market impact

---

## Project Structure

```
portfolio-analyzer/
├── app.py               # Streamlit app (6 pages)
├── mcp_server.py        # MCP server for Claude Desktop
├── requirements.txt
├── .env.example         # API key template
├── data/
│   ├── portfolio.json   # Your holdings
│   └── summaries/       # Saved AI summaries
└── src/
    ├── analytics.py     # Portfolio metrics & risk
    ├── data_fetcher.py  # yfinance wrapper with caching
    ├── indicators.py    # SMA, EMA, RSI, MACD, Bollinger
    ├── llm.py           # Claude Sonnet 4.6 via OpenRouter
    ├── news_monitor.py  # Multi-source news fetcher + scorer
    ├── portfolio.py     # Load / save / add / remove holdings
    ├── sec_edgar.py     # SEC EDGAR API client
    ├── snaptrade_integration.py  # Auto-import holdings from your brokerage
    └── summary_pipeline.py  # Weekly/daily/monthly memo pipeline
```

## Adding Holdings

There are three ways to get your positions into the tracker. Pick whichever you prefer.

### Option 1 — Auto-connect your brokerage (SnapTrade) ⭐ recommended

Connect your broker once and import your **real positions** (shares + cost basis)
automatically — no CSVs, no manual typing. Works with Robinhood, Fidelity, Schwab,
Vanguard, E\*TRADE, Webull, Wealthsimple, and many more.

**1. Create a free SnapTrade account**
Sign up at [dashboard.snaptrade.com](https://dashboard.snaptrade.com) and verify your
email. The free tier gives real brokerage data for a personal account at no cost.

**2. Generate an API key** in the dashboard — you'll get a **Client ID** and a
**Consumer Key**.

**3. Add them to your `.env`:**
```
SNAPTRADE_CLIENT_ID=your-snaptrade-client-id
SNAPTRADE_CONSUMER_KEY=your-snaptrade-consumer-key
```

**4. Install the SDK** (already included if you ran `pip install -r requirements.txt`):
```bash
pip install snaptrade-python-sdk
```

**5. In the app:** open the **🏦 Connect Brokerage** tab on the Manage Holdings page →
**Connect Brokerage**. A SnapTrade window opens; log into your broker there. Back in the
app, click **Check Connection**, then **🔄 Sync Holdings** to import.

> Your broker credentials go directly to SnapTrade and never touch this app.
> Your SnapTrade user secret is stored locally in `data/.snaptrade_user.json` (gitignored).
> Note: SnapTrade provides shares + average cost basis, but not the original lot
> purchase *date*, so imported positions use a placeholder date. Your P&L is accurate.

### Option 2 — Upload a CSV export

On the Manage Holdings page, use the **📥 Import CSV** tab to upload a holdings export
from your broker (Robinhood, Fidelity, Schwab, Vanguard, etc.). The app standardizes
common brokerage CSV formats automatically.

**If your broker's CSV isn't supported:** You can easily generate the `portfolio.json`
file using any AI assistant (like Claude or ChatGPT). Just attach your CSV and ask it to
*"Convert my brokerage CSV into this JSON format:"*.

### Option 3 — Manual entry / edit the file

Use the **🟢 Buy** / **🔴 Sell** tabs on the Manage Holdings page, or edit
`data/portfolio.json` directly:

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

---

## Indicator Cheat-Sheet

| Indicator | What it tells you |
|-----------|-------------------|
| **SMA / EMA** | Trend direction. Price above MA = uptrend. SMA 50/200 cross = "golden/death cross". |
| **RSI (14)** | Momentum. >70 overbought, <30 oversold. |
| **MACD** | Momentum + trend. Histogram crossing zero = momentum shift. |
| **Bollinger Bands** | Volatility envelope. Near upper = stretched up; near lower = stretched down. |
| **Sharpe Ratio** | Return per unit of risk. >1 good, >2 great. Uses 4% risk-free rate. |
| **Max Drawdown** | Largest peak-to-trough loss. |
| **Beta vs SPY** | Market sensitivity. >1 = more volatile than S&P 500. |

---

## Notes

- Yahoo Finance data has a ~15 min delay on the free feed.
- API responses are cached for 5 min to avoid rate-limit issues.
- Performance history assumes you held current share counts for the full selected period — it's a "how would my current book have done?" view, not a true time-weighted return.
- AI features require an [OpenRouter](https://openrouter.ai) API key. The MCP server uses your Claude Desktop subscription directly (no separate key needed).
- Not investment advice.
