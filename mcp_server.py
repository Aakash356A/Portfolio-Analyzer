#!/usr/bin/env python3
"""
Portfolio Tracker — MCP Server
================================
Exposes your portfolio data, technical analysis, fundamentals, news,
and SEC filings as tools that Claude can call during a conversation.

HOW TO CONNECT (Claude Desktop):
---------------------------------
Edit: ~/Library/Application Support/Claude/claude_desktop_config.json
      (Mac) or %APPDATA%/Claude/claude_desktop_config.json (Windows)

{
  "mcpServers": {
    "portfolio-tracker": {
      "command": "python",
      "args": ["/FULL/PATH/TO/Portfolio_tracker/mcp_server.py"]
    }
  }
}

Then restart Claude Desktop. You will see a hammer icon (🔨) in the
chat input bar when the server is connected.

USAGE:
-------
Just talk to Claude naturally:
  "Analyze my full portfolio and tell me what to watch this week."
  "What does the technical setup look like for AAPL right now?"
  "Compare MSFT and GOOGL — which looks better technically?"
  "Any breaking news or SEC filings for my holdings today?"

Claude will call the right tools, pull your live data, and analyze it —
all using your Claude subscription, zero API cost.
"""

import json
import os
import sys
from pathlib import Path

# ── Make sure src.* imports work regardless of cwd ───────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP

from src.analytics import (
    annualized_volatility,
    beta_vs_benchmark,
    calculate_portfolio_metrics,
    calculate_returns,
    max_drawdown,
    portfolio_history,
    sharpe_ratio,
)
from src.data_fetcher import (
    get_company_news_rss,
    get_earnings_info,
    get_historical_data,
    get_stock_info,
)
from src.indicators import (
    bollinger_bands,
    ema,
    macd,
    rsi,
    sma,
    support_resistance_levels,
)
from src.news_monitor import fetch_all
from src.portfolio import load_portfolio
from src.sec_edgar import get_recent_filings

# ── Portfolio helper ──────────────────────────────────────────────────────────

def _parse_portfolio(portfolio_json: str) -> dict:
    """
    Return portfolio dict from an inline JSON string, or fall back to the
    local data/portfolio.json when running in stdio/local mode.
    """
    if portfolio_json.strip():
        data = json.loads(portfolio_json)
        if "holdings" not in data:
            data = {"holdings": data}  # accept bare list too
        return data
    return load_portfolio()


# ── Server declaration ────────────────────────────────────────────────────────

mcp = FastMCP(
    name="Portfolio Tracker",
    instructions="""
You have access to a personal stock portfolio tracker with live market data.

Available tools:
  get_portfolio          — all holdings: price, P&L, allocation
  get_portfolio_metrics  — returns, Sharpe, drawdown, beta vs S&P 500
  get_technical_analysis — RSI, MACD, moving averages, support/resistance
  get_fundamentals       — EPS history, valuation ratios, revenue trend
  get_news               — latest news headlines (Google + Yahoo RSS)
  get_sec_filings        — recent 8-K/10-K/10-Q filings from SEC EDGAR
  get_breaking_news      — all fast sources scored by market significance
  compare_stocks         — side-by-side multi-stock comparison

WORKFLOW GUIDANCE:
- For full portfolio review: start with get_portfolio, then
  get_portfolio_metrics, then per-stock analysis.
- For a single stock: get_technical_analysis + get_fundamentals +
  get_sec_filings gives a complete picture.
- For time-sensitive alerts: get_breaking_news (polls SEC EDGAR today).
- Combine RSI, MACD, and support/resistance for technical confluence.
- Flag 8-K items 2.02 (earnings), 2.01 (M&A), 5.02 (CEO change).
""",
)


