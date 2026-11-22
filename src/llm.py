"""
OpenRouter LLM client (default: Claude Opus 5.5).

API key resolution order:
  1. Streamlit secrets  → st.secrets["OPENROUTER_API_KEY"]
  2. .env file          → loaded by python-dotenv
  3. Environment var    → os.environ["OPENROUTER_API_KEY"]

Model: $OPENROUTER_MODEL, else anthropic/claude-opus-5.5, via https://openrouter.ai/api/v1
"""
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Load .env if present (silently ignored if not)
load_dotenv(Path(__file__).parent.parent / ".env")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = os.environ.get("OPENROUTER_MODEL") or "anthropic/claude-opus-5.5"


def _model_label(model_id: str) -> str:
    """'anthropic/claude-opus-5.5' -> 'Claude Opus 5.5'."""
    name = model_id.split("/")[-1].replace("-", " ")
    return " ".join(w if w[0].isdigit() else w.capitalize() for w in name.split())


MODEL_LABEL = _model_label(DEFAULT_MODEL)


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

ANALYST_SYSTEM = (
    "You are a sharp buy-side equity analyst writing for one individual investor "
    "about their own portfolio. Ground every claim in the data provided and quote "
    "the numbers you rely on. Never invent figures, dates or events; if something "
    "you need is missing, say so. Mark any statement that is your judgment rather "
    "than something the data shows with *(inference)*. Prefer specific, falsifiable "
    "statements over generic ones. This is personal research, not investment advice."
)


def _today() -> str:
    return datetime.today().strftime("%A, %B %d, %Y")


def _block(title: str, body) -> str:
    """Prompt section, omitted when there is nothing to show."""
    if body is None:
        return ""
    if isinstance(body, (list, tuple)):
        body = "\n".join(f"- {b}" for b in body if b)
    body = str(body).strip()
    return f"\n--- {title} ---\n{body}\n" if body else ""


_VIEW_SECTIONS = """## Bull Case
(2–3 bullets: what has to go right, with the evidence for it)

## Bear Case
(2–3 bullets: what could go wrong, with the evidence for it)

## What Would Change the View
(2–3 concrete, observable triggers — e.g. "gross margin below X%", "insider buying", "loses share to Y")

## Verdict
**Rating:** Strong Buy / Buy / Moderate Buy / Hold / Moderate Sell / Sell / Strong Sell
**Confidence:** High / Medium / Low — one sentence on why (data quality, conflicting signals, etc.)
**If held:** one sentence on sizing given the current position weight, if position data was provided."""


def analyze_fundamentals(
    ticker: str,
    info: dict,
    earnings_summary: str,
    sec_filings: list,
    news_headlines: list,
    quality: dict | None = None,
    relative_perf: str = "",
    insider: dict | None = None,
    filing_digest: str = "",
    position: str = "",
    macro: str = "",
) -> str:
    """Full fundamental analysis memo for a single stock."""
    company  = info.get("longName", ticker)
    biz_sum  = (info.get("longBusinessSummary") or "")[:1200]

    quality_str = "\n".join(f"{k}: {v}" for k, v in (quality or {}).items() if v not in ("N/A", None))
    filings_str = [f"[{f['date']}] {f['form']} — {f['description']}" for f in (sec_filings or [])[:8]]
    insider_str = ""
    if insider:
        insider_str = insider["summary"] + ("\n" + "\n".join(insider["lines"]) if insider["lines"] else "")

    prompt = f"""Today is {_today()}.
Analyze {company} ({ticker}) as a long-term equity investment.

--- COMPANY ---
Sector: {info.get('sector', 'N/A')} | Industry: {info.get('industry', 'N/A')} | HQ: {info.get('country', 'N/A')}
Business: {biz_sum}
{_block("VALUATION, QUALITY & ANALYST VIEW", quality_str)}{_block("PRICE PERFORMANCE VS PEERS", relative_perf)}{_block("EARNINGS: ACTUAL VS ESTIMATE (last 4 quarters)", earnings_summary)}{_block("INSIDER TRANSACTIONS (Form 4, open market only)", insider_str)}{_block("RECENT SEC FILINGS", filings_str)}{_block("LATEST 10-K/10-Q EXCERPTS (MD&A / Risk Factors)", filing_digest)}{_block("RECENT HEADLINES", (news_headlines or [])[:10])}{_block("MACRO BACKDROP", macro)}{_block("INVESTOR'S POSITION", position)}
Write a structured investment memo (≈450 words) with exactly these sections:

## Business Overview
(2 sentences: what the company does and its competitive position)

## Financial Quality
(Growth, margins, cash generation and balance sheet — cite the numbers above. Is the business getting better or worse?)

## Valuation
(Is the price justified by growth? Compare multiples to growth, the analyst target range and the 52-week range. Say whether the stock is cheap, fair or expensive and why.)

## Earnings & Momentum
(Beat/miss pattern, performance vs its sector ETF and SPY, and what that says about expectations)

## Insider & Filing Signals
(What insider activity and the filings reveal. Treat 10b5-1 plan sales as low-signal and open-market buys as high-signal. Flag anything material from MD&A or Risk Factors.)

{_VIEW_SECTIONS}"""

    return call_llm(prompt, system=ANALYST_SYSTEM, max_tokens=1800)


