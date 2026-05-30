# Portfolio Tracker & Analyzer

> **A stock portfolio tracker with a built-in MCP server for Claude Desktop — run it locally or deploy it as a hosted remote server.**
> Talk to Claude naturally — it pulls live prices, technicals, SEC filings, and news from your portfolio without you opening the app.

![Python](https://img.shields.io/badge/Python-3.9%2B-blue) ![Streamlit](https://img.shields.io/badge/Streamlit-app-red) ![MCP](https://img.shields.io/badge/MCP-Claude%20Desktop-blueviolet) ![License](https://img.shields.io/badge/license-MIT-green)

---

## What is this?

Two tools in one repo:

| | Tool | What it does |
|---|------|--------------|
| 📊 | **Streamlit web app** | Visual dashboard: charts, P&L, technicals, AI summaries |
| 🤖 | **MCP server** | Connects Claude Desktop (or any MCP client) to live market data |

Runs locally with zero cloud setup, or deploy in one click to Railway/Render so any MCP client can reach it over the internet.

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

---

## Option A — Local (stdio) Setup

Best for personal use with Claude Desktop. Your portfolio data stays on your machine.

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

**3. Add your holdings** to `data/portfolio.json` (see format below).

**4. Restart Claude Desktop** — look for the 🔨 hammer icon in the chat bar.

See [MCP_SETUP.md](MCP_SETUP.md) for the full guide including troubleshooting.

---

## Option B — Hosted / Remote Setup (Streamable HTTP)

Deploy the server so it's reachable over the internet. This lets you list it on MCP registries (mcp.so, Smithery, Glama) and use it from any MCP client without local installation.

### Deploy to Railway (free tier)

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**
3. Select your repo — Railway picks up `railway.json` and `Dockerfile` automatically
4. Click **Deploy**

Your server will be live at:
```
https://your-app.up.railway.app/mcp
```

### Deploy to Render (free tier)

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → **New → Web Service**
3. Connect your repo — Render picks up `render.yaml` automatically
4. Click **Create Web Service**

### Connect a remote MCP client

Once deployed, point any MCP client at:
```
https://your-app.up.railway.app/mcp
```

For Claude Desktop with remote MCP support:
```json
{
  "mcpServers": {
    "portfolio-analyzer": {
      "type": "streamable-http",
      "url": "https://your-app.up.railway.app/mcp"
    }
  }
}
```

### Passing your portfolio to the hosted server

On the hosted server there is no local file, so you pass your holdings directly when calling `get_portfolio` or `get_portfolio_metrics`:

```json
{
  "portfolio_json": "{\"holdings\": [{\"ticker\": \"AAPL\", \"shares\": 10, \"purchase_price\": 150.0, \"purchase_date\": \"2024-01-15\"}]}"
}
```

All other tools — technicals, fundamentals, news, SEC filings, compare — only need a ticker and work the same in both modes.

### Run in HTTP mode locally (for testing)

```bash
MCP_TRANSPORT=streamable-http PORT=8000 python mcp_server.py
```

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
├── mcp_server.py        # MCP server — stdio or Streamable HTTP
├── requirements.txt
├── Dockerfile           # For hosted deployment
├── railway.json         # Railway one-click deploy
├── render.yaml          # Render one-click deploy
├── .env.example         # API key template
├── data/
│   ├── portfolio.json   # Your holdings (local mode)
│   └── summaries/       # Saved AI summaries
└── src/
    ├── analytics.py     # Portfolio metrics & risk
    ├── data_fetcher.py  # yfinance wrapper with caching
    ├── indicators.py    # SMA, EMA, RSI, MACD, Bollinger
    ├── llm.py           # Claude Sonnet 4.6 via OpenRouter
    ├── news_monitor.py  # Multi-source news fetcher + scorer
    ├── portfolio.py     # Load / save / add / remove holdings
    ├── sec_edgar.py     # SEC EDGAR API client
    └── summary_pipeline.py  # Weekly/daily/monthly memo pipeline
```

## Adding Holdings (local mode)

**In the app:** Use the "Manage Holdings" page. You can manually enter positions or **upload a CSV export** from your broker (e.g., Robinhood, Fidelity, Schwab, Vanguard) to automatically import your holdings.

**If your broker's CSV isn't supported:** You can easily generate the `portfolio.json` file using any AI assistant (like Claude or ChatGPT). Just attach your CSV and ask it to *"Convert my brokerage CSV into this JSON format:"*.

**Or edit directly:** `data/portfolio.json`

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
