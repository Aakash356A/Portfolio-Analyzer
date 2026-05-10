"""Technical indicators. All take price Series and return Series (or tuples)."""
import pandas as pd
import numpy as np


# ── Trend ──────────────────────────────────────────────────────────────────

def sma(prices: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return prices.rolling(window=period).mean()


def ema(prices: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return prices.ewm(span=period, adjust=False).mean()


# ── Momentum ───────────────────────────────────────────────────────────────

def rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index. >70 overbought, <30 oversold."""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Returns (macd_line, signal_line, histogram)."""
    macd_line = ema(prices, fast) - ema(prices, slow)
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line


# ── Volatility ─────────────────────────────────────────────────────────────

def bollinger_bands(prices: pd.Series, period: int = 20, std_dev: float = 2.0):
    """Returns (upper, middle, lower) bands."""
    middle = sma(prices, period)
    std = prices.rolling(window=period).std()
    return middle + std * std_dev, middle, middle - std * std_dev


# ── Support & Resistance ───────────────────────────────────────────────────

def support_resistance_levels(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 10,
    n_levels: int = 5,
    cluster_tolerance: float = 0.015,  # 1.5% price band to merge nearby levels
) -> tuple:
    """
    Find significant support and resistance levels using local pivot
    highs/lows, then cluster nearby price levels together.

    Algorithm:
    1. A pivot HIGH at index i means high[i] is the maximum within
       [i-window, i+window]. These become potential resistance levels.
    2. A pivot LOW at index i means low[i] is the minimum within
       [i-window, i+window]. These become potential support levels.
    3. All pivots are merged — levels within `cluster_tolerance` of each
       other are averaged into a single level (reduces noise).
    4. Split into support (below current price) and resistance (above).

    Returns:
        (supports, resistances) — both sorted lists of price floats.
        supports[-1] is the strongest (closest below current price).
        resistances[0] is the strongest (closest above current price).
    """
    if len(close) < window * 2 + 1:
        return [], []

    pivot_highs, pivot_lows = [], []

    for i in range(window, len(close) - window):
        slice_high = high.iloc[i - window: i + window + 1]
        slice_low = low.iloc[i - window: i + window + 1]
        if float(high.iloc[i]) == float(slice_high.max()):
            pivot_highs.append(float(high.iloc[i]))
        if float(low.iloc[i]) == float(slice_low.min()):
            pivot_lows.append(float(low.iloc[i]))

    def cluster(levels: list) -> list:
        if not levels:
            return []
        levels = sorted(levels)
        merged = [levels[0]]
        for lvl in levels[1:]:
            if abs(lvl - merged[-1]) / max(abs(merged[-1]), 1e-10) <= cluster_tolerance:
                merged[-1] = (merged[-1] + lvl) / 2  # average nearby pivots
            else:
                merged.append(lvl)
        return merged

    all_levels = cluster(pivot_highs + pivot_lows)
    current = float(close.iloc[-1])

    # Give a tiny buffer so current price doesn't land exactly on a level
    supports = sorted([l for l in all_levels if l < current * 0.998])[-n_levels:]
    resistances = sorted([l for l in all_levels if l >= current * 0.998])[:n_levels]

    return supports, resistances


def pivot_points(high: float, low: float, close: float) -> dict:
    """
    Classic daily pivot points (PP, S1/S2/S3, R1/R2/R3).
    Pass the previous session's high, low, close.
    Useful for intraday and short-term swing traders.
    """
    pp = (high + low + close) / 3
    return {
        "PP": pp,
        "R1": 2 * pp - low,
        "R2": pp + (high - low),
        "R3": high + 2 * (pp - low),
        "S1": 2 * pp - high,
        "S2": pp - (high - low),
        "S3": low - 2 * (high - pp),
    }
