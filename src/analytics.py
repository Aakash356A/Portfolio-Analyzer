"""Portfolio-level analytics: metrics, returns, risk measures."""
import numpy as np
import pandas as pd

from .data_fetcher import get_current_price, get_historical_data


def calculate_portfolio_metrics(holdings: list) -> pd.DataFrame:
    """Build a DataFrame of current position values and P&L."""
    rows = []
    for h in holdings:
        current = get_current_price(h["ticker"])
        if current is None:
            continue
        cost = h["shares"] * h["purchase_price"]
        market_value = h["shares"] * current
        pnl = market_value - cost
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0
        rows.append({
            "Ticker": h["ticker"],
            "Shares": h["shares"],
            "Purchase Price": h["purchase_price"],
            "Current Price": current,
            "Cost Basis": cost,
            "Market Value": market_value,
            "P&L ($)": pnl,
            "P&L (%)": pnl_pct,
            "Purchase Date": h.get("purchase_date", ""),
        })
    return pd.DataFrame(rows)


def calculate_returns(prices: pd.Series) -> pd.Series:
    """Daily simple returns."""
    return prices.pct_change().dropna()


def annualized_volatility(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Annualized standard deviation of returns."""
    if returns.empty:
        return 0.0
    return float(returns.std() * np.sqrt(periods_per_year))


def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.04, periods_per_year: int = 252) -> float:
    """Sharpe ratio. Default risk-free rate ~4% (rough US T-bill yield)."""
    if returns.empty:
        return 0.0
    annualized_return = returns.mean() * periods_per_year
    excess = annualized_return - risk_free_rate
    vol = annualized_volatility(returns, periods_per_year)
    return float(excess / vol) if vol > 0 else 0.0


def max_drawdown(prices: pd.Series) -> float:
    """Largest peak-to-trough decline (negative number)."""
    if prices.empty:
        return 0.0
    cumulative = (1 + prices.pct_change().fillna(0)).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    return float(drawdown.min())


def beta_vs_benchmark(asset_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    """Beta = cov(asset, benchmark) / var(benchmark)."""
    aligned = pd.concat([asset_returns, benchmark_returns], axis=1, join="inner").dropna()
    if len(aligned) < 2:
        return 0.0
    cov = aligned.iloc[:, 0].cov(aligned.iloc[:, 1])
    var = aligned.iloc[:, 1].var()
    return float(cov / var) if var > 0 else 0.0


def portfolio_history(holdings: list, period: str = "1y") -> pd.DataFrame:
    """Historical portfolio value as the sum of (shares * close) per ticker per day."""
    if not holdings:
        return pd.DataFrame()

    series_by_ticker = {}
    for h in holdings:
        hist = get_historical_data(h["ticker"], period)
        if hist.empty:
            continue
        # Naive: assumes you held current shares for the full period.
        # Good enough for tracking how the *current* book has performed.
        series_by_ticker[h["ticker"]] = hist["Close"] * h["shares"]

    if not series_by_ticker:
        return pd.DataFrame()

    df = pd.DataFrame(series_by_ticker).ffill()
    df["Total"] = df.sum(axis=1)
    return df
