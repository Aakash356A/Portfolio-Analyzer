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
from .llm import generate_portfolio_summary
from .sec_edgar import get_recent_filings

SUMMARIES_DIR = Path("data/summaries")

PERIOD_CONFIG = {
    "Daily":   {"yf_period": "5d",  "days_back": 2,  "label": "daily"},
    "Weekly":  {"yf_period": "1mo", "days_back": 7,  "label": "weekly"},
    "Monthly": {"yf_period": "3mo", "days_back": 30, "label": "monthly"},
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

    return {
        "period_return": f"{per_ret:+.2f}%",
        "volatility":    f"{vol:.2f}%",
        "sharpe":        f"{sr:.2f}",
        "max_drawdown":  f"{mdd:.2f}%",
        "beta":          f"{beta:.2f}",
    }


def _stock_snapshot(holding: dict, yf_period: str, days_back: int) -> dict:
    """Return a dict of per-stock highlights for the summary prompt."""
    ticker  = holding["ticker"]
    info    = get_stock_info(ticker)
    company = info.get("longName", ticker)

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
    }


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

    total = len(holdings) + 2  # portfolio metrics + per-stock + LLM call
    step  = [0]

    def _tick(msg: str):
        step[0] += 1
        if progress_callback:
            progress_callback(min(step[0] / total, 0.95), msg)

    _tick("Computing portfolio metrics…")
    metrics = _portfolio_metrics(holdings, yf_period)

    holdings_data = []
    for h in holdings:
        _tick(f"Gathering data for {h['ticker']}…")
        holdings_data.append(_stock_snapshot(h, yf_period, days_back))

    _tick("Calling Claude Sonnet 4.6 via OpenRouter…")
    summary_text = generate_portfolio_summary(
        period_label=period_label,
        holdings_data=holdings_data,
        portfolio_metrics=metrics,
    )

    # Persist to disk
    SUMMARIES_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.today().strftime("%Y-%m-%d")
    fname    = SUMMARIES_DIR / f"{date_str}_{period_label.lower()}.md"
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
