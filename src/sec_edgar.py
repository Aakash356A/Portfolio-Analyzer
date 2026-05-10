"""
SEC EDGAR API integration. Free, no API key.

SEC requires a User-Agent header — using a generic personal-use identifier.
Docs: https://www.sec.gov/developer
"""
import re
from datetime import datetime, timedelta

import requests
import streamlit as st

EDGAR_BASE = "https://data.sec.gov"
SEC_BASE   = "https://www.sec.gov"
# SEC requires User-Agent: Name email (personal or company)
HEADERS    = {"User-Agent": "PortfolioTracker research@personal.com"}
TIMEOUT    = 12

# Form types and what they mean for an investor
FORM_LABELS = {
    "8-K":    "Material Event",
    "10-K":   "Annual Report",
    "10-Q":   "Quarterly Report",
    "DEF 14A": "Proxy / Shareholder Vote",
    "4":      "Insider Trade",
    "SC 13G": "Large Holder (5%+)",
    "SC 13D": "Activist Stake (5%+)",
    "S-1":    "IPO / New Offering",
}


@st.cache_data(ttl=86400, show_spinner=False)  # 24h — tickers don't change
def get_cik(ticker: str) -> str | None:
    """
    Map a ticker symbol → 10-digit SEC CIK string.
    Uses SEC's official company_tickers.json (updated nightly by SEC).
    """
    try:
        resp = requests.get(
            f"{SEC_BASE}/files/company_tickers.json",
            headers=HEADERS, timeout=TIMEOUT,
        )
        resp.raise_for_status()
        ticker_up = ticker.upper()
        for entry in resp.json().values():
            if entry.get("ticker", "").upper() == ticker_up:
                return str(entry["cik_str"]).zfill(10)
    except Exception:
        pass
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def get_recent_filings(
    ticker: str,
    form_types: list = None,
    days_back: int = 90,
    max_results: int = 15,
) -> list:
    """
    Return recent SEC filings for a ticker.

    Each result dict:
        form         – filing type (8-K, 10-K, …)
        date         – filing date (YYYY-MM-DD)
        description  – 8-K item codes or form label
        label        – human-readable form type
        url          – direct URL to primary document
        accession    – accession number
    """
    if form_types is None:
        form_types = ["8-K", "10-K", "10-Q", "DEF 14A", "4"]

    cik = get_cik(ticker)
    if not cik:
        return []

    try:
        url  = f"{EDGAR_BASE}/submissions/CIK{cik}.json"
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    recent = data.get("filings", {}).get("recent", {})
    if not recent:
        return []

    forms       = recent.get("form",            [])
    dates       = recent.get("filingDate",       [])
    docs        = recent.get("primaryDocument",  [])
    accessions  = recent.get("accessionNumber",  [])
    items       = recent.get("items",            [])   # 8-K item codes e.g. "1.01,8.01"

    cutoff    = (datetime.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    cik_int   = str(int(cik))  # no leading zeros for URL path

    results = []
    for form, date, doc, acc, item in zip(forms, dates, docs, accessions, items):
        if date < cutoff:
            break  # newest-first → safe to stop
        if form not in form_types:
            continue

        acc_nodash  = acc.replace("-", "")
        filing_url  = f"{SEC_BASE}/Archives/edgar/data/{cik_int}/{acc_nodash}/{doc}"
        description = _describe_filing(form, item)

        results.append({
            "form":        form,
            "date":        date,
            "description": description,
            "label":       FORM_LABELS.get(form, form),
            "url":         filing_url,
            "accession":   acc,
        })

        if len(results) >= max_results:
            break

    return results


@st.cache_data(ttl=7200, show_spinner=False)
def get_filing_text(url: str, max_chars: int = 3000) -> str:
    """
    Download a filing page and return cleaned plain text.
    Used to give the LLM context for summarization.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        text = resp.text
        # Strip HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""


def _describe_filing(form: str, item_codes: str) -> str:
    """Human-readable description based on form type + 8-K item codes."""
    if form != "8-K" or not item_codes:
        return FORM_LABELS.get(form, form)

    # 8-K item code → plain English (most common ones)
    item_map = {
        "1.01": "Entry into material agreement",
        "1.02": "Termination of material agreement",
        "1.05": "Material cybersecurity incident",
        "2.01": "Completion of acquisition/disposal",
        "2.02": "Results of operations (earnings)",
        "2.05": "Departure of key employees / cost-cutting",
        "2.06": "Material impairment",
        "3.01": "Notice of delisting",
        "4.01": "Change in auditor",
        "5.01": "Change in control",
        "5.02": "Director / officer departure or appointment",
        "5.03": "Amendments to charter",
        "7.01": "Regulation FD disclosure",
        "8.01": "Other material events",
        "9.01": "Financial statements / exhibits",
    }
    codes = [c.strip() for c in item_codes.split(",")]
    labels = [item_map.get(c, f"Item {c}") for c in codes if c]
    return "; ".join(labels) if labels else "8-K Filing"
