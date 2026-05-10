"""
Real-time news monitor for portfolio companies.

Source speed tiers (from fastest to slowest):
  ⚡⚡⚡⚡  SEC EDGAR 8-K   — companies file *before* press release; instant
  ⚡⚡⚡    Business Wire   — primary press release wire; 0-2 min
  ⚡⚡⚡    PR Newswire     — second major wire; 0-2 min
  ⚡⚡      Yahoo Finance   — syndicates wires quickly; 2-5 min
  ⚡        Google News     — broad aggregation; 5-15 min

Strategy: poll the top three on a short cycle (60-120s),
use Yahoo/Google to catch anything they miss.
"""

import hashlib
import re
from datetime import date, datetime, timezone
from typing import Optional

import feedparser
import requests
import streamlit as st

HEADERS = {"User-Agent": "PersonalPortfolioMonitor research@personal.com"}
TIMEOUT = 8

# ─────────────────────────────────────────────────────────────────────────────
# Significance scoring (rule-based, fast, no LLM needed for alerts)
# ─────────────────────────────────────────────────────────────────────────────

IMPACT_RULES = [
    # (keywords,  score, label)
    (["acquisition","acquires","acquire","merger","acquired","takeover",
      "buyout","tender offer","chip deal","major deal","historic deal",
      "landmark deal","strategic deal"],                                 10, "🔴 M&A"),
    (["fda approval","fda approved","fda approves","clearance","breakthrough therapy",
      "accelerated approval","nda approved","fda clears","fda grants"],  10, "🔴 FDA"),
    (["bankruptcy","chapter 11","chapter 7","insolvency","default",
      "debt restructuring"],                                             10, "🔴 Distress"),
    (["deal","agreement","partnership","contract awarded","selected as",
      "chosen as","signed with","joint venture"],                         8, "🟠 Deal"),
    (["earnings","quarterly results","revenue","eps","beat","missed",
      "guidance","outlook","raised guidance","lowered guidance"],          8, "🟠 Earnings"),
    (["ceo","cfo","cto","chief executive","president resigns","appoints",
      "named as","stepping down","fired","departure"],                    7, "🟡 Leadership"),
    (["layoffs","job cuts","restructuring","workforce reduction",
      "downsizing","headcount"],                                          7, "🟡 Restructuring"),
    (["lawsuit","sec investigation","doj probe","subpoena","class action",
      "fraud","accounting irregularities"],                               8, "🟠 Legal"),
    (["recall","safety warning","product defect","hazard"],               8, "🟠 Safety"),
    (["dividend","special dividend","buyback","share repurchase",
      "increased dividend"],                                              6, "🟡 Capital Return"),
    (["stock split","reverse split","spinoff","spin-off","ipo"],          6, "🟡 Corporate Action"),
    (["upgrade","downgrade","price target","overweight","underweight",
      "buy rating","sell rating"],                                        5, "🟢 Analyst"),
    (["investment","funding","raised","series","venture"],                5, "🟢 Funding"),
    (["product launch","unveiled","announces new","introduces"],          5, "🟢 Product"),
]


def score_article(title: str) -> tuple[int, str]:
    """
    Rule-based significance score (1-10) + label.
    Runs in microseconds — suitable for polling loops.
    """
    title_lower = title.lower()
    best_score, best_label = 3, "⚪ General"
    for keywords, score, label in IMPACT_RULES:
        if any(kw in title_lower for kw in keywords):
            if score > best_score:
                best_score, best_label = score, label
    return best_score, best_label


def article_id(article: dict) -> str:
    """Stable ID for deduplication across refreshes."""
    key = article.get("link") or article.get("title", "")
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ─────────────────────────────────────────────────────────────────────────────
# Individual source fetchers
# ─────────────────────────────────────────────────────────────────────────────

