"""
Extra context for the LLM prompts: positions, valuation/quality metrics,
sector-relative performance, macro indicators and ETF look-through.

Everything here comes from yfinance (free, no key) and degrades to "N/A"
or an empty result when a field is missing.
"""
import pandas as pd
import streamlit as st
import yfinance as yf

from .data_fetcher import get_current_price, get_historical_data, get_stock_info

# Sector (as yfinance reports it) → SPDR sector ETF used as the peer benchmark
SECTOR_ETF = {
    "Technology":             "XLK",
    "Healthcare":             "XLV",
    "Financial Services":     "XLF",
    "Consumer Cyclical":      "XLY",
    "Consumer Defensive":     "XLP",
    "Communication Services": "XLC",
    "Industrials":            "XLI",
    "Energy":                 "XLE",
    "Utilities":              "XLU",
    "Real Estate":            "XLRE",
    "Basic Materials":        "XLB",
}

# Macro indicators available as yfinance tickers
MACRO_TICKERS = {
    "10Y Treasury yield": "^TNX",
    "VIX (volatility)":   "^VIX",
    "US Dollar Index":    "DX-Y.NYB",
    "WTI crude oil":      "CL=F",
    "Gold":               "GC=F",
}


# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────────────────────

def _num(v):
    try:
        f = float(v)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _pct(v, already_pct: bool = False) -> str:
    f = _num(v)
    if f is None:
        return "N/A"
    return f"{f:.1f}%" if already_pct else f"{f * 100:.1f}%"


def _x(v, digits: int = 1) -> str:
    f = _num(v)
    return "N/A" if f is None else f"{f:.{digits}f}"


def _money(v) -> str:
    f = _num(v)
    if f is None:
        return "N/A"
    sign = "-" if f < 0 else ""
    f = abs(f)
    for div, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if f >= div:
            return f"{sign}${f / div:.1f}{unit}"
    return f"{sign}${f:,.0f}"


def is_etf(info: dict) -> bool:
    return (info or {}).get("quoteType", "").upper() in ("ETF", "MUTUALFUND")


# ─────────────────────────────────────────────────────────────────────────────
# Positions
# ─────────────────────────────────────────────────────────────────────────────

def position_table(holdings: list) -> dict:
    """
    Current value, weight and unrealized P&L for every holding, plus sector
    weights. Returns {"positions": {ticker: {...}}, "total_value", "total_cost",
    "sector_weights": {sector: pct}}.
    """
    positions = {}
    for h in holdings:
        price = get_current_price(h["ticker"])
        if price is None:
            continue
        cost  = h["shares"] * h["avg_price"]
        value = h["shares"] * price
        positions[h["ticker"]] = {
            "shares":         h["shares"],
            "avg_cost":       h["avg_price"],
            "price":          price,
            "value":          value,
            "cost":           cost,
            "unrealized_pct": (value / cost - 1) * 100 if cost > 0 else 0.0,
            "unrealized_usd": value - cost,
        }

    total_value = sum(p["value"] for p in positions.values())
    total_cost  = sum(p["cost"] for p in positions.values())
    sector_weights: dict = {}
    for t, p in positions.items():
        p["weight"] = p["value"] / total_value * 100 if total_value else 0.0
        info = get_stock_info(t)
        sector = "ETF / Fund" if is_etf(info) else info.get("sector", "Unknown")
        p["sector"] = sector
        sector_weights[sector] = sector_weights.get(sector, 0.0) + p["weight"]

    return {
        "positions":      positions,
        "total_value":    total_value,
        "total_cost":     total_cost,
        "sector_weights": dict(sorted(sector_weights.items(), key=lambda kv: -kv[1])),
    }


