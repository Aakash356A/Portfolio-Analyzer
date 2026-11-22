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


@st.cache_data(ttl=86400, show_spinner=False)
def _filing_plain_text(url: str) -> str:
    """Full filing as plain text (no length cap)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"&nbsp;|&#160;|&#xa0;", " ", text, flags=re.I)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&#8217;|&rsquo;", "'", text)
        text = re.sub(r"&#\d+;|&[a-z]+;", " ", text)
        return re.sub(r"\s+", " ", text).strip()
    except Exception:
        return ""


_XREF = re.compile(r"(refer to|see|in|under|with|within|described in|part i,?)\s*[\"“']?\s*$", re.I)


def _extract_section(text: str, start_pat: str, end_pat: str, max_chars: int) -> str:
    """
    Pull one 'Item X' section out of a 10-K/10-Q. The heading also appears in
    the table of contents, so take the start match with the longest span to
    its next end match — that is the real section body.
    """
    # Drop cross-references like "Refer to Item 1A. Risk Factors"
    starts = [m.start() for m in re.finditer(start_pat, text, flags=re.I)
              if not _XREF.search(text[max(0, m.start() - 40):m.start()])]
    ends   = [m.start() for m in re.finditer(end_pat,   text, flags=re.I)]
    best = ""
    for s in starts:
        e = next((e for e in ends if e > s + 20), None)
        chunk = text[s:e] if e else text[s:s + max_chars]
        if len(chunk) > len(best):
            best = chunk
    return best[:max_chars]


# Section patterns per form: (label, start, end)
_SECTIONS = {
    "10-K": [
        ("Risk Factors", r"item\s*1a\.?\s*[-–—:]?\s*risk\s+factors", r"item\s*1b\.?|item\s*1c\.?|item\s*2\.?\s*[-–—:]?\s*properties"),
        ("MD&A",         r"item\s*7\.?\s*[-–—:]?\s*management.s\s+discussion", r"item\s*7a\.?|item\s*8\.?\s*[-–—:]?\s*financial"),
    ],
    "10-Q": [
        ("MD&A",         r"item\s*2\.?\s*[-–—:]?\s*management.s\s+discussion", r"item\s*3\.?\s*[-–—:]?\s*quantitative|item\s*4\.?\s*[-–—:]?\s*controls"),
    ],
}


def get_filing_digest(form: str, url: str, max_chars: int = 12000) -> str:
    """
    The parts of a filing worth an LLM's attention:
      10-K / 10-Q → Risk Factors + MD&A sections
      everything else (8-K, proxy, …) → body text after the cover page
    """
    text = _filing_plain_text(url)
    if not text:
        return ""
    sections = _SECTIONS.get(form.replace("/A", ""))
    if sections:
        per = max_chars // len(sections)
        parts = []
        for label, sp, ep in sections:
            body = _extract_section(text, sp, ep, per)
            if len(body) > 500:
                parts.append(f"[{label}]\n{body}")
        if parts:
            return "\n\n".join(parts)
    # 8-K etc.: skip the boilerplate cover page when possible
    m = re.search(r"item\s*\d\.\d\d", text, flags=re.I)
    start = m.start() if m else 0
    return text[start:start + max_chars]


@st.cache_data(ttl=86400, show_spinner=False)
def get_latest_annual_risk_factors(ticker: str, max_chars: int = 6000) -> str:
    """Risk Factors section of the most recent 10-K (last ~13 months)."""
    filings = get_recent_filings(ticker, form_types=["10-K"], days_back=400, max_results=1)
    if not filings:
        return ""
    text = _filing_plain_text(filings[0]["url"])
    start, end = _SECTIONS["10-K"][0][1:]
    return _extract_section(text, start, end, max_chars)


def _form4_xml_url(url: str) -> str:
    """Form 4 primaryDocument points at the XSL-rendered view; strip it for raw XML."""
    return re.sub(r"/xslF345X\d+/", "/", url)


@st.cache_data(ttl=86400, show_spinner=False)
def _parse_form4(url: str) -> list:
    """Open-market transactions in one Form 4: [{name, title, code, shares, price, date}]."""
    import xml.etree.ElementTree as ET
    try:
        resp = requests.get(_form4_xml_url(url), headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception:
        return []

    def _t(node, path):
        el = node.find(path)
        return (el.text or "").strip() if el is not None and el.text else ""

    owner = root.find("reportingOwner")
    name  = _t(owner, "reportingOwnerId/rptOwnerName") if owner is not None else ""
    rel   = owner.find("reportingOwnerRelationship") if owner is not None else None
    title = ""
    if rel is not None:
        title = _t(rel, "officerTitle") or (
            "Director" if _t(rel, "isDirector") in ("1", "true") else
            "10% owner" if _t(rel, "isTenPercentOwner") in ("1", "true") else "")

    out = []
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _t(tx, "transactionCoding/transactionCode")
        if code not in ("P", "S"):  # P = open-market buy, S = open-market sale
            continue
        try:
            shares = float(_t(tx, "transactionAmounts/transactionShares/value") or 0)
            price  = float(_t(tx, "transactionAmounts/transactionPricePerShare/value") or 0)
        except ValueError:
            continue
        out.append({
            "name": name, "title": title, "code": code,
            "shares": shares, "price": price,
            "date": _t(tx, "transactionDate/value"),
            "planned": "10b5-1" in resp.text,
        })
    return out


def get_insider_activity(ticker: str, days_back: int = 90, max_forms: int = 20) -> dict:
    """
    Summarize open-market insider buys/sells from Form 4 filings.
    Returns {"buys_usd", "sells_usd", "n_buys", "n_sells", "lines": [...], "summary": str}.
    """
    forms = get_recent_filings(ticker, form_types=["4"], days_back=days_back, max_results=max_forms)
    txs = []
    for f in forms:
        txs.extend(_parse_form4(f["url"]))

    buys  = [t for t in txs if t["code"] == "P"]
    sells = [t for t in txs if t["code"] == "S"]
    buys_usd  = sum(t["shares"] * t["price"] for t in buys)
    sells_usd = sum(t["shares"] * t["price"] for t in sells)

    # Aggregate per insider for readable lines
    agg: dict = {}
    for t in txs:
        k = (t["name"], t["title"], t["code"])
        a = agg.setdefault(k, {"usd": 0.0, "shares": 0.0, "planned": False})
        a["usd"] += t["shares"] * t["price"]
        a["shares"] += t["shares"]
        a["planned"] = a["planned"] or t["planned"]
    lines = [
        f"{'BUY' if code == 'P' else 'SELL'} {name}{f' ({title})' if title else ''}: "
        f"{a['shares']:,.0f} sh ≈ ${a['usd']:,.0f}{' [10b5-1 plan]' if a['planned'] else ''}"
        for (name, title, code), a in sorted(agg.items(), key=lambda kv: -kv[1]["usd"])
    ][:6]

    if not txs:
        summary = f"No open-market insider buys or sells in the last {days_back} days."
    else:
        summary = (f"Last {days_back}d: {len(buys)} open-market buys (${buys_usd:,.0f}), "
                   f"{len(sells)} sells (${sells_usd:,.0f}).")
    return {"buys_usd": buys_usd, "sells_usd": sells_usd, "n_buys": len(buys),
            "n_sells": len(sells), "lines": lines, "summary": summary}


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
