"""
OpenRouter LLM client using Claude Sonnet 4.6.

API key resolution order:
  1. Streamlit secrets  → st.secrets["OPENROUTER_API_KEY"]
  2. .env file          → loaded by python-dotenv
  3. Environment var    → os.environ["OPENROUTER_API_KEY"]

Model: anthropic/claude-sonnet-4.6 via https://openrouter.ai/api/v1
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Load .env if present (silently ignored if not)
load_dotenv(Path(__file__).parent.parent / ".env")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.6"


def _get_api_key() -> str:
    """Try Streamlit secrets first, then env."""
    try:
        import streamlit as st
        key = st.secrets.get("OPENROUTER_API_KEY", "")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("OPENROUTER_API_KEY", "")


def get_client() -> OpenAI:
    key = _get_api_key()
    if not key:
        raise ValueError(
            "OPENROUTER_API_KEY not set.\n"
            "Add it to .env or .streamlit/secrets.toml.\n"
            "Get a key at https://openrouter.ai/settings/keys"
        )
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=key,
        default_headers={
            "HTTP-Referer": "http://localhost:8501",
            "X-Title": "Personal Portfolio Tracker",
        },
    )


def is_configured() -> bool:
    """True if an API key is available (doesn't validate it)."""
    return bool(_get_api_key())


def call_llm(
    prompt: str,
    system: str = "You are a professional financial analyst. Be concise and factual.",
    model: str = DEFAULT_MODEL,
    max_tokens: int = 800,
    temperature: float = 0.3,
) -> str:
    """Single synchronous LLM call. Returns text or an error string."""
    try:
        client = get_client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip()
    except ValueError as e:
        return f"⚠️ Configuration error: {e}"
    except Exception as e:
        return f"⚠️ LLM error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Prompt library — each function is a focused analytical task
# ─────────────────────────────────────────────────────────────────────────────

def analyze_fundamentals(
    ticker: str,
    info: dict,
    earnings_summary: str,
    sec_filings: list,
    news_headlines: list,
) -> str:
    """Full fundamental analysis memo for a single stock."""
    company   = info.get("longName", ticker)
    sector    = info.get("sector", "N/A")
    industry  = info.get("industry", "N/A")
    pe        = info.get("trailingPE", "N/A")
    fpe       = info.get("forwardPE", "N/A")
    mcap      = info.get("marketCap", 0)
    mcap_str  = f"${mcap/1e9:.1f}B" if mcap else "N/A"
    div       = info.get("dividendYield", None)
    div_str   = f"{div*100:.2f}%" if div else "None"
    beta      = info.get("beta", "N/A")
    biz_sum   = (info.get("longBusinessSummary") or "")[:400]

    sec_block = ""
    if sec_filings:
        sec_block = "\nRecent SEC Filings:\n" + "\n".join(
            f"  [{f['date']}] {f['form']} — {f['description']}"
            for f in sec_filings[:6]
        )

    news_block = ""
    if news_headlines:
        news_block = "\nRecent Headlines:\n" + "\n".join(
            f"  - {h}" for h in news_headlines[:8]
        )

    prompt = f"""Analyze {company} ({ticker}) as a long-term equity investment.

--- COMPANY DATA ---
Sector: {sector} | Industry: {industry}
Market Cap: {mcap_str} | P/E TTM: {pe} | Forward P/E: {fpe}
Dividend Yield: {div_str} | Beta: {beta}
Business: {biz_sum}

--- EARNINGS ---
{earnings_summary}
{sec_block}
{news_block}

Write a structured investment memo (≈250 words) with exactly these sections:
## Business Overview
(2 sentences on what the company does and its competitive position)

## Key Strengths
(3 bullet points, specific and evidence-based)

## Key Risks
(3 bullet points, specific and evidence-based)

## Recent Developments
(What the SEC filings and news reveal — flag anything material)

## Outlook
(1 paragraph on near-term and long-term prospects)

Be factual. Do not invent numbers. If data is missing, say so."""

    return call_llm(prompt, max_tokens=700)


def analyze_geopolitical(ticker: str, info: dict, news_headlines: list) -> str:
    """Geopolitical and macro risk assessment for a stock."""
    company  = info.get("longName", ticker)
    country  = info.get("country", "USA")
    sector   = info.get("sector", "")
    industry = info.get("industry", "")
    biz_sum  = (info.get("longBusinessSummary") or "")[:400]
    news_block = "\n".join(f"- {h}" for h in news_headlines[:10]) if news_headlines else "None available."

    prompt = f"""Assess geopolitical and macroeconomic risks for {company} ({ticker}).

HQ Country: {country}
Sector: {sector} | Industry: {industry}
Business: {biz_sum}

Recent News:
{news_block}

Write a risk assessment (≈180 words) with these sections:
## Geographic & Supply Chain Exposure
(Key markets, manufacturing, where revenue comes from)

## Macro Risks
(Interest rates, inflation, currency, regulatory environment)

## Geopolitical Risks
(Trade policy, tariffs, sanctions, political stability in key markets)

## Sector-Specific Risks
(e.g. for Tech: AI regulation, export controls; for Energy: policy risk; for Consumer: discretionary spend)

## Risk Rating
**Overall: Low / Medium / High** — one sentence rationale.

Be specific to this company. Avoid generic platitudes."""

    return call_llm(prompt, max_tokens=500)


def summarize_sec_filing(form_type: str, filing_text: str, ticker: str) -> str:
    """Summarize a raw SEC filing into plain English (2-3 sentences)."""
    if not filing_text or len(filing_text) < 100:
        return "Filing text unavailable or too short to summarize."

    prompt = f"""This is an excerpt from a {form_type} filing by {ticker} submitted to the SEC.

--- FILING EXCERPT ---
{filing_text[:2500]}
--- END ---

Summarize this filing in 2-3 sentences for a personal investor:
- What happened / what is being disclosed?
- Is this bullish, bearish, or neutral for the stock?
- Is there any urgency or action required?

Be direct and plain. No jargon."""

    return call_llm(prompt, max_tokens=200, temperature=0.2)


def generate_portfolio_summary(
    period_label: str,
    holdings_data: list,
    portfolio_metrics: dict,
) -> str:
    """Portfolio-level investment memo for a given period."""
    holdings_block = ""
    for h in holdings_data:
        holdings_block += (
            f"\n{h['ticker']} ({h.get('company', h['ticker'])}):\n"
            f"  Period return: {h.get('period_return', 'N/A')}\n"
            f"  Top headline: {h.get('top_headline', 'None')}\n"
            f"  Latest filing: {h.get('latest_filing', 'None')}\n"
        )

    prompt = f"""Write a {period_label.lower()} portfolio review for a personal investor.

PORTFOLIO METRICS THIS PERIOD:
- Return: {portfolio_metrics.get('period_return', 'N/A')}
- Annualized Volatility: {portfolio_metrics.get('volatility', 'N/A')}
- Sharpe Ratio: {portfolio_metrics.get('sharpe', 'N/A')}
- Max Drawdown: {portfolio_metrics.get('max_drawdown', 'N/A')}
- Beta vs S&P 500: {portfolio_metrics.get('beta', 'N/A')}

INDIVIDUAL POSITIONS:
{holdings_block}

Write a concise investment memo (≈300 words) with these sections:
## Portfolio Performance
(How the portfolio did vs the market, what drove it)

## Winners & Losers
(Specific positions — what worked and what didn't)

## Key Events This Period
(Material news, filings, earnings — be specific)

## Risk Flags
(Anything that needs watching — concentration, volatility, macro)

## Watch List for Next Period
(2-3 concrete things to monitor or research)

Tone: smart but personal — like a note from a trusted analyst to yourself."""

    return call_llm(prompt, max_tokens=750)
