"""
Summary pipeline: collect data for all holdings → call LLM → save markdown.

Called from the Summary page in app.py.
"""
from datetime import datetime
from pathlib import Path

import pandas as pd

from .analytics import (
    annualized_volatility,
    beta_vs_benchmark,
    calculate_returns,
    max_drawdown,
    portfolio_history,
    sharpe_ratio,
)
from .data_fetcher import get_company_news_rss, get_earnings_info, get_historical_data, get_stock_info
from .indicators import bollinger_bands as _bb, macd as _macd, rsi as _rsi, sma as _sma
from .llm import MODEL_LABEL, generate_portfolio_summary
from .market_context import (
    is_etf,
    lookthrough_block,
    lookthrough_exposure,
    macro_snapshot,
    position_line,
    position_table,
    quality_metrics,
    relative_performance,
)
from .sec_edgar import get_insider_activity, get_recent_filings

SUMMARIES_DIR = Path(__file__).parent.parent / "data" / "summaries"

PERIOD_CONFIG = {
    "Daily":   {"yf_period": "2d",  "days_back": 2,  "label": "daily"},
    "Weekly":  {"yf_period": "5d",  "days_back": 7,  "label": "weekly"},
    "Monthly": {"yf_period": "1mo", "days_back": 30, "label": "monthly"},
}


def _tech_signals(ticker: str) -> dict:
    """Compute key technical indicator signals for the recommendation engine."""
    hist = get_historical_data(ticker, "3mo")
    out: dict = {}
    if hist.empty or len(hist) < 20:
        return out

    closes  = hist["Close"]
    current = float(closes.iloc[-1])

    rsi_s = _rsi(closes)
    if not rsi_s.dropna().empty:
        out["rsi"] = round(float(rsi_s.iloc[-1]), 1)

    ml, sl, hh = _macd(closes)
    hh_clean = hh.dropna()
    if not ml.dropna().empty:
        out["macd_bullish"] = bool(float(ml.iloc[-1]) > float(sl.iloc[-1]))
        if len(hh_clean) >= 2:
            out["macd_crossing_up"] = bool(
                float(hh_clean.iloc[-1]) > 0 and float(hh_clean.iloc[-2]) <= 0
            )

    upper, _, lower = _bb(closes)
    if not upper.dropna().empty:
        bw = float(upper.iloc[-1]) - float(lower.iloc[-1])
        if bw > 0:
            out["bb_pct"] = round((current - float(lower.iloc[-1])) / bw, 2)

    sma20 = _sma(closes, 20)
    if not sma20.dropna().empty:
        out["above_sma20"] = bool(current > float(sma20.iloc[-1]))
    if len(closes) >= 50:
        sma50 = _sma(closes, 50)
        if not sma50.dropna().empty:
            out["above_sma50"] = bool(current > float(sma50.iloc[-1]))

    return out


def _portfolio_metrics(holdings: list, yf_period: str) -> dict:
    """Compute portfolio-level metrics dict for the given period."""
    history  = portfolio_history(holdings, yf_period)
    spy_data = get_historical_data("SPY", yf_period)

    if history.empty or "Total" not in history.columns:
        return {}

    returns  = calculate_returns(history["Total"])
    per_ret  = (history["Total"].iloc[-1] / history["Total"].iloc[0] - 1) * 100
    vol      = annualized_volatility(returns) * 100
    sr       = sharpe_ratio(returns)
    mdd      = max_drawdown(history["Total"]) * 100
    beta     = 0.0
    if not spy_data.empty:
        beta = beta_vs_benchmark(returns, calculate_returns(spy_data["Close"]))

    spy_ret = "N/A"
    if not spy_data.empty and len(spy_data) >= 2:
        spy_ret = f"{(spy_data['Close'].iloc[-1] / spy_data['Close'].iloc[0] - 1) * 100:+.2f}%"

    return {
        "period_return": f"{per_ret:+.2f}%",
        "spy_return":    spy_ret,
        "volatility":    f"{vol:.2f}%",
        # Annualizing a handful of daily returns produces meaningless Sharpe values
        "sharpe":        f"{sr:.2f}" if len(returns) >= 15 else "N/A (window too short)",
        "max_drawdown":  f"{mdd:.2f}%",
        "beta":          f"{beta:.2f}",
    }


