# Portfolio Analyzer — Technical Documentation

## Table of Contents
1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Frontend](#3-frontend)
4. [Backend Modules](#4-backend-modules)
5. [Data Sources](#5-data-sources)
6. [AI / LLM Layer](#6-ai--llm-layer)
7. [Technical Indicators (Quant Layer)](#7-technical-indicators-quant-layer)
8. [Analytics Engine](#8-analytics-engine)
9. [Data Flow — Summary Pipeline](#9-data-flow--summary-pipeline)
10. [Caching Strategy](#10-caching-strategy)
11. [Storage](#11-storage)
12. [Dependencies](#12-dependencies)
13. [Pages & Features Reference](#13-pages--features-reference)

---

## 1. Overview

A personal stock portfolio tracker and AI-powered investment analyzer. It lets you manage a portfolio of equity holdings, view live prices and charts, run technical and fundamental analysis on individual stocks, get AI-generated fundamental memos and geopolitical risk assessments, monitor real-time news alerts, and generate periodic AI-written summaries with trading recommendations.

**Run with:**
```bash
streamlit run app.py
```

---

## 2. Architecture

```
app.py                      ← Streamlit frontend (single-page, multi-view)
│
├── src/portfolio.py        ← Holdings CRUD (load/save/add/remove)
├── src/data_fetcher.py     ← Market data + news via yfinance & RSS
├── src/analytics.py        ← Portfolio-level quant metrics
├── src/indicators.py       ← Per-stock technical indicators
├── src/sec_edgar.py        ← SEC EDGAR API integration
├── src/news_monitor.py     ← Real-time multi-source news aggregator
├── src/llm.py              ← LLM prompts and OpenRouter client
├── src/snaptrade_integration.py ← Auto-import holdings from a brokerage (SnapTrade)
└── src/summary_pipeline.py ← Orchestrates data + LLM for summaries

data/
├── portfolio.json          ← Your holdings (gitignored, local only)
├── portfolio.example.json  ← Template for others
├── .snaptrade_user.json    ← SnapTrade user id + secret (gitignored, local only)
└── summaries/              ← AI-generated markdown memos (gitignored)
```

**Pattern:** No database. No backend server. Everything runs in a single Streamlit process. Persistent state is plain JSON on disk.

---

## 3. Frontend

**Framework:** [Streamlit](https://streamlit.io/) `>=1.28.0`

**Charting:** [Plotly](https://plotly.com/python/) `>=5.17.0` — candlestick charts, bar charts, line charts, pie/donut charts, histograms, subplots.

Streamlit's sidebar `radio` widget drives navigation between six pages. All UI state is ephemeral (resets on refresh) except holdings data which is read fresh from `portfolio.json` on every page load.

### Pages

| Page | Purpose |
|------|---------|
| Dashboard | Live portfolio value, P&L table, allocation pie chart |
| Manage Holdings | Buy/sell positions, import a broker CSV, or auto-connect a brokerage via SnapTrade |
| Stock Analysis | 4-tab deep dive: Technical, Fundamentals, Geopolitical, News |
| Performance | Historical portfolio value vs SPY, risk metrics |
| Summary | AI-generated periodic memo + trading recommendations table |
| Monitor | Real-time news alert feed with auto-refresh |

---

## 4. Backend Modules

### `src/portfolio.py`
Handles all reads and writes to `data/portfolio.json`.

| Function | What it does |
|----------|-------------|
| `load_portfolio()` | Reads JSON, returns `{"holdings": [...]}` |
| `save_portfolio(portfolio)` | Writes JSON to disk with indentation |
| `add_holding(ticker, shares, avg_price, purchase_date)` | Appends a position and saves |
| `remove_holding(index)` | Pops by list index and saves |

Each holding is stored as:
```json
{
  "ticker": "AAPL",
  "shares": 10.0,
  "avg_price": 150.0,
  "purchase_date": "2024-01-15"
}
```

---

### `src/snaptrade_integration.py`
Auto-imports real brokerage positions via [SnapTrade](https://snaptrade.com), an
investment-data aggregator (Robinhood, Fidelity, Schwab, Vanguard, E\*TRADE, Webull,
Wealthsimple, and more). Reads `SNAPTRADE_CLIENT_ID` and `SNAPTRADE_CONSUMER_KEY` from
the environment.

**Flow (no callback server, no token exchange):**
1. `get_or_register_user()` — registers a single local SnapTrade user the first time and
   persists `{userId, userSecret}` to `data/.snaptrade_user.json`. The `userSecret` is
   generated once by SnapTrade and required for all subsequent calls.
2. `open_connection_portal()` — calls `login_snap_trade_user` to get a hosted
   Connection Portal URL (`redirectURI`) and opens it in the browser. The user logs into
   their brokerage on SnapTrade's side; credentials never touch this app.
3. `list_connections()` — returns active brokerage authorizations
   (`connections.list_brokerage_authorizations`), used to detect a successful connection.
4. `fetch_holdings()` — lists the user's accounts (`list_user_accounts`), reads positions
   per account (`get_user_account_positions`), and maps them to portfolio format.

| Function | What it does |
|----------|-------------|
| `is_configured()` | True if both API keys are present in the environment |
| `get_or_register_user()` | Returns saved `{userId, userSecret}`, registering on first use |
| `is_registered()` | True if a local user file exists |
| `open_connection_portal()` | Opens the SnapTrade Connection Portal in the browser; returns the URL |
| `list_connections()` | Returns active brokerage connections (empty list if none) |
| `fetch_holdings()` | Returns positions as `[{ticker, shares, avg_price, purchase_date}]` |
| `disconnect()` | Deletes the SnapTrade user (and local secret file), removing all connections |

**Position mapping:** ticker = `position["symbol"]["symbol"]["symbol"]`, shares =
`units`, `avg_price` = `average_purchase_price` (falls back to last `price` if cost
basis is unavailable). Positions for the same ticker across multiple accounts are merged
with a share-weighted average price. SnapTrade does not expose a per-lot purchase date, so
`purchase_date` defaults to a placeholder (`"2024-01-01"`); cost-basis-driven P&L remains
accurate.

---

### `src/data_fetcher.py`
Thin wrapper around `yfinance` and RSS feeds. All functions are decorated with `@st.cache_data` to avoid redundant network calls.

| Function | Source | Cache TTL |
|----------|--------|-----------|
| `get_current_price(ticker)` | yfinance (2-day history) | 5 min |
| `get_historical_data(ticker, period, interval)` | yfinance OHLCV | 5 min |
| `get_stock_info(ticker)` | yfinance `.info` dict | 1 hr |
| `get_earnings_info(ticker)` | yfinance earnings / financials | 1 hr |
| `get_company_news_rss(ticker, company, max_articles)` | Google News RSS + Yahoo Finance RSS | 30 min |

`get_historical_data` supports `interval="1d"` (daily) or `"1wk"` (weekly) and periods from `"5d"` to `"5y"`.

---

### `src/sec_edgar.py`
Integrates with the free [SEC EDGAR REST API](https://www.sec.gov/developer) — no API key required. SEC rules require a `User-Agent` header, which is set to a generic personal-use value.

| Function | What it does |
|----------|-------------|
| `get_cik(ticker)` | Resolves ticker → 10-digit SEC CIK number via `company_tickers.json` |
| `get_recent_filings(ticker, form_types, days_back, max_results)` | Returns list of recent filings with form, date, description, SEC URL |
| `get_filing_text(url, max_chars)` | Downloads a filing page, strips HTML, returns plain text for LLM |
| `get_filing_digest(form, url)` | LLM-ready excerpt: Risk Factors + MD&A for 10-K, MD&A for 10-Q, item text for 8-K (skips table of contents and cross-references) |
| `get_latest_annual_risk_factors(ticker)` | Item 1A of the most recent 10-K |
| `get_insider_activity(ticker, days_back)` | Parses Form 4 XML for open-market buys (`P`) and sells (`S`), aggregates by insider, flags 10b5-1 plan sales |
| `_describe_filing(form, item_codes)` | Maps 8-K item codes to plain-English descriptions |

**Supported form types:** `8-K` (material events), `10-K` (annual report), `10-Q` (quarterly report), `DEF 14A` (proxy/shareholder vote), `4` (insider trades), `SC 13G/13D` (large/activist stakes), `S-1` (IPO).

**8-K item codes decoded:** M&A (`2.01`), earnings (`2.02`), cybersecurity incident (`1.05`), CEO/CFO change (`5.02`), debt offering (`1.01`), bankruptcy (`6.01`), and more.

---

### `src/news_monitor.py`
Multi-source real-time news aggregator used by the Monitor page. Sources are polled in speed order.

| Source | Speed | Method |
|--------|-------|--------|
| SEC EDGAR 8-K (same-day) | ⚡⚡⚡⚡ | EDGAR full-text search API |
| Business Wire | ⚡⚡⚡ | RSS feed |
| PR Newswire | ⚡⚡⚡ | RSS feed (keyword filtered) |
| Yahoo Finance | ⚡⚡ | RSS feed |
| Google News | ⚡ | RSS feed |

**Significance scoring:** Rule-based keyword matching assigns each article a score from 1–10 with a category label:

| Score | Label | Example triggers |
|-------|-------|-----------------|
| 10 | 🔴 M&A | "acquisition", "merger", "buyout" |
| 10 | 🔴 FDA | "fda approval", "breakthrough therapy" |
| 10 | 🔴 Distress | "bankruptcy", "chapter 11", "default" |
| 8 | 🟠 Earnings | "quarterly results", "eps", "guidance" |
| 8 | 🟠 Legal | "sec investigation", "class action", "fraud" |
| 7 | 🟡 Leadership | "ceo", "cfo", "stepping down" |
| 5 | 🟢 Analyst | "upgrade", "downgrade", "price target" |
| 3 | ⚪ General | Everything else |

Deduplication uses an MD5 hash of the article URL. Results are sorted by score (descending), then recency. Cache TTL is 90 seconds.

---

## 5. Data Sources

| Data | Source | Cost | API Key? |
|------|--------|------|----------|
| Stock prices (live + historical) | Yahoo Finance via `yfinance` | Free | No |
| Company metadata (sector, P/E, beta, etc.) | Yahoo Finance via `yfinance` | Free | No |
| Earnings calendar + EPS history | Yahoo Finance via `yfinance` | Free | No |
| Quarterly/annual income statements | Yahoo Finance via `yfinance` | Free | No |
| SEC filings (8-K, 10-K, 10-Q, etc.) | SEC EDGAR REST API | Free | No |
| SEC full-text search (8-K same-day) | SEC EDGAR EFTS | Free | No |
| News (portfolio news page) | Google News RSS + Yahoo Finance RSS | Free | No |
| News (monitor page) | SEC EDGAR + Business Wire + PR Newswire + Yahoo + Google | Free | No |
| AI analysis | OpenRouter → Claude Opus 5.5 | Paid per token | Yes (`OPENROUTER_API_KEY`) |

### `src/market_context.py`
Extra context for the prompts, all from yfinance (no key).

| Function | What it does |
|----------|-------------|
| `position_table(holdings)` | Value, weight, unrealized P&L per holding, plus sector weights |
| `quality_metrics(info)` | Growth, margins, FCF, cash/debt, P/E, PEG, EV/EBITDA, P/S, analyst consensus + target, short interest, 52w range |
| `earnings_surprises(earnings_history)` | Last 4 quarters EPS actual vs estimate with surprise % |
| `relative_performance(ticker, sector, period)` | Return vs sector SPDR ETF (XLK, XLV, …) and SPY |
| `macro_snapshot()` | 10Y yield, VIX, dollar index, oil, gold — level and 1-month change |
| `etf_profile(ticker, info)` / `etf_top_holdings(ticker)` | Expense ratio, category, assets, yield; top 10 holdings |
| `lookthrough_exposure(positions)` | Direct + via-ETF exposure per stock (lower bound — only ETF top holdings are known) |

---

## 6. AI / LLM Layer

**File:** `src/llm.py`

**Model:** `$OPENROUTER_MODEL` if set, otherwise `anthropic/claude-opus-5.5`, via [OpenRouter](https://openrouter.ai/)

**Client:** OpenAI SDK pointed at `https://openrouter.ai/api/v1` — OpenRouter's API is OpenAI-compatible, so the standard `openai` Python package works without modification.

**API key resolution order:**
1. `st.secrets["OPENROUTER_API_KEY"]` (Streamlit Cloud deployment)
2. `.env` file loaded by `python-dotenv`
3. `os.environ["OPENROUTER_API_KEY"]`

### LLM Functions

| Function | Purpose | Max tokens | Temp |
|----------|---------|-----------|------|
| `analyze_fundamentals(...)` | Stock memo: quality, valuation, earnings & momentum vs peers, insider & filing signals, bull/bear case, what would change the view, rating + confidence | 1800 | 0.3 |
| `analyze_etf(...)` | Fund memo: what you own, cost, overlap with your other holdings, performance, bull/bear, rating + confidence | 1500 | 0.3 |
| `analyze_geopolitical(ticker, info, news_headlines, risk_factors, macro)` | Exposure, sensitivity to current macro readings, geopolitical and regulatory risks, the company's own 10-K risk factors, rating + confidence | 1200 | 0.3 |
| `summarize_sec_filing(form_type, filing_text, ticker, description)` | What happened, why it matters, signal, anything unusual, action needed | 600 | 0.2 |
| `generate_portfolio_summary(period_label, holdings_data, portfolio_metrics, overview, lookthrough, macro, prior_summary)` | Full portfolio memo + recommendations table | 10000 | 0.3 |

Every prompt includes today's date and uses a shared analyst system prompt that requires citing the data, never inventing figures, and tagging judgment calls with *(inference)*.

All functions call the shared `call_llm(prompt, system, model, max_tokens, temperature)` which handles API errors and configuration errors gracefully, returning error strings instead of raising exceptions.

### Trading Recommendations (output format)

`generate_portfolio_summary` instructs Claude to output a Markdown table with one row per ticker:

```
| Ticker | Weight | Daily | Weekly | Monthly | Confidence | Key Reasoning |
```

Valid ratings: `Strong Buy / Buy / Moderate Buy / Hold / Moderate Sell / Sell / Strong Sell`

Rows are ordered by position weight. The memo also includes Concentration & Exposure, Bull vs Bear for the top 5 positions, Rebalancing Ideas, and — when a previous summary for the same period exists — What Changed Since Last Review.

Claude synthesizes: position size and unrealized P&L, fundamentals, insider activity, performance vs sector ETF and SPY, ETF look-through, macro indicators, price return, RSI, MACD, Bollinger Band position, SMA trend, recent SEC filings, news headlines, sector macro context, and geopolitical exposure to arrive at each rating.

---

## 7. Technical Indicators (Quant Layer)

**File:** `src/indicators.py`

All indicators take a `pd.Series` of prices and return a `pd.Series` (or tuple for multi-output indicators). No external TA library — all implemented from scratch with NumPy/Pandas.

### Trend
| Indicator | Function | Parameters |
|-----------|----------|-----------|
| Simple Moving Average | `sma(prices, period)` | `period` (int) |
| Exponential Moving Average | `ema(prices, period)` | `period` (int) |

### Momentum
| Indicator | Function | Notes |
|-----------|----------|-------|
| RSI | `rsi(prices, period=14)` | >70 = overbought, <30 = oversold |
| MACD | `macd(prices, fast=12, slow=26, signal=9)` | Returns `(macd_line, signal_line, histogram)` |

### Volatility
| Indicator | Function | Notes |
|-----------|----------|-------|
| Bollinger Bands | `bollinger_bands(prices, period=20, std_dev=2.0)` | Returns `(upper, middle, lower)` |

### Support & Resistance
| Function | Algorithm |
|----------|-----------|
| `support_resistance_levels(high, low, close, window=10, n_levels=5)` | Finds pivot highs/lows within a rolling window, clusters nearby levels within 1.5% tolerance, splits into support (below price) and resistance (above price) |
| `pivot_points(high, low, close)` | Classic floor trader pivot points: PP, R1/R2/R3, S1/S2/S3 |

### How indicators feed the Summary Pipeline
`_tech_signals(ticker)` in `summary_pipeline.py` runs a 3-month history through RSI, MACD, Bollinger Bands, SMA20, and SMA50, then packages the results as structured signals passed to the LLM:

```python
{
  "rsi": 58.3,                 # latest RSI value
  "macd_bullish": True,        # MACD line above signal line
  "macd_crossing_up": False,   # fresh bullish crossover this bar
  "bb_pct": 0.62,              # position within Bollinger Band (0=lower, 1=upper)
  "above_sma20": True,
  "above_sma50": True,
}
```

---

## 8. Analytics Engine

**File:** `src/analytics.py`

Portfolio-level quantitative finance calculations.

| Function | Formula / Method |
|----------|-----------------|
| `calculate_portfolio_metrics(holdings)` | Fetches current prices, computes cost basis, market value, P&L ($), P&L (%) per position |
| `calculate_returns(prices)` | Daily simple returns: `prices.pct_change().dropna()` |
| `annualized_volatility(returns, periods=252)` | $\sigma_{ann} = \sigma_{daily} \times \sqrt{252}$ |
| `sharpe_ratio(returns, risk_free=0.04, periods=252)` | $S = \frac{R_{ann} - R_f}{\sigma_{ann}}$, risk-free default ~4% (US T-bill) |
| `max_drawdown(prices)` | $MDD = \min\left(\frac{cumulative - running\_max}{running\_max}\right)$ |
| `beta_vs_benchmark(asset_returns, benchmark_returns)` | $\beta = \frac{Cov(r_a, r_b)}{Var(r_b)}$, benchmark = SPY |
| `portfolio_history(holdings, period)` | Sums `shares × close_price` per ticker per day using a date-aligned DataFrame. Assumes current share count held for the full period. |

---

## 9. Data Flow — Summary Pipeline

**File:** `src/summary_pipeline.py`

Orchestrates data collection → LLM call → disk save when you click "Generate Summary".

```
run_summary_pipeline(holdings, period_label)
│
├── _portfolio_metrics(holdings, yf_period)
│   ├── portfolio_history() → total value series
│   ├── calculate_returns()
│   ├── annualized_volatility(), sharpe_ratio(), max_drawdown()
│   └── beta_vs_benchmark() vs SPY
│
├── position_table()  → weights, unrealized P&L, sector weights
├── macro_snapshot()  → 10Y, VIX, DXY, oil, gold
│
├── For each holding (largest first) → _stock_snapshot(holding, yf_period, days_back, position)
│   ├── get_stock_info()      → sector, country, company name, quality metrics
│   ├── relative_performance()→ vs sector ETF and SPY
│   ├── get_insider_activity()→ Form 4 buys/sells (90 days, stocks only)
│   ├── get_historical_data() → period price return
│   ├── get_recent_filings()  → up to 4 recent SEC filings
│   ├── get_company_news_rss()→ up to 8 headlines
│   └── _tech_signals()
│       ├── rsi()             → RSI value + overbought/oversold flag
│       ├── macd()            → bullish/bearish + fresh crossover flag
│       ├── bollinger_bands() → % position within band
│       └── sma(20), sma(50)  → above/below trend flags
│
├── lookthrough_exposure() → direct + via-ETF exposure
├── _prior_summary()       → last saved summary for the same period
│
└── generate_portfolio_summary() → Claude (OPENROUTER_MODEL)
    └── Writes markdown to data/summaries/YYYY-MM-DD_period.md (LLM errors are not saved)
```

**Period configs:**

| Label | yfinance period | Days back (filings/news) |
|-------|----------------|--------------------------|
| Daily | 5d | 2 days |
| Weekly | 1mo | 7 days |
| Monthly | 3mo | 30 days |

---

## 10. Caching Strategy

Streamlit's `@st.cache_data` is used throughout to avoid hammering APIs on every UI interaction. Cache is per-session (in-memory) and resets on app restart.

| Data | TTL |
|------|-----|
| Current price | 5 min |
| Historical OHLCV | 5 min |
| Stock info (fundamentals) | 1 hr |
| Earnings data | 1 hr |
| SEC filings list | 1 hr |
| SEC filing text | 2 hr |
| CIK lookup | 24 hr |
| News (portfolio page) | 30 min |
| News (monitor page) | 90 sec |

---

## 11. Storage

| File | Description | Gitignored? |
|------|-------------|-------------|
| `data/portfolio.json` | Your actual holdings | Yes — stays local |
| `data/portfolio.example.json` | Template with example tickers | No — public |
| `data/summaries/*.md` | AI-generated memos | Yes — stays local |
| `data/.snaptrade_user.json` | SnapTrade user id + secret | Yes — stays local |
| `.env` | API keys | Yes |
| `.env.example` | Template (no real keys) | No — public |

---

## 12. Dependencies

```
streamlit>=1.28.0           # UI framework
yfinance>=0.2.40            # Yahoo Finance market data
pandas>=2.0.0               # DataFrames
numpy>=1.24.0               # Numerical operations (indicators, analytics)
plotly>=5.17.0              # Interactive charts
feedparser>=6.0.0           # RSS feed parsing (news monitor)
openai>=1.0.0               # OpenAI-compatible client (used for OpenRouter)
python-dotenv>=1.0.0        # .env file loading
streamlit-autorefresh>=0.0.1 # Auto-refresh on Monitor page
snaptrade-python-sdk>=11.0.0 # Brokerage holdings import (SnapTrade)
```

No ML frameworks (PyTorch, sklearn, etc.) are used. All quantitative logic is implemented directly with NumPy and Pandas.

---

## 13. Pages & Features Reference

### Dashboard
- Fetches current prices for all holdings via `get_current_price()`
- Computes portfolio metrics via `calculate_portfolio_metrics()`
- Shows: total value, cost basis, total P&L, allocation donut chart, P&L bar chart, full holdings table

### Manage Holdings
Four tabs:
- **🟢 Buy / 🔴 Sell** — form-validated inputs (ticker verified live via `get_current_price()` before saving); buys recompute a share-weighted average cost, sells reduce or close a position
- **📥 Import CSV** — upload a broker holdings export (Robinhood, Fidelity, Schwab, Vanguard); common formats are standardized automatically
- **🏦 Connect Brokerage** — auto-import live positions via SnapTrade (`src/snaptrade_integration.py`): connect once in a hosted portal, then **Sync Holdings** writes positions into `portfolio.json`
- Removes individual positions by list index

### Stock Analysis — Technical tab
- Candlestick chart (daily or weekly) with configurable period
- Optional overlays: SMA 20/50/200, EMA 20, Bollinger Bands
- Optional support/resistance levels (pivot-point algorithm)
- Optional floor-trader pivot points (PP, S1-S3, R1-R3)
- Volume bar chart (color-coded by up/down candle)
- RSI (14) with overbought/oversold zones
- MACD with histogram

### Stock Analysis — Fundamentals & Earnings tab
- Company snapshot: sector, industry, market cap, employees, P/E TTM, forward P/E, dividend yield, beta
- AI fundamental memo (on-demand, Claude Opus 5.5)
- Next earnings date + EPS/revenue estimates
- EPS actual vs estimate beat/miss chart (last 4 quarters)
- Quarterly financials: Revenue, Gross Profit, Net Income, Operating Income, EBITDA
- SEC filings list with links to SEC.gov; per-filing AI summarization on demand

### Stock Analysis — Geopolitical & Macro tab
- On-demand AI risk assessment: geographic exposure, macro risks, geopolitical risks, sector-specific risks, and an overall Low/Medium/High risk rating
- Links to FRED, USTR, SEC 10-K risk disclosures, Geopolitical Risk Index

### Stock Analysis — News tab
- Up to 25 articles from Google News + Yahoo Finance RSS
- Live text filter on headlines and summaries

### Performance
- Plots historical portfolio value as an area chart
- Overlays normalized portfolio vs SPY (both indexed to 100)
- Risk metrics: period return, annualized volatility, Sharpe ratio, max drawdown, beta vs SPY
- Daily returns distribution histogram

### Summary
- Selectable period: Daily / Weekly / Monthly
- Progress bar during data collection and LLM call
- Output sections: Portfolio Performance, Winners & Losers, Key Events, Macro & Geopolitical Watch, Risk Flags, **Trading Recommendations table**, Watch List
- Saves to `data/summaries/YYYY-MM-DD_period.md`
- Past summaries: load and download as Markdown

### Monitor
- Per-ticker feed from 5 sources: SEC 8-K (same-day), Business Wire, PR Newswire, Yahoo Finance, Google News
- Articles sorted by significance score (1–10) with color-coded badges
- Auto-refresh every 2 minutes via `streamlit-autorefresh` (if installed)
- Covers all tickers in the portfolio simultaneously
