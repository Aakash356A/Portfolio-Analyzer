"""Thin wrapper around yfinance + RSS news feeds with Streamlit caching."""
import feedparser
import pandas as pd
import streamlit as st
import yfinance as yf


@st.cache_data(ttl=300, show_spinner=False)
def get_current_price(ticker: str):
    """Latest close. Returns None if ticker is bad or data missing."""
    try:
        data = yf.Ticker(ticker).history(period="2d")
        if data.empty:
            return None
        return float(data["Close"].iloc[-1])
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def get_historical_data(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """OHLCV history. Supports interval='1d' (daily) or '1wk' (weekly)."""
    try:
        data = yf.Ticker(ticker).history(period=period, interval=interval)
        return data if data is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def get_stock_info(ticker: str) -> dict:
    """Company metadata: sector, industry, market cap, P/E, beta, etc."""
    try:
        return yf.Ticker(ticker).info or {}
    except Exception:
        return {}


@st.cache_data(ttl=3600, show_spinner=False)
def get_earnings_info(ticker: str) -> dict:
    """
    Earnings calendar (next date + estimates) and historical EPS beat/miss.
    Uses yfinance — no API key needed.
    """
    stock = yf.Ticker(ticker)
    result = {
        "calendar": None,
        "earnings_history": None,
        "quarterly_financials": None,
        "annual_financials": None,
    }
    try:
        cal = stock.calendar
        if isinstance(cal, dict) and cal:
            result["calendar"] = cal
        elif hasattr(cal, "to_dict"):
            result["calendar"] = cal.to_dict()
    except Exception:
        pass
    try:
        eh = stock.earnings_history
        if eh is not None and not eh.empty:
            result["earnings_history"] = eh.reset_index()
    except Exception:
        pass
    try:
        qf = stock.quarterly_income_stmt
        if qf is not None and not qf.empty:
            result["quarterly_financials"] = qf
    except Exception:
        pass
    try:
        af = stock.income_stmt
        if af is not None and not af.empty:
            result["annual_financials"] = af
    except Exception:
        pass
    return result


@st.cache_data(ttl=1800, show_spinner=False)
def get_company_news_rss(ticker: str, company_name: str = "", max_articles: int = 20) -> list:
    """
    Fetch recent news via Google News RSS + Yahoo Finance RSS.
    Completely free, no API key needed.
    """
    query = (company_name or ticker).replace(" ", "+")
    urls = [
        f"https://news.google.com/rss/search?q={query}+stock&hl=en-US&gl=US&ceid=US:en",
        f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US",
    ]
    articles = []
    seen = set()
    for url in urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                if title and title not in seen:
                    seen.add(title)
                    articles.append({
                        "title": title,
                        "link": entry.get("link", ""),
                        "published": entry.get("published", ""),
                        "summary": entry.get("summary", ""),
                        "source": feed.feed.get("title", ""),
                    })
        except Exception:
            continue
    return articles[:max_articles]