def analyze_etf(
    ticker: str,
    info: dict,
    profile: dict,
    top_holdings: list,
    relative_perf: str = "",
    overlap: str = "",
    position: str = "",
    news_headlines: list | None = None,
    macro: str = "",
) -> str:
    """Memo for an ETF / fund — cost, concentration, overlap with the rest of the portfolio."""
    name = info.get("longName", ticker)
    profile_str  = "\n".join(f"{k}: {v}" for k, v in profile.items() if v not in ("N/A", None))
    holdings_str = [f"{sym} ({nm}): {w:.2f}%" for sym, nm, w in top_holdings[:10]]
    top10 = sum(w for _, _, w in top_holdings[:10])

    prompt = f"""Today is {_today()}.
Analyze the fund {name} ({ticker}) as a holding in a personal portfolio.

--- FUND PROFILE ---
{profile_str}
Summary: {(info.get('longBusinessSummary') or '')[:800]}
{_block(f"TOP HOLDINGS (top 10 = {top10:.1f}% of fund)", holdings_str)}{_block("PERFORMANCE VS BENCHMARKS", relative_perf)}{_block("OVERLAP WITH THE INVESTOR'S OTHER HOLDINGS", overlap)}{_block("INVESTOR'S POSITION", position)}{_block("RECENT HEADLINES", (news_headlines or [])[:6])}{_block("MACRO BACKDROP", macro)}
Write a memo (≈350 words) with exactly these sections:

## What You Own
(Strategy, index/exposure, and how concentrated it is in its top names)

## Cost & Efficiency
(Expense ratio in context — cheap or expensive for its category — and yield)

## Overlap & Redundancy
(How much this fund duplicates stocks the investor already holds directly or through other funds. Is it adding diversification or doubling down?)

## Performance & Risk
(Recent performance vs benchmarks, beta, and what macro conditions help or hurt it)

{_VIEW_SECTIONS}"""

    return call_llm(prompt, system=ANALYST_SYSTEM, max_tokens=1500)


def analyze_geopolitical(
    ticker: str,
    info: dict,
    news_headlines: list,
    risk_factors: str = "",
    macro: str = "",
) -> str:
    """Geopolitical and macro risk assessment for a stock."""
    company = info.get("longName", ticker)

    prompt = f"""Today is {_today()}.
Assess geopolitical and macroeconomic risks for {company} ({ticker}).

HQ Country: {info.get('country', 'N/A')}
Sector: {info.get('sector', 'N/A')} | Industry: {info.get('industry', 'N/A')}
Business: {(info.get('longBusinessSummary') or '')[:1000]}
{_block("CURRENT MACRO INDICATORS", macro)}{_block("COMPANY'S OWN RISK FACTORS (latest 10-K, Item 1A excerpt)", risk_factors)}{_block("RECENT NEWS", (news_headlines or [])[:12])}
Write a risk assessment (≈350 words) with these sections:

## Geographic & Supply Chain Exposure
(Key markets, manufacturing, where revenue comes from — use the 10-K excerpt where it helps)

## Macro Sensitivity
(How the current rate, dollar, oil and volatility readings above specifically affect this company)

## Geopolitical Risks
(Trade policy, tariffs, export controls, sanctions, political stability in key markets)

## Sector-Specific & Regulatory Risks

## What the Company Itself Flags
(The 2–3 most material risks from its own Risk Factors, in plain English)

## Risk Rating
**Overall: Low / Medium / High** — **Confidence: High / Medium / Low** — one sentence rationale.

Be specific to this company. Avoid generic platitudes."""

    return call_llm(prompt, system=ANALYST_SYSTEM, max_tokens=1200)