def position_line(p: dict) -> str:
    return (
        f"{p['weight']:.1f}% of portfolio ({_money(p['value'])}) | "
        f"{p['shares']:g} sh @ avg ${p['avg_cost']:.2f}, now ${p['price']:.2f} | "
        f"unrealized {p['unrealized_pct']:+.1f}% ({_money(p['unrealized_usd'])})"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Valuation, quality and analyst data
# ─────────────────────────────────────────────────────────────────────────────

def quality_metrics(info: dict) -> dict:
    """Growth, margins, balance sheet, valuation multiples and analyst view."""
    price  = _num(info.get("currentPrice") or info.get("regularMarketPrice"))
    target = _num(info.get("targetMeanPrice"))
    upside = f"{(target / price - 1) * 100:+.1f}%" if price and target else "N/A"
    return {
        "Revenue growth (YoY)":   _pct(info.get("revenueGrowth")),
        "Earnings growth (YoY)":  _pct(info.get("earningsGrowth")),
        "Gross margin":           _pct(info.get("grossMargins")),
        "Operating margin":       _pct(info.get("operatingMargins")),
        "Profit margin":          _pct(info.get("profitMargins")),
        "ROE":                    _pct(info.get("returnOnEquity")),
        "Free cash flow (TTM)":   _money(info.get("freeCashflow")),
        "Total cash":             _money(info.get("totalCash")),
        "Total debt":             _money(info.get("totalDebt")),
        "Debt/Equity (%)":        _x(info.get("debtToEquity")),
        "P/E (TTM)":              _x(info.get("trailingPE")),
        "P/E (forward)":          _x(info.get("forwardPE")),
        "PEG":                    _x(info.get("trailingPegRatio") or info.get("pegRatio"), 2),
        "EV/EBITDA":              _x(info.get("enterpriseToEbitda")),
        "Price/Sales":            _x(info.get("priceToSalesTrailing12Months")),
        "Analyst consensus":      (info.get("recommendationKey") or "N/A").replace("_", " "),
        "# analysts":             info.get("numberOfAnalystOpinions", "N/A"),
        "Mean target":            f"${target:.2f} ({upside} vs price)" if target else "N/A",
        "Target range":           (f"${_x(info.get('targetLowPrice'), 2)} – ${_x(info.get('targetHighPrice'), 2)}"
                                   if info.get("targetLowPrice") else "N/A"),
        "Short % of float":       _pct(info.get("shortPercentOfFloat")),
        "52w range":              (f"${_x(info.get('fiftyTwoWeekLow'), 2)} – ${_x(info.get('fiftyTwoWeekHigh'), 2)}"
                                   if info.get("fiftyTwoWeekLow") else "N/A"),
    }


def metrics_block(metrics: dict, indent: str = "") -> str:
    return "\n".join(f"{indent}{k}: {v}" for k, v in metrics.items() if v not in ("N/A", None))


def earnings_surprises(earnings_history) -> str:
    """Last 4 quarters of EPS actual vs estimate with surprise %."""
    eh = earnings_history
    if eh is None or getattr(eh, "empty", True):
        return "No earnings history available."
    cols = {c.lower(): c for c in eh.columns}
    ac = next((cols[k] for k in cols if "actual" in k), None)
    ec = next((cols[k] for k in cols if "estimate" in k), None)
    qc = next((cols[k] for k in cols if "quarter" in k or "date" in k), None)
    if not (ac and ec):
        return "No earnings history available."
    lines = []
    for _, r in eh.tail(4).iterrows():
        a, e = _num(r[ac]), _num(r[ec])
        if a is None or e is None:
            continue
        surprise = f"{(a - e) / abs(e) * 100:+.1f}%" if e else "n/a"
        verdict  = "beat" if a >= e else "miss"
        label    = str(r[qc])[:10] if qc else ""
        lines.append(f"{label}: actual ${a:.2f} vs est ${e:.2f} → {verdict} ({surprise})")
    return "\n".join(lines) or "No earnings history available."


# ─────────────────────────────────────────────────────────────────────────────
# Relative performance and macro
# ─────────────────────────────────────────────────────────────────────────────

def _period_return(ticker: str, yf_period: str):
    hist = get_historical_data(ticker, yf_period)
    if hist.empty or len(hist) < 2:
        return None
    return (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100


def relative_performance(ticker: str, sector: str, yf_period: str) -> str:
    """'+4.2% vs XLK +6.1% vs SPY +2.0%' style comparison."""
    own = _period_return(ticker, yf_period)
    if own is None:
        return "N/A"
    parts = [f"{ticker} {own:+.1f}%"]
    etf = SECTOR_ETF.get(sector)
    if etf and etf != ticker:
        r = _period_return(etf, yf_period)
        if r is not None:
            parts.append(f"sector {etf} {r:+.1f}% (relative {own - r:+.1f} pts)")
    spy = _period_return("SPY", yf_period)
    if spy is not None and ticker != "SPY":
        parts.append(f"SPY {spy:+.1f}% (relative {own - spy:+.1f} pts)")
    return " | ".join(parts)


@st.cache_data(ttl=1800, show_spinner=False)
def macro_snapshot() -> str:
    """Current level and 1-month change for rates, volatility, dollar, oil, gold."""
    lines = []
    for label, t in MACRO_TICKERS.items():
        hist = get_historical_data(t, "1mo")
        if hist.empty:
            continue
        last, first = float(hist["Close"].iloc[-1]), float(hist["Close"].iloc[0])
        if t == "^TNX":
            lines.append(f"- {label}: {last:.2f}% ({(last - first) * 100:+.0f} bps over 1 month)")
        else:
            lines.append(f"- {label}: {last:,.2f} ({(last / first - 1) * 100:+.1f}% over 1 month)")
    return "\n".join(lines) or "Macro data unavailable."


# ─────────────────────────────────────────────────────────────────────────────
# ETFs
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=86400, show_spinner=False)
def etf_top_holdings(ticker: str) -> list:
    """[(symbol, name, weight_pct), …] for an ETF's top holdings."""
    try:
        df = yf.Ticker(ticker).funds_data.top_holdings
    except Exception:
        return []
    if df is None or df.empty:
        return []
    wcol = next((c for c in df.columns if "percent" in c.lower()), df.columns[-1])
    ncol = next((c for c in df.columns if "name" in c.lower()), None)
    out = []
    for sym, row in df.iterrows():
        w = _num(row[wcol])
        if w is None:
            continue
        out.append((str(sym), str(row[ncol]) if ncol else str(sym), w * 100 if w <= 1 else w))
    return out


def etf_profile(ticker: str, info: dict) -> dict:
    er = info.get("netExpenseRatio")
    if _num(er) is None and _num(info.get("annualReportExpenseRatio")) is not None:
        er = _num(info.get("annualReportExpenseRatio")) * 100
    er_str = f"{_num(er):.2f}%" if _num(er) is not None else "N/A"
    return {
        "Category":        info.get("category", "N/A"),
        "Fund family":     info.get("fundFamily", "N/A"),
        "Expense ratio":   er_str,
        "Total assets":    _money(info.get("totalAssets")),
        "Yield":           _pct(info.get("yield")),
        "YTD return":      _pct(info.get("ytdReturn"), already_pct=True),
        "3y avg return":   _pct(info.get("threeYearAverageReturn")),
        "Beta (3y)":       _x(info.get("beta3Year"), 2),
    }


def lookthrough_exposure(positions: dict, top_n: int = 12) -> list:
    """
    True exposure per underlying stock = direct weight + Σ(ETF weight × stock's
    weight inside that ETF). Only ETF *top* holdings are known, so this is a
    lower bound. Returns [(symbol, total_pct, direct_pct, via_etfs_pct, sources)].
    """
    direct: dict = {t: p["weight"] for t, p in positions.items() if p.get("sector") != "ETF / Fund"}
    via: dict = {}
    sources: dict = {}
    for t, p in positions.items():
        if p.get("sector") != "ETF / Fund":
            continue
        for sym, _, w in etf_top_holdings(t):
            # yfinance sometimes uses GOOG for Alphabet; fold into GOOGL when held
            sym = "GOOGL" if sym == "GOOG" and "GOOGL" in positions else sym
            contrib = p["weight"] * w / 100
            via[sym] = via.get(sym, 0.0) + contrib
            sources.setdefault(sym, []).append(t)

    rows = []
    for sym in set(direct) | set(via):
        d, v = direct.get(sym, 0.0), via.get(sym, 0.0)
        rows.append((sym, d + v, d, v, sorted(set(sources.get(sym, [])))))
    rows.sort(key=lambda r: -r[1])
    return rows[:top_n]


def lookthrough_block(rows: list) -> str:
    if not rows:
        return "No ETF holdings data."
    lines = []
    for sym, tot, d, v, src in rows:
        extra = f" + {v:.1f}% via {', '.join(src)}" if v > 0.05 else ""
        lines.append(f"- {sym}: {tot:.1f}% total (direct {d:.1f}%{extra})")
    return "\n".join(lines)