# ─────────────────────────────────────────────────────────────────────────────
# Tool 1 — Portfolio snapshot
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_portfolio(portfolio_json: str = "") -> str:
    """
    Return all current portfolio holdings with live prices, P&L (dollar
    and percent), cost basis, market value, and allocation weight.
    Always call this first for a portfolio-level conversation.

    Args:
        portfolio_json: (remote/hosted use) JSON string of your holdings, e.g.
            '{"holdings": [{"ticker": "AAPL", "shares": 10, "purchase_price": 150.0, "purchase_date": "2024-01-15"}]}'
            Omit when running locally — the server reads data/portfolio.json automatically.
    """
    try:
        holdings = _parse_portfolio(portfolio_json)["holdings"]
        if not holdings:
            return json.dumps({"status": "empty", "message": "No holdings in portfolio."})

        df = calculate_portfolio_metrics(holdings)
        if df.empty:
            return json.dumps({"error": "Could not fetch live prices for any holding."})

        total_value = df["Market Value"].sum()
        total_cost  = df["Cost Basis"].sum()
        total_pnl   = df["P&L ($)"].sum()

        result = {
            "portfolio_summary": {
                "total_market_value": round(total_value, 2),
                "total_cost_basis":   round(total_cost, 2),
                "total_pnl_dollars":  round(total_pnl, 2),
                "total_pnl_pct":      round(total_pnl / total_cost * 100, 2) if total_cost else 0,
                "num_positions":      len(df),
            },
            "holdings": [
                {
                    "ticker":         row["Ticker"],
                    "shares":         row["Shares"],
                    "purchase_price": round(row["Purchase Price"], 2),
                    "current_price":  round(row["Current Price"], 2),
                    "cost_basis":     round(row["Cost Basis"], 2),
                    "market_value":   round(row["Market Value"], 2),
                    "pnl_dollars":    round(row["P&L ($)"], 2),
                    "pnl_pct":        round(row["P&L (%)"], 2),
                    "weight_pct":     round(row["Market Value"] / total_value * 100, 1),
                    "purchase_date":  row.get("Purchase Date", ""),
                }
                for _, row in df.iterrows()
            ],
        }
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 2 — Portfolio risk / performance metrics
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_portfolio_metrics(period: str = "1y", portfolio_json: str = "") -> str:
    """
    Return portfolio-level risk and return metrics for the given period.

    Args:
        period:         "1mo" | "3mo" | "6mo" | "1y" | "2y" | "5y"
        portfolio_json: (remote/hosted use) JSON string of your holdings — same
                        format as get_portfolio. Omit when running locally.

    Metrics returned: period return, alpha vs S&P 500, annualized
    volatility, Sharpe ratio, max drawdown, beta.
    """
    try:
        holdings = _parse_portfolio(portfolio_json)["holdings"]
        history  = portfolio_history(holdings, period)
        if history.empty or "Total" not in history.columns:
            return json.dumps({"error": "Could not build portfolio history."})

        returns    = calculate_returns(history["Total"])
        spy        = get_historical_data("SPY", period)
        per_ret    = (history["Total"].iloc[-1] / history["Total"].iloc[0] - 1) * 100
        vol        = annualized_volatility(returns) * 100
        sr         = sharpe_ratio(returns)
        mdd        = max_drawdown(history["Total"]) * 100
        beta       = 0.0
        spy_ret    = 0.0

        if not spy.empty:
            spy_rets = calculate_returns(spy["Close"])
            beta     = beta_vs_benchmark(returns, spy_rets)
            spy_ret  = (spy["Close"].iloc[-1] / spy["Close"].iloc[0] - 1) * 100

        return json.dumps({
            "period":               period,
            "portfolio_return_pct": round(per_ret, 2),
            "sp500_return_pct":     round(spy_ret, 2),
            "alpha_pct":            round(per_ret - spy_ret, 2),
            "annualized_vol_pct":   round(vol, 2),
            "sharpe_ratio":         round(sr, 2),
            "max_drawdown_pct":     round(mdd, 2),
            "beta_vs_sp500":        round(beta, 2),
            "start_value":          round(float(history["Total"].iloc[0]), 2),
            "end_value":            round(float(history["Total"].iloc[-1]), 2),
            "interpretation": {
                "sharpe":     "good (>1)" if sr > 1 else "fair (0.5-1)" if sr > 0.5 else "poor (<0.5)",
                "beta":       "defensive (<0.8)" if beta < 0.8
                              else "market-like (0.8-1.2)" if beta < 1.2
                              else "aggressive (>1.2)",
                "vs_market":  "outperforming" if per_ret > spy_ret else "underperforming",
                "drawdown":   "low risk" if mdd > -10 else "moderate" if mdd > -20 else "high drawdown",
            },
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 3 — Technical analysis
# ─────────────────────────────────────────────────────────────────────────────

def _bias(rsi_v, macd_v, sig_v, price, sma50, sma200) -> str:
    score = 0
    if rsi_v > 50: score += 1
    else:          score -= 1
    if macd_v > sig_v: score += 1
    else:              score -= 1
    if sma50  and price > sma50:  score += 1
    else:                          score -= 1
    if sma200 and price > sma200: score += 1
    else:                          score -= 1
    return "bullish" if score >= 2 else "bearish" if score <= -2 else "neutral"


@mcp.tool()
def get_technical_analysis(ticker: str, period: str = "6mo",
                            interval: str = "1d") -> str:
    """
    Return a full technical analysis snapshot for a stock.

    Args:
        ticker:   e.g. "AAPL"
        period:   "1mo" | "3mo" | "6mo" | "1y" | "2y"
        interval: "1d" (daily) | "1wk" (weekly)

    Includes: RSI, MACD signal, moving averages (SMA 20/50/200),
    Bollinger Band position, key support and resistance levels,
    and an overall bullish/neutral/bearish bias.
    """
    try:
        data = get_historical_data(ticker, period, interval)
        if data.empty or len(data) < 20:
            return json.dumps({"error": f"Insufficient price data for {ticker}."})

        close = data["Close"]
        price = float(close.iloc[-1])

        # RSI
        rsi_s    = rsi(close)
        rsi_now  = float(rsi_s.iloc[-1])
        rsi_prev = float(rsi_s.iloc[-2])

        # MACD
        ml, sl, hist = macd(close)
        macd_now  = float(ml.iloc[-1])
        sig_now   = float(sl.iloc[-1])
        hist_now  = float(hist.iloc[-1])
        hist_prev = float(hist.iloc[-2])

        # Moving averages
        sma20  = float(sma(close, 20).iloc[-1])  if len(close) >= 20  else None
        sma50  = float(sma(close, 50).iloc[-1])  if len(close) >= 50  else None
        sma200 = float(sma(close, 200).iloc[-1]) if len(close) >= 200 else None

        # Bollinger Bands
        bbu, bbm, bbl = bollinger_bands(close)
        bb_pct = (price - float(bbl.iloc[-1])) / \
                 max(float(bbu.iloc[-1]) - float(bbl.iloc[-1]), 1e-9)

        # Support / Resistance
        win = 5 if interval == "1wk" else 10
        sups, ress = support_resistance_levels(
            data["High"], data["Low"], close, window=win, n_levels=4)

        # Period stats
        rets    = calculate_returns(close)
        per_ret = (price / float(close.iloc[0]) - 1) * 100

        # Cross signals
        cross = None
        if sma50 and sma200:
            cross = "golden_cross" if sma50 > sma200 else "death_cross"

        return json.dumps({
            "ticker":        ticker,
            "period":        period,
            "interval":      interval,
            "current_price": round(price, 2),
            "period_return_pct": round(per_ret, 2),
            "annualized_vol_pct": round(annualized_volatility(rets) * 100, 2),

            "rsi": {
                "value":     round(rsi_now, 1),
                "previous":  round(rsi_prev, 1),
                "signal":    "overbought" if rsi_now > 70
                             else "oversold" if rsi_now < 30
                             else "neutral",
                "trending":  "up" if rsi_now > rsi_prev else "down",
            },

            "macd": {
                "macd_line":     round(macd_now, 4),
                "signal_line":   round(sig_now, 4),
                "histogram":     round(hist_now, 4),
                "crossover":     "bullish" if macd_now > sig_now else "bearish",
                "momentum":      "strengthening" if abs(hist_now) > abs(hist_prev)
                                 else "weakening",
            },

            "moving_averages": {
                "sma_20":           round(sma20, 2)  if sma20  else None,
                "sma_50":           round(sma50, 2)  if sma50  else None,
                "sma_200":          round(sma200, 2) if sma200 else None,
                "price_vs_sma20":   "above" if sma20  and price > sma20  else "below",
                "price_vs_sma50":   "above" if sma50  and price > sma50  else "below",
                "price_vs_sma200":  "above" if sma200 and price > sma200 else "below",
                "ma_cross_signal":  cross,
            },

            "bollinger_bands": {
                "upper":    round(float(bbu.iloc[-1]), 2),
                "middle":   round(float(bbm.iloc[-1]), 2),
                "lower":    round(float(bbl.iloc[-1]), 2),
                "pct_b":    round(bb_pct, 2),
                "position": "near upper (stretched up)" if bb_pct > 0.8
                            else "near lower (stretched down)" if bb_pct < 0.2
                            else "middle",
            },

            "key_levels": {
                "support_levels":     [round(s, 2) for s in sups],
                "resistance_levels":  [round(r, 2) for r in ress],
                "nearest_support":    round(sups[-1], 2)  if sups else None,
                "nearest_resistance": round(ress[0], 2)   if ress else None,
                "distance_to_support_pct":    round((price - sups[-1])  / price * 100, 1) if sups else None,
                "distance_to_resistance_pct": round((ress[0] - price)   / price * 100, 1) if ress else None,
            },

            "overall_bias": _bias(rsi_now, macd_now, sig_now, price, sma50, sma200),
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 4 — Fundamentals
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_fundamentals(ticker: str) -> str:
    """
    Return fundamental data: valuation ratios, quality metrics, growth
    rates, EPS beat/miss history, next earnings date, and quarterly
    revenue trend.

    Args:
        ticker: e.g. "MSFT"
    """
    try:
        info = get_stock_info(ticker)
        ear  = get_earnings_info(ticker)

        result: dict = {
            "ticker":   ticker,
            "company":  info.get("longName", ticker),
            "sector":   info.get("sector",   "N/A"),
            "industry": info.get("industry", "N/A"),
            "country":  info.get("country",  "N/A"),
            "employees": info.get("fullTimeEmployees"),

            "valuation": {
                "market_cap_usd": info.get("marketCap"),
                "pe_ttm":         info.get("trailingPE"),
                "pe_forward":     info.get("forwardPE"),
                "price_to_book":  info.get("priceToBook"),
                "price_to_sales": info.get("priceToSalesTrailing12Months"),
                "ev_to_ebitda":   info.get("enterpriseToEbitda"),
                "dividend_yield": info.get("dividendYield"),
                "beta":           info.get("beta"),
            },

            "quality": {
                "roe":              info.get("returnOnEquity"),
                "roa":              info.get("returnOnAssets"),
                "net_margin":       info.get("profitMargins"),
                "operating_margin": info.get("operatingMargins"),
                "debt_to_equity":   info.get("debtToEquity"),
                "current_ratio":    info.get("currentRatio"),
                "free_cashflow":    info.get("freeCashflow"),
            },

            "growth": {
                "revenue_growth_yoy":    info.get("revenueGrowth"),
                "earnings_growth_yoy":   info.get("earningsGrowth"),
                "earnings_growth_qoq":   info.get("earningsQuarterlyGrowth"),
            },
        }

        # Next earnings date
        cal = ear.get("calendar") or {}
        try:
            def pick(keys):
                for k in keys:
                    if k in cal:
                        v = cal[k]
                        if hasattr(v, "__iter__") and not isinstance(v, str):
                            v = list(v)
                            return v[0] if v else None
                        return v
                return None

            result["next_earnings"] = {
                "date":         str(pick(["Earnings Date", "earningsDate"]) or "N/A"),
                "eps_estimate": pick(["EPS Estimate", "epsEstimate", "Earnings Average"]),
                "rev_estimate": pick(["Revenue Estimate", "revenueAverage"]),
            }
        except Exception:
            pass

        # EPS beat/miss history
        eh = ear.get("earnings_history")
        if eh is not None and not eh.empty:
            cm = {}
            for c in eh.columns:
                cl = c.lower()
                if "actual"   in cl: cm[c] = "actual"
                elif "estimate" in cl: cm[c] = "estimate"
                elif "surprise" in cl and "%" in cl: cm[c] = "surprise_pct"
                elif "quarter" in cl or "date" in cl: cm[c] = "period"
            eh = eh.rename(columns=cm)
            eps_list = []
            for _, row in eh.tail(6).iterrows():
                entry = {c: str(row[c]) for c in ["period","actual","estimate","surprise_pct"] if c in row}
                try:
                    entry["beat"] = float(entry["actual"]) >= float(entry["estimate"])
                except Exception:
                    pass
                eps_list.append(entry)
            result["eps_history_last_6q"] = eps_list

        # Quarterly revenue
        qf = ear.get("quarterly_financials")
        if qf is not None and not qf.empty:
            rev_row = next((r for r in ["Total Revenue", "Revenue"] if r in qf.index), None)
            if rev_row:
                result["quarterly_revenue_usd"] = {
                    str(k)[:10]: int(v)
                    for k, v in qf.loc[rev_row].dropna().items()
                }

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 5 — News headlines
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_news(ticker: str, max_articles: int = 15) -> str:
    """
    Fetch the latest news articles for a company from Yahoo Finance
    and Google News RSS feeds.

    Args:
        ticker:       e.g. "NVDA"
        max_articles: 1-25 (default 15)
    """
    try:
        info     = get_stock_info(ticker)
        company  = info.get("longName", ticker)
        articles = get_company_news_rss(ticker, company,
                                         max_articles=min(max_articles, 25))
        return json.dumps({
            "ticker":   ticker,
            "company":  company,
            "count":    len(articles),
            "articles": [
                {
                    "title":     a["title"],
                    "source":    a.get("source", ""),
                    "published": a.get("published", ""),
                    "link":      a.get("link", ""),
                    "summary":   a.get("summary", "")[:200],
                }
                for a in articles
            ],
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 6 — SEC filings
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_sec_filings(ticker: str, days_back: int = 90,
                    form_types: str = "8-K,10-K,10-Q,DEF 14A") -> str:
    """
    Fetch recent SEC filings from EDGAR. 8-K filings are the most
    actionable — companies must file within 4 business days of a
    material event.

    Args:
        ticker:     e.g. "INTC"
        days_back:  how far back to look (default 90)
        form_types: comma-separated (default "8-K,10-K,10-Q,DEF 14A")

    Key 8-K item codes to watch:
        2.02 Earnings release    2.01 M&A completion
        5.02 CEO/CFO change      1.05 Cybersecurity incident
        1.01 Material contract   2.05 Cost cuts / layoffs
    """
    try:
        forms   = [f.strip() for f in form_types.split(",")]
        filings = get_recent_filings(ticker, form_types=forms,
                                     days_back=days_back)
        return json.dumps({
            "ticker":    ticker,
            "days_back": days_back,
            "count":     len(filings),
            "filings": [
                {
                    "form":        f["form"],
                    "date":        f["date"],
                    "description": f["description"],
                    "label":       f["label"],
                    "url":         f["url"],
                }
                for f in filings
            ],
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 7 — Breaking news (all fast sources, scored)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_breaking_news(ticker: str) -> str:
    """
    Fetch and score breaking news from all fast sources: SEC EDGAR
    (today's 8-Ks), Business Wire, PR Newswire, Yahoo Finance, and
    Google News. Each article is scored 1-10 for market impact.

    Args:
        ticker: e.g. "AAPL"

    Significance scores:
        9-10  Critical  — M&A, FDA approval, bankruptcy
        7-8   High      — Earnings, CEO change, major contract
        5-6   Medium    — Analyst upgrade/downgrade, dividends
        1-4   Low       — General news

    Use this for real-time monitoring or before-market checks.
    """
    try:
        info     = get_stock_info(ticker)
        company  = info.get("longName", ticker)
        articles = fetch_all(ticker, company)

        return json.dumps({
            "ticker":    ticker,
            "company":   company,
            "total":     len(articles),
            "high_impact": [
                {
                    "score":     a["score"],
                    "label":     a["label"],
                    "title":     a["title"],
                    "source":    a["source"],
                    "speed_tier": a["speed"],
                    "published": a.get("published", ""),
                    "link":      a.get("link", ""),
                }
                for a in articles if a["score"] >= 6
            ],
            "all_articles": [
                {
                    "score":     a["score"],
                    "label":     a["label"],
                    "title":     a["title"],
                    "source":    a["source"],
                    "published": a.get("published", ""),
                }
                for a in articles
            ],
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Tool 8 — Multi-stock comparison
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def compare_stocks(tickers: str, period: str = "6mo") -> str:
    """
    Compare multiple stocks side-by-side: period return, volatility,
    RSI, MACD signal, P/E, and market cap.

    Args:
        tickers: comma-separated, e.g. "AAPL,MSFT,GOOGL"
        period:  "1mo" | "3mo" | "6mo" | "1y"
    """
    try:
        ticker_list = [t.strip().upper() for t in tickers.split(",")][:8]
        rows = []
        for tick in ticker_list:
            try:
                data    = get_historical_data(tick, period)
                info    = get_stock_info(tick)
                rets    = calculate_returns(data["Close"])
                rsi_v   = float(rsi(data["Close"]).iloc[-1]) if not data.empty else None
                ml, sl, _ = macd(data["Close"])
                per_ret = (float(data["Close"].iloc[-1]) /
                           float(data["Close"].iloc[0]) - 1) * 100 \
                          if not data.empty and len(data) >= 2 else None

                rows.append({
                    "ticker":           tick,
                    "company":          info.get("longName", tick)[:30],
                    "current_price":    round(float(data["Close"].iloc[-1]), 2) if not data.empty else None,
                    "period_return_pct": round(per_ret, 2) if per_ret is not None else None,
                    "volatility_pct":   round(annualized_volatility(rets) * 100, 2),
                    "rsi":              round(rsi_v, 1) if rsi_v else None,
                    "macd_signal":      "bullish" if float(ml.iloc[-1]) > float(sl.iloc[-1]) else "bearish",
                    "pe_ttm":           info.get("trailingPE"),
                    "market_cap_usd":   info.get("marketCap"),
                    "sector":           info.get("sector", "N/A"),
                })
            except Exception as err:
                rows.append({"ticker": tick, "error": str(err)})

        return json.dumps({"period": period, "comparison": rows},
                          indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
#   stdio (default)          — Claude Desktop / local use
#   MCP_TRANSPORT=streamable-http — hosted deployment (Railway, Render, Fly.io)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        port = int(os.environ.get("PORT", 8000))
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()   # blocks; communicates with Claude Desktop over stdio