def summarize_sec_filing(form_type: str, filing_text: str, ticker: str, description: str = "") -> str:
    """Summarize a SEC filing (relevant sections, not just the cover page) in plain English."""
    if not filing_text or len(filing_text) < 100:
        return "Filing text unavailable or too short to summarize."

    prompt = f"""Today is {_today()}.
Below are the relevant parts of a {form_type} filing by {ticker}{f" ({description})" if description else ""}.
For 10-K/10-Q this is the MD&A and Risk Factors; for 8-Ks it is the item text.

--- FILING ---
{filing_text[:14000]}
--- END ---

Summarize for a personal investor:
**What happened:** 2–3 sentences, with the key numbers.
**Why it matters:** 1–2 sentences.
**Signal:** Bullish / Bearish / Neutral — one-line reason.
**Anything new or unusual:** changes in guidance, new risks, management changes, one-off items — or "Nothing notable".
**Action needed:** Yes/No — one line.

Be direct and plain. No jargon."""

    return call_llm(prompt, system=ANALYST_SYSTEM, max_tokens=600, temperature=0.2)


def _tech_str(tech: dict) -> str:
    parts = []
    rsi_val = tech.get("rsi")
    if rsi_val is not None:
        tag = " (overbought)" if rsi_val > 70 else " (oversold)" if rsi_val < 30 else " (neutral)"
        parts.append(f"RSI {rsi_val}{tag}")
    if "macd_bullish" in tech:
        cross = " [fresh crossover]" if tech.get("macd_crossing_up") else ""
        parts.append(f"MACD {'bullish' if tech['macd_bullish'] else 'bearish'}{cross}")
    bb = tech.get("bb_pct")
    if bb is not None:
        pos = "near upper band" if bb >= 0.8 else "near lower band" if bb <= 0.2 else f"{bb:.0%} of band"
        parts.append(f"BB {pos}")
    trend = []
    if tech.get("above_sma20") is not None:
        trend.append("above SMA20" if tech["above_sma20"] else "below SMA20")
    if tech.get("above_sma50") is not None:
        trend.append("above SMA50" if tech["above_sma50"] else "below SMA50")
    if trend:
        parts.append("Trend: " + ", ".join(trend))
    return " | ".join(parts) if parts else "N/A"