def _fundamentals_line(info: dict) -> str:
    """Compact one-liner of the most decision-relevant metrics."""
    q = quality_metrics(info)
    keys = ["P/E (forward)", "PEG", "Revenue growth (YoY)", "Operating margin",
            "Free cash flow (TTM)", "Analyst consensus", "Mean target", "Short % of float"]
    return " | ".join(f"{k} {q[k]}" for k in keys if q.get(k) not in ("N/A", None)) or "N/A"


def _stock_snapshot(holding: dict, yf_period: str, days_back: int, position: dict | None = None) -> dict:
    """Return a dict of per-stock highlights for the summary prompt."""
    ticker  = holding["ticker"]
    info    = get_stock_info(ticker)
    company = info.get("longName", ticker)
    etf     = is_etf(info)

    # Period price return
    price_hist    = get_historical_data(ticker, yf_period)
    period_return = "N/A"
    if not price_hist.empty and len(price_hist) >= 2:
        ret = (price_hist["Close"].iloc[-1] / price_hist["Close"].iloc[0] - 1) * 100
        period_return = f"{ret:+.2f}%"

    # Recent SEC filings
    filings = get_recent_filings(ticker, days_back=days_back,
                                  form_types=["8-K", "10-K", "10-Q"])
    latest_filing = "None"
    filings_list  = []
    if filings:
        f = filings[0]
        latest_filing = f"{f['form']} ({f['date']}): {f['description']}"
        filings_list  = [f"{f['form']} ({f['date']}): {f['description']}" for f in filings[:4]]

    # News headlines
    news          = get_company_news_rss(ticker, company, max_articles=8)
    top_headline  = news[0]["title"] if news else "No recent news"
    news_headlines = [n["title"] for n in news[:8]]

    # Technical signals
    tech = _tech_signals(ticker)

    # Insider activity (Form 4) — always look back at least 90 days for signal
    insider = "N/A (fund)" if etf else get_insider_activity(
        ticker, days_back=max(days_back, 90), max_forms=10)["summary"]

    # Upcoming earnings
    earnings_date = "Unknown"
    eps_estimate  = None
    try:
        ei  = get_earnings_info(ticker)
        cal = ei.get("calendar")
        if isinstance(cal, dict) and cal:
            def _pick(keys):
                for k in keys:
                    if k in cal:
                        v = cal[k]
                        if hasattr(v, "__iter__") and not isinstance(v, str):
                            v = list(v)
                            return v[0] if v else None
                        return v
                return None
            ed = _pick(["Earnings Date", "earningsDate"])
            if ed:
                earnings_date = str(ed)[:10]
            ee = _pick(["EPS Estimate", "epsEstimate", "Earnings Average"])
            if ee is not None:
                try:
                    eps_estimate = round(float(ee), 2)
                except (ValueError, TypeError):
                    pass
    except Exception:
        pass

    return {
        "ticker":          ticker,
        "company":         company,
        "period_return":   period_return,
        "latest_filing":   latest_filing,
        "filings_list":    filings_list,
        "top_headline":    top_headline,
        "news_headlines":  news_headlines,
        "tech":            tech,
        "sector":          info.get("sector", "N/A"),
        "country":         info.get("country", "US"),
        "earnings_date":   earnings_date,
        "eps_estimate":    eps_estimate,
        "is_etf":          etf,
        "position":        position_line(position) if position else "N/A",
        "relative_perf":   relative_performance(ticker, info.get("sector", ""), yf_period),
        "fundamentals":    "See ETF profile" if etf else _fundamentals_line(info),
        "insider":         insider,
    }


