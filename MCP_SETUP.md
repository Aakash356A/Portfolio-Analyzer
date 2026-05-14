# MCP Setup Guide — Portfolio Analyzer

Connect your portfolio analyzer to **Claude Desktop** so you can just talk to Claude
and it will pull your live portfolio data, run technical analysis, fetch news, and
read SEC filings — all without opening the Streamlit app.

---

## What you get (8 tools Claude can call)

| Tool | What it does |
|------|-------------|
| `get_portfolio` | All holdings: live price, P&L, allocation weight |
| `get_portfolio_metrics` | Returns, Sharpe, max drawdown, beta vs S&P 500 |
| `get_technical_analysis` | RSI, MACD, SMA 20/50/200, Bollinger Bands, support/resistance |
| `get_fundamentals` | Valuation ratios, EPS history, next earnings date + estimate |
| `get_news` | Latest headlines from Yahoo Finance + Google News |
| `get_sec_filings` | Recent 8-K/10-K/10-Q filings from SEC EDGAR |
| `get_breaking_news` | All fast sources scored by market impact (1–10) |
| `compare_stocks` | Side-by-side multi-stock comparison |

---

## Step 1: Confirm `mcp` is installed

```bash
conda activate portfolio
pip install mcp
```

---

## Step 2: Edit the Claude Desktop config

Open this file (create it if it doesn't exist):

**Mac:** `~/Library/Application Support/Claude/claude_desktop_config.json`

Paste exactly this (paths are already filled in for your machine):

```json
{
  "mcpServers": {
    "portfolio-analyzer": {
      "command": "/opt/anaconda3/envs/portfolio/bin/python",
      "args": ["/Users/aakashdivakar/Downloads/Idea/portfolio-analyzer/mcp_server.py"]
    }
  }
}
```

> If you already have other MCP servers in the config, add the `"portfolio-analyzer"` block
> inside the existing `"mcpServers"` object — don't replace the whole file.

---

## Step 3: Restart Claude Desktop

Fully quit (⌘Q) and reopen. Look for the **🔨 hammer icon** in the chat input bar.
Click it — you should see 8 tools listed under "portfolio-analyzer".

---

## Step 4: Try it

```
"Give me a full review of my portfolio this week."
"What's the technical setup for AMD right now — daily and weekly?"
"Any breaking news or SEC filings for my holdings today?"
"Compare GOOGL, META, and AMZN — which looks best technically?"
"What are the upcoming earnings dates for my holdings?"
"How is my portfolio performing vs the S&P 500 over the last 3 months?"
```

---

## Troubleshooting

**Hammer icon not showing:**
- JSON syntax error in the config — validate at [jsonlint.com](https://jsonlint.com)
- Run manually to see the error: `/opt/anaconda3/envs/portfolio/bin/python mcp_server.py`

**"No module named 'src'":**
- The `args` must use the full absolute path to `mcp_server.py` (already done above)

**Tools return errors / stale data:**
- `yfinance` sometimes rate-limits — wait 30 seconds and retry
- Make sure your `.env` file has a valid `OPENROUTER_API_KEY` (only needed if you ask Claude to generate AI memos directly, not for the data tools)

**`@st.cache_data` warnings in console:**
- Harmless. Outside Streamlit, the cache decorators just run the functions without caching.