def generate_portfolio_summary(
    period_label: str,
    holdings_data: list,
    portfolio_metrics: dict,
    overview: str = "",
    lookthrough: str = "",
    macro: str = "",
    prior_summary: str = "",
) -> str:
    """Portfolio-level investment memo + trading recommendations for a given period."""
    holdings_block = ""
    for h in holdings_data:
        news_str    = "\n".join(f"    - {n}" for n in h.get("news_headlines", [])[:6]) or "    None"
        filings_str = "\n".join(f"    - {f}" for f in h.get("filings_list", [])) or "    None"
        ed          = h.get("earnings_date", "Unknown")
        eps         = h.get("eps_estimate")
        earn_str    = f"{ed}" + (f" (EPS est. ${eps})" if eps is not None else "")
        kind        = "ETF" if h.get("is_etf") else h.get("sector", "N/A")
        holdings_block += (
            f"\n{h['ticker']} ({h.get('company', h['ticker'])}) — {kind} | {h.get('country', 'N/A')}\n"
            f"  Position: {h.get('position', 'N/A')}\n"
            f"  Period performance: {h.get('relative_perf') or h.get('period_return', 'N/A')}\n"
            f"  Fundamentals: {h.get('fundamentals', 'N/A')}\n"
            f"  Insiders: {h.get('insider', 'N/A')}\n"
            f"  Next earnings: {earn_str}\n"
            f"  Technical: {_tech_str(h.get('tech', {}))}\n"
            f"  Recent News:\n{news_str}\n"
            f"  Recent SEC Filings:\n{filings_str}\n"
        )

    prior_block = ""
    changed_section = ""
    if prior_summary:
        prior_block = _block("PREVIOUS REVIEW (for comparison — do not repeat it)", prior_summary[-8000:])
        changed_section = """
## What Changed Since Last Review
(Compare with the previous review: ratings you are changing and why, risks that played out or faded, calls that were right or wrong. Be honest about misses.)
"""

    prompt = f"""Today is {_today()}.
Write a {period_label.lower()} portfolio review and trading recommendations for a personal investor.

PORTFOLIO METRICS THIS PERIOD:
- Return: {portfolio_metrics.get('period_return', 'N/A')} (SPY: {portfolio_metrics.get('spy_return', 'N/A')})
- Annualized Volatility: {portfolio_metrics.get('volatility', 'N/A')}
- Sharpe Ratio: {portfolio_metrics.get('sharpe', 'N/A')}
- Max Drawdown: {portfolio_metrics.get('max_drawdown', 'N/A')}
- Beta vs S&P 500: {portfolio_metrics.get('beta', 'N/A')}
{_block("PORTFOLIO COMPOSITION", overview)}{_block("LOOK-THROUGH EXPOSURE (direct + via ETF top holdings; a lower bound)", lookthrough)}{_block("MACRO INDICATORS", macro)}{prior_block}
INDIVIDUAL POSITIONS:
{holdings_block}

Write a structured investment memo (≈900 words) with these exact sections:

## Portfolio Performance
(Return vs SPY, what drove it — weight the explanation by position size, not ticker count)
{changed_section}
## Winners & Losers
(Specific positions, in dollar-impact terms where possible — what worked and what didn't, and whether each move was stock-specific or sector/market-wide)

## Concentration & Exposure
(Largest positions and sectors, hidden concentration revealed by the look-through, overlapping ETFs, and whether the mix matches a sensible risk level)

## Key Events This Period
(Material news, SEC filings and insider activity — be specific and reference tickers)

## Macro & Geopolitical Watch
(Tie the macro indicators above to the specific holdings they affect most)

## Risk Flags
(Overbought/oversold signals, earnings risk, rich valuations, heavy insider selling, oversized losers)

## Bull vs Bear: Top 5 Positions
For each of the five largest positions by weight: one-line bull case, one-line bear case, and one observable trigger that would change the view.

## Trading Recommendations
Synthesize position size, fundamentals, technical signals, news, filings and macro context for each ticker.
Use EXACTLY this markdown table:

| Ticker | Weight | Daily | Weekly | Monthly | Confidence | Key Reasoning |
|--------|--------|-------|--------|---------|------------|---------------|
| TICK | 4.2% | Hold | Moderate Buy | Buy | Medium | one-line rationale |

Valid ratings: Strong Buy / Buy / Moderate Buy / Hold / Moderate Sell / Sell / Strong Sell
Confidence: High / Medium / Low (Low when signals conflict or data is thin).
Every ticker in the portfolio must appear in the table, ordered by weight (largest first).

## Rebalancing Ideas
(1–3 concrete ideas tied to concentration, overlap or position sizing — or "None needed" with a reason)

## Upcoming Catalysts
List every ticker that has a known earnings date coming up, any expected product launches,
regulatory decisions, Fed meetings, or macro events relevant to this portfolio.
Use today's date to place each event. Format as a bullet list grouped by timeframe:

**This week:**
- TICKER — event description

**Next 2–4 weeks:**
- TICKER — event description

**Next 1–3 months:**
- TICKER — event description

If no known events for a timeframe, write "None confirmed."
Flag any earnings with analyst EPS estimates as: "Earnings — est. $X.XX EPS"

Tone: smart, direct, personal — like a note from a trusted analyst to yourself."""

    return call_llm(prompt, system=ANALYST_SYSTEM, max_tokens=10000)