def _overview_block(pt: dict) -> str:
    tv, tc = pt["total_value"], pt["total_cost"]
    if not tv:
        return ""
    top = sorted(pt["positions"].items(), key=lambda kv: -kv[1]["value"])[:5]
    lines = [
        f"Total value ${tv:,.0f} | cost basis ${tc:,.0f} | unrealized {(tv / tc - 1) * 100 if tc else 0:+.1f}%",
        f"Positions: {len(pt['positions'])} | top 5 = {sum(p['weight'] for _, p in top):.1f}% of portfolio",
        "Sector weights: " + ", ".join(f"{s} {w:.1f}%" for s, w in pt["sector_weights"].items()),
        "Largest: " + ", ".join(f"{t} {p['weight']:.1f}%" for t, p in top),
        "Note: purchase dates may be placeholders; unrealized P&L uses average cost.",
    ]
    return "\n".join(lines)


def _prior_summary(period_label: str, today_name: str) -> str:
    """Most recent saved summary for the same period, excluding today's."""
    if not SUMMARIES_DIR.exists():
        return ""
    files = sorted(SUMMARIES_DIR.glob(f"*_{period_label.lower()}.md"), reverse=True)
    for f in files:
        if f.stem != today_name:
            return f"(Written {f.stem[:10]})\n" + f.read_text()
    return ""


def run_summary_pipeline(
    holdings: list,
    period_label: str,
    progress_callback=None,
) -> tuple:
    """
    Full pipeline. Returns (summary_text, metrics_dict, per_stock_list).
    progress_callback(pct: float, message: str) is called at each step.
    """
    cfg       = PERIOD_CONFIG.get(period_label, PERIOD_CONFIG["Weekly"])
    yf_period = cfg["yf_period"]
    days_back = cfg["days_back"]

    total = len(holdings) + 4  # metrics + context + per-stock + look-through + LLM call
    step  = [0]

    def _tick(msg: str):
        step[0] += 1
        if progress_callback:
            progress_callback(min(step[0] / total, 0.95), msg)

    _tick("Computing portfolio metrics…")
    metrics = _portfolio_metrics(holdings, yf_period)

    _tick("Loading positions and macro indicators…")
    pt    = position_table(holdings)
    macro = macro_snapshot()

    # Biggest positions first so the prompt reads in order of importance
    ordered = sorted(holdings, key=lambda h: -pt["positions"].get(h["ticker"], {}).get("value", 0))
    holdings_data = []
    for h in ordered:
        _tick(f"Gathering data for {h['ticker']}…")
        holdings_data.append(_stock_snapshot(h, yf_period, days_back, pt["positions"].get(h["ticker"])))

    _tick("Computing ETF look-through exposure…")
    lookthrough = lookthrough_block(lookthrough_exposure(pt["positions"]))

    date_str  = datetime.today().strftime("%Y-%m-%d")
    file_stem = f"{date_str}_{period_label.lower()}"

    _tick(f"Calling {MODEL_LABEL} via OpenRouter…")
    summary_text = generate_portfolio_summary(
        period_label=period_label,
        holdings_data=holdings_data,
        portfolio_metrics=metrics,
        overview=_overview_block(pt),
        lookthrough=lookthrough,
        macro=macro,
        prior_summary=_prior_summary(period_label, file_stem),
    )

    if summary_text.startswith("⚠️"):
        # Don't save LLM errors — they'd be fed back in as the "previous review"
        raise RuntimeError(summary_text)

    # Persist to disk
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    fname = SUMMARIES_DIR / f"{file_stem}.md"
    with open(fname, "w") as fh:
        fh.write(f"# {period_label} Portfolio Summary — {date_str}\n\n")
        fh.write("**Portfolio Metrics:**\n")
        for k, v in metrics.items():
            fh.write(f"- {k.replace('_', ' ').title()}: {v}\n")
        fh.write("\n---\n\n")
        fh.write(summary_text)

    if progress_callback:
        progress_callback(1.0, "Done.")

    return summary_text, metrics, holdings_data


def list_saved_summaries() -> list:
    """Return saved summary files, newest first."""
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(SUMMARIES_DIR.glob("*.md"), reverse=True)
    return [{"path": f, "name": f.stem} for f in files]