def _make_article(title, link, published, summary, source, speed) -> dict:
    a = {
        "title":     title.strip(),
        "link":      link,
        "published": published,
        "summary":   re.sub(r"<[^>]+>", "", summary or "")[:220],
        "source":    source,
        "speed":     speed,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    score, label = score_article(title)
    a["score"] = score
    a["label"] = label
    a["id"]    = article_id(a)
    return a


def fetch_sec_8k_today(ticker: str) -> list:
    """
    Query SEC EDGAR full-text search for today's 8-K filings for this ticker.
    8-Ks must be filed within 4 business days of a material event — for major
    deals/earnings, companies file same day, often BEFORE the press release.
    """
    today = date.today().isoformat()
    url   = (
        "https://efts.sec.gov/LATEST/search-index?"
        f"q=%22{ticker}%22&forms=8-K"
        f"&dateRange=custom&startdt={today}&enddt={today}"
    )
    results = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        for h in hits[:5]:
            src   = h.get("_source", {})
            items = src.get("items", "") or ""
            names = src.get("display_names", [""])
            fdate = src.get("file_date", today)
            furl  = "https://www.sec.gov" + src.get("file_url", "")
            title = f"[8-K] {names[0]} — {items or 'Material Event'}"
            results.append(_make_article(
                title=title, link=furl,
                published=fdate, summary=f"Form 8-K | {items}",
                source="SEC EDGAR", speed="⚡⚡⚡⚡",
            ))
            # 8-K always gets a minimum score of 7 — it's an official material event
            results[-1]["score"] = max(results[-1]["score"], 7)
            results[-1]["label"] = results[-1]["label"] if results[-1]["score"] >= 8 \
                                   else "🟠 SEC Filing"
    except Exception:
        pass
    return results


def fetch_businesswire(ticker: str, company: str) -> list:
    """Business Wire RSS — one of the two primary press release wires."""
    urls = [
        f"https://feed.businesswire.com/rss/home/?rss=G1&tag={ticker}",
        f"https://feed.businesswire.com/rss/home/?rss=G22&tag={company.split()[0]}",
    ]
    results = []
    for url in urls:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:10]:
                results.append(_make_article(
                    title=e.get("title",""),
                    link=e.get("link",""),
                    published=e.get("published",""),
                    summary=e.get("summary",""),
                    source="Business Wire", speed="⚡⚡⚡",
                ))
            if results:
                break
        except Exception:
            continue
    return results


def fetch_prnewswire(company: str, ticker: str) -> list:
    """PR Newswire RSS — filtered to company name."""
    url = "https://www.prnewswire.com/rss/news-releases-list.rss"
    results = []
    name_words = [w.lower() for w in company.split()[:2] if len(w) > 2]
    try:
        feed = feedparser.parse(url)
        for e in feed.entries[:40]:
            title = e.get("title", "")
            if ticker.lower() in title.lower() or \
               any(w in title.lower() for w in name_words):
                results.append(_make_article(
                    title=title,
                    link=e.get("link",""),
                    published=e.get("published",""),
                    summary=e.get("summary",""),
                    source="PR Newswire", speed="⚡⚡⚡",
                ))
    except Exception:
        pass
    return results[:8]


def fetch_yahoo_rss(ticker: str) -> list:
    """Yahoo Finance RSS — fast syndication of wire stories."""
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    results = []
    try:
        feed = feedparser.parse(url)
        for e in feed.entries[:15]:
            results.append(_make_article(
                title=e.get("title",""),
                link=e.get("link",""),
                published=e.get("published",""),
                summary=e.get("summary",""),
                source="Yahoo Finance", speed="⚡⚡",
            ))
    except Exception:
        pass
    return results


def fetch_google_news(company: str, ticker: str) -> list:
    """Google News RSS — broad coverage, slower aggregation."""
    query = f"{company} {ticker}".replace(" ","+")
    url   = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    results = []
    try:
        feed = feedparser.parse(url)
        for e in feed.entries[:10]:
            results.append(_make_article(
                title=e.get("title",""),
                link=e.get("link",""),
                published=e.get("published",""),
                summary="",
                source="Google News", speed="⚡",
            ))
    except Exception:
        pass
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Aggregator
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=90, show_spinner=False)  # 90-second cache
def fetch_all(ticker: str, company: str) -> list:
    """
    Fetch all sources for a ticker, deduplicate, sort by significance then recency.
    TTL = 90 seconds — aggressive for a monitor, reasonable for RSS rate limits.
    """
    raw = []
    raw.extend(fetch_sec_8k_today(ticker))
    raw.extend(fetch_businesswire(ticker, company))
    raw.extend(fetch_prnewswire(company, ticker))
    raw.extend(fetch_yahoo_rss(ticker))
    raw.extend(fetch_google_news(company, ticker))

    # Deduplicate on article_id (URL-based hash)
    seen, deduped = set(), []
    for a in raw:
        if a.get("title") and a["id"] not in seen:
            seen.add(a["id"])
            deduped.append(a)

    # Sort: high score first, then by fetch time (newest first within same score)
    deduped.sort(key=lambda x: (-x["score"], x.get("fetched_at","") ), reverse=False)
    deduped.sort(key=lambda x: x["score"], reverse=True)

    return deduped


def score_color(score: int) -> str:
    if score >= 9: return "#e74c3c"   # red
    if score >= 7: return "#e67e22"   # orange
    if score >= 5: return "#f1c40f"   # yellow
    return "#95a5a6"                  # gray


def score_bg(score: int) -> str:
    if score >= 9: return "rgba(231,76,60,0.12)"
    if score >= 7: return "rgba(230,126,34,0.10)"
    if score >= 5: return "rgba(241,196,15,0.10)"
    return "transparent"
