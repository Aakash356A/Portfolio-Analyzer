"""Portfolio Tracker & Analyzer — main Streamlit app.
Run with:  streamlit run app.py
"""
import os
import re as _re
from datetime import datetime
from pathlib import Path
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src.analytics import (
    annualized_volatility, beta_vs_benchmark,
    calculate_portfolio_metrics, calculate_returns,
    max_drawdown, portfolio_history, sharpe_ratio,
)
from src.data_fetcher import (
    get_company_news_rss, get_current_price,
    get_earnings_info, get_historical_data, get_stock_info,
)
from src.indicators import (
    bollinger_bands, ema, macd, pivot_points,
    rsi, sma, support_resistance_levels,
)
from src.llm import (
    analyze_fundamentals, analyze_geopolitical,
    is_configured, summarize_sec_filing,
)
from src.portfolio import add_holding, load_portfolio, remove_holding, sell_holding, save_portfolio
from src.sec_edgar import get_filing_text, get_recent_filings
from src.summary_pipeline import list_saved_summaries, run_summary_pipeline
from src.news_monitor import fetch_all, score_color, score_bg

# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Portfolio Tracker", page_icon="📊", layout="wide")
st.title("📊 Portfolio Tracker & Analyzer")

llm_ready = is_configured()
if llm_ready:
    st.sidebar.success("🤖 Claude Sonnet 4.6 ready")
else:
    st.sidebar.warning("🔑 OpenRouter key not set — AI features disabled")
    with st.sidebar.expander("How to add key"):
        st.code("# Copy .env.example → .env\nOPENROUTER_API_KEY=sk-or-v1-...")

page = st.sidebar.radio(
    "Navigate",
    ["Dashboard", "Manage Holdings", "Stock Analysis", "Performance", "📋 Summary", "🔔 Monitor"],
)

portfolio = load_portfolio()
holdings  = portfolio["holdings"]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def fmt(x):      return f"${x:,.2f}"
def pct(x):      return f"{x:+.2f}%"
def safe_money(x):
    if x is None: return "N/A"
    if x >= 1e9:  return f"${x/1e9:.2f}B"
    if x >= 1e6:  return f"${x/1e6:.2f}M"
    return f"${x:,.0f}"

def llm_btn(label, key):
    if llm_ready:
        return st.button(f"🤖 {label}", key=key)
    st.button(f"🤖 {label}", key=key, disabled=True,
              help="Add OPENROUTER_API_KEY to .env to enable AI features.")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────
if page == "Dashboard":
    st.header("Dashboard")
    if not holdings:
        st.info("No holdings yet. Go to **Manage Holdings** to add some.")
    else:
        with st.spinner("Fetching latest prices…"):
            df = calculate_portfolio_metrics(holdings)
        if df.empty:
            st.warning("Couldn't fetch data for any holdings.")
        else:
            tv = df["Market Value"].sum(); tc = df["Cost Basis"].sum()
            tp = df["P&L ($)"].sum();     tpct = (tp/tc*100) if tc else 0.
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Total Value", fmt(tv))
            c2.metric("Cost Basis",  fmt(tc))
            c3.metric("Total P&L",   fmt(tp), pct(tpct))
            c4.metric("Positions",   len(df))

            ca, cb = st.columns(2)
            with ca:
                st.subheader("Allocation")
                fig = px.pie(df, values="Market Value", names="Ticker", hole=0.45)
                fig.update_traces(textposition="inside", textinfo="percent+label")
                fig.update_layout(height=380, margin=dict(t=20,b=10,l=0,r=0))
                st.plotly_chart(fig, use_container_width=True)
            with cb:
                st.subheader("P&L by Position")
                ds = df.sort_values("P&L ($)")
                fig = go.Figure(go.Bar(
                    x=ds["P&L ($)"], y=ds["Ticker"], orientation="h",
                    marker_color=["#e74c3c" if v<0 else "#2ecc71" for v in ds["P&L ($)"]],
                    text=[fmt(v) for v in ds["P&L ($)"]], textposition="auto"))
                fig.update_layout(height=380, showlegend=False, margin=dict(t=20,b=10,l=0,r=0))
                st.plotly_chart(fig, use_container_width=True)

            st.subheader("Holdings")
            disp = df.copy()
            for c in ["Purchase Price","Current Price","Cost Basis","Market Value","P&L ($)"]:
                disp[c] = disp[c].apply(fmt)
            disp["P&L (%)"] = disp["P&L (%)"].apply(lambda x: f"{x:+.2f}%")
            st.dataframe(disp, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# Manage Holdings
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Manage Holdings":
    st.header("Manage Holdings")

    tab_buy, tab_sell, tab_import, tab_plaid = st.tabs(["🟢 Buy", "🔴 Sell", "📥 Import CSV", "🏦 Connect Brokerage"])

    with tab_buy:
        st.subheader("Buy Shares")
        existing_tickers = [h["ticker"] for h in holdings]
        with st.form("add_holding", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                ticker = st.text_input("Ticker", placeholder="AAPL")
                shares = st.number_input("Shares", min_value=0., step=0.01, format="%.4f")
            with c2:
                pp    = st.number_input("Purchase Price ($)", min_value=0., step=0.01, format="%.2f")
                pdate = st.date_input("Purchase Date", value=datetime.today())
            if st.form_submit_button("Buy"):
                if not ticker or shares <= 0 or pp <= 0:
                    st.error("Fill in all fields.")
                else:
                    price = get_current_price(ticker)
                    if price is None:
                        st.error(f"Couldn't verify '{ticker.upper()}'. Check the symbol.")
                    else:
                        is_existing = ticker.upper().strip() in existing_tickers
                        add_holding(ticker, shares, pp, pdate.isoformat())
                        if is_existing:
                            updated = next(h for h in load_portfolio()["holdings"]
                                           if h["ticker"] == ticker.upper().strip())
                            st.success(
                                f"Added {shares} shares of {ticker.upper()}. "
                                f"New position: {updated['shares']} shares @ avg {fmt(updated['purchase_price'])}"
                            )
                        else:
                            st.success(f"Opened new position: {shares} shares of {ticker.upper()} (current: {fmt(price)})")
                        st.rerun()

    with tab_sell:
        st.subheader("Sell Shares")
        if not holdings:
            st.info("No holdings to sell.")
        else:
            with st.form("sell_holding", clear_on_submit=True):
                sell_ticker = st.selectbox("Ticker", [h["ticker"] for h in holdings])
                held = next((h for h in holdings if h["ticker"] == sell_ticker), None)
                if held:
                    st.caption(f"Currently holding **{held['shares']} shares** @ avg cost {fmt(held['purchase_price'])}")
                sell_shares = st.number_input("Shares to sell", min_value=0., step=0.01, format="%.4f")
                if st.form_submit_button("Sell"):
                    if sell_shares <= 0:
                        st.error("Enter number of shares to sell.")
                    else:
                        try:
                            remaining = sell_holding(sell_ticker, sell_shares)
                            if remaining == 0:
                                st.success(f"Closed position in {sell_ticker} entirely.")
                            else:
                                st.success(f"Sold {sell_shares} shares of {sell_ticker}. Remaining: {remaining} shares.")
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))

    with tab_import:
        import io
        st.subheader("Import from Brokerage CSV")
        st.caption("Supports position snapshots (Fidelity, Schwab) and transaction histories (Robinhood).")

        # ── Shared helpers ────────────────────────────────────────────────
        def _clean_num(val):
            try:
                s = str(val).strip().replace("$", "").replace(",", "").replace("%", "")
                if s.startswith("(") and s.endswith(")"):
                    s = "-" + s[1:-1]
                return float(s)
            except Exception:
                return None

        def _exact_col(df, names):
            """Match a column whose lowercased name exactly equals one of `names`."""
            lc = {c.lower().strip(): c for c in df.columns}
            for n in names:
                if n in lc:
                    return lc[n]
            return None

        def _fuzzy_col(df, candidates):
            """Match a column whose lowercased name contains a candidate string."""
            lc = {c.lower().strip(): c for c in df.columns}
            for cand in candidates:
                for lower, orig in lc.items():
                    if cand in lower or lower in cand:
                        return orig
            return None

        def _do_import(rows, clear):
            if clear:
                save_portfolio({"holdings": []})
            imported, errors = 0, []
            for r in rows:
                try:
                    add_holding(r["Ticker"], r["Shares"], r["Avg Cost ($)"], r["Purchase Date"])
                    imported += 1
                except Exception as exc:
                    errors.append(f"{r['Ticker']}: {exc}")
            if imported:
                st.success(f"Imported {imported} position(s) successfully.")
            for err in errors:
                st.error(err)
            st.rerun()

        BROKER_MAPPINGS = {
            "robinhood": {"date": "Activity Date", "ticker": "Instrument", "action": "Trans Code", "quantity": "Quantity", "price": "Price"},
            "fidelity": {"date": "Run Date", "ticker": "Symbol", "action": "Action", "quantity": "Quantity", "price": "Price"},
            "schwab": {"date": "Date", "ticker": "Symbol", "action": "Action", "quantity": "Quantity", "price": "Price"},
            "vanguard": {"date": "Trade Date", "ticker": "Symbol", "action": "Transaction Type", "quantity": "Shares", "price": "Share Price"}
        }

        def normalize_broker_data(df: pd.DataFrame, broker_name: str) -> pd.DataFrame:
            """Standardizes brokerage CSVs into a single format."""
            mapping = BROKER_MAPPINGS.get(broker_name.lower())
            if not mapping:
                return df
                
            rename_dict = {}
            for std_key, expected_col in mapping.items():
                match = _exact_col(df, [expected_col]) or _fuzzy_col(df, [expected_col])
                if match:
                    rename_dict[match] = std_key
                    
            std_df = df.rename(columns=rename_dict)
            cols_to_keep = [c for c in ['date', 'ticker', 'action', 'quantity', 'price'] if c in std_df.columns]
            return std_df[cols_to_keep]

        uploaded = st.file_uploader(
            "Upload CSV from your broker (positions export or transaction history)",
            type=["csv"],
            key="csv_import",
        )
        
        broker_choice = st.selectbox("Broker Format", ["Auto-detect", "Robinhood", "Fidelity", "Schwab", "Vanguard", "Generic Positions Snapshot"])

        if uploaded is not None:
            try:
                uploaded.seek(0)
                raw = uploaded.read()
                df_raw = None
                _DETECT_KEYS = ["symbol", "ticker", "instrument", "qty",
                                 "quantity", "shares", "trans code", "activity date"]
                for skip in [0, 1, 2, 3]:
                    try:
                        df_try = pd.read_csv(
                            io.BytesIO(raw), skiprows=skip,
                            encoding="utf-8-sig", engine="python",
                            on_bad_lines="skip",
                        )
                        cols_lower = " ".join(c.lower() for c in df_try.columns)
                        if any(k in cols_lower for k in _DETECT_KEYS):
                            df_raw = df_try
                            break
                    except Exception as e:
                        import sys
                        print(f"DEBUG Parse exception on skip={skip}: {e}", file=sys.stderr)
                        continue

                if df_raw is None:
                    st.error("Could not parse this file. Make sure it is a CSV export from your broker.")
                else:
                    col_set = {c.lower().strip() for c in df_raw.columns}
                    
                    broker_detected = broker_choice
                    if broker_choice == "Auto-detect":
                        if "trans code" in col_set or "activity date" in col_set:
                            broker_detected = "robinhood"
                        elif "run date" in col_set:
                            broker_detected = "fidelity"
                        elif "transaction type" in col_set and "trade date" in col_set:
                            broker_detected = "vanguard"
                        elif "action" in col_set and "symbol" in col_set:
                            broker_detected = "schwab"
                        else:
                            broker_detected = "Generic Positions Snapshot"
                    
                    is_tx_history = broker_detected.lower() in BROKER_MAPPINGS
                    
                    if is_tx_history:
                        st.info(f"Detected **{broker_detected.title()}** transaction history format. Aggregating open positions.")
                        std_df = normalize_broker_data(df_raw, broker_detected)
                        
                        if not all(k in std_df.columns for k in ['date', 'ticker', 'action', 'quantity', 'price']):
                            st.error("Could not find all required columns (Date, Ticker, Action, Quantity, Price).")
                        else:
                            positions: dict = {}
                            for _, row in std_df.iterrows():
                                ticker = str(row['ticker']).strip().upper()
                                action = str(row['action']).strip().title()
                                if not ticker or ticker in ("NAN", "", "NONE"):
                                    continue
                                
                                # Schwab uses cash/credit/debit, vanguard has variations, so match loosely on Buy/Sell
                                if 'Buy' in action or 'Reinvest' in action or action == 'B':
                                    trans = "Buy"
                                elif 'Sell' in action or action == 'S':
                                    trans = "Sell"
                                else:
                                    continue
                                
                                qty = _clean_num(row['quantity'])
                                price = _clean_num(row['price'])
                                if qty is None or qty <= 0:
                                    continue
                                
                                if ticker not in positions:
                                    positions[ticker] = {
                                        "buy_shares": 0.0, "buy_cost": 0.0,
                                        "sell_shares": 0.0, "first_date": None,
                                    }
                                
                                date_val = None
                                try:
                                    date_val = pd.to_datetime(str(row['date'])).date().isoformat()
                                except:
                                    pass
                                
                                if trans == "Buy":
                                    p = price if price and price > 0 else 0.0
                                    positions[ticker]["buy_shares"] += qty
                                    positions[ticker]["buy_cost"]   += qty * p
                                    if date_val:
                                        if positions[ticker]["first_date"] is None or date_val < positions[ticker]["first_date"]:
                                            positions[ticker]["first_date"] = date_val
                                else:
                                    positions[ticker]["sell_shares"] += qty

                            rows, closed = [], []
                            for ticker, pos in positions.items():
                                net = round(pos["buy_shares"] - pos["sell_shares"], 6)
                                if net < 0.0001:
                                    closed.append(ticker)
                                    continue
                                avg = (round(pos["buy_cost"] / pos["buy_shares"], 4)
                                       if pos["buy_shares"] > 0 else 0.0)
                                if avg <= 0:
                                    closed.append(f"{ticker} (no price data)")
                                    continue
                                rows.append({
                                    "Ticker": ticker,
                                    "Shares": net,
                                    "Avg Cost ($)": avg,
                                    "Purchase Date": pos["first_date"] or datetime.today().date().isoformat(),
                                })

                            if rows:
                                st.markdown(f"**Preview — {len(rows)} open position(s) found:**")
                                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                                if closed:
                                    st.caption(f"Skipped {len(closed)} closed/zero position(s): {', '.join(closed)}")
                                overlapping = [r["Ticker"] for r in rows
                                               if r["Ticker"] in [h["ticker"] for h in holdings]]
                                
                                clear_opt = st.checkbox("Clear existing portfolio before importing", value=False)
                                
                                if overlapping and not clear_opt:
                                    st.warning(
                                        f"**{', '.join(overlapping)}** already exist in your portfolio. "
                                        "Shares will be added and cost basis averaged in."
                                    )
                                if st.button(f"✅ Import {len(rows)} position(s)",
                                             type="primary", key="do_import"):
                                    _do_import(rows, clear_opt)
                            else:
                                st.warning("No open positions found in the transaction history.")
                    
                    else:
                        _TICKER_COLS = ["symbol", "ticker", "stock", "security"]
                        _SHARES_COLS = ["quantity", "qty", "shares", "units", "shares held", "share qty"]
                        _PRICE_COLS  = ["average cost basis", "average cost", "avg cost", "cost basis",
                                        "average price", "price paid", "unit cost", "purchase price",
                                        "cost per share", "avg price", "avg cost/share", "price"]
                        _DATE_COLS   = ["date acquired", "purchase date", "open date", "trade date"]

                        col_ticker = _fuzzy_col(df_raw, _TICKER_COLS)
                        col_shares = _fuzzy_col(df_raw, _SHARES_COLS)
                        col_price  = _fuzzy_col(df_raw, _PRICE_COLS)
                        col_date   = _fuzzy_col(df_raw, _DATE_COLS)

                        st.markdown("**Detected columns:**")
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Ticker",        col_ticker or "❌ Not found")
                        m2.metric("Shares",        col_shares or "❌ Not found")
                        m3.metric("Avg Cost",      col_price  or "❌ Not found")
                        m4.metric("Purchase Date", col_date   or "(today as default)")

                        if not (col_ticker and col_shares and col_price):
                            st.warning("Couldn't auto-detect all columns. Select them manually:")
                            all_cols = ["(none)"] + list(df_raw.columns)
                            col_ticker = st.selectbox("Ticker column",           all_cols, key="imp_t")
                            col_shares = st.selectbox("Shares column",           all_cols, key="imp_s")
                            col_price  = st.selectbox("Avg cost/price column",   all_cols, key="imp_p")
                            col_date   = st.selectbox("Purchase date (optional)", all_cols, key="imp_d")
                            col_ticker = None if col_ticker == "(none)" else col_ticker
                            col_shares = None if col_shares == "(none)" else col_shares
                            col_price  = None if col_price  == "(none)" else col_price
                            col_date   = None if col_date   == "(none)" else col_date

                        if col_ticker and col_shares and col_price:
                            _SKIP_VALS = {"NAN", "ACCOUNT TOTAL", "PENDING ACTIVITY", "TOTAL", "", "NONE"}
                            rows, skipped = [], []
                            for _, row in df_raw.iterrows():
                                t = str(row.get(col_ticker, "")).strip().upper()
                                if t in _SKIP_VALS or t.startswith(("**", "--")):
                                    continue
                                s = _clean_num(row.get(col_shares))
                                p = _clean_num(row.get(col_price))
                                if not s or not p or s <= 0 or p <= 0:
                                    skipped.append(t)
                                    continue
                                d = datetime.today().date().isoformat()
                                if col_date:
                                    try:
                                        d = pd.to_datetime(str(row.get(col_date))).date().isoformat()
                                    except Exception:
                                        pass
                                rows.append({"Ticker": t, "Shares": s, "Avg Cost ($)": p, "Purchase Date": d})

                            if rows:
                                st.markdown(f"**Preview — {len(rows)} holding(s) to import:**")
                                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                                if skipped:
                                    st.caption(f"Skipped {len(skipped)} row(s) with missing/invalid data: {', '.join(skipped)}")
                                overlapping = [r["Ticker"] for r in rows
                                               if r["Ticker"] in [h["ticker"] for h in holdings]]
                                
                                clear_opt = st.checkbox("Clear existing portfolio before importing", value=False)
                                
                                if overlapping and not clear_opt:
                                    st.warning(
                                        f"**{', '.join(overlapping)}** already exist in your portfolio. "
                                        "Shares will be added and cost basis averaged in."
                                    )
                                if st.button(f"✅ Import {len(rows)} holding(s)",
                                             type="primary", key="do_import"):
                                    _do_import(rows, clear_opt)
                            else:
                                st.warning("No valid rows found. Check that the file contains tickers, quantities, and cost/price data.")
            except Exception as e:
                st.error(f"Failed to read file: {e}")

    # ── SnapTrade ─────────────────────────────────────────────────────────────
    with tab_plaid:
        st.subheader("🏦 Connect Your Brokerage via SnapTrade")
        st.caption(
            "SnapTrade connects to Robinhood, Fidelity, Schwab, Vanguard, E*TRADE, "
            "Webull, Wealthsimple, and many more. "
            "Your credentials never touch this app — they go directly to SnapTrade."
        )

        try:
            from src import snaptrade_integration as snap
        except ImportError:
            snap = None
            st.error("snaptrade-python-sdk not installed. Run: `pip install snaptrade-python-sdk`")

        if snap is not None:
            if not snap.is_configured():
                st.warning("SnapTrade API keys not configured.")
                with st.expander("📋 Setup instructions (2 minutes, free — real brokerage data)"):
                    st.markdown("""
**1. Create a free SnapTrade account**
Go to [dashboard.snaptrade.com](https://dashboard.snaptrade.com) and sign up, then
verify your email. The free tier gives you **real brokerage data** for a personal
account at no cost.

**2. Generate your API key**
In the dashboard, create an API key. You'll get a **Client ID** and a **Consumer Key**.

**3. Add to your `.env` file**
```
SNAPTRADE_CLIENT_ID=your_client_id_here
SNAPTRADE_CONSUMER_KEY=your_consumer_key_here
```

**4. Install the SDK**
```bash
pip install snaptrade-python-sdk
```

**5. Restart the app** — this page will activate automatically.

> SnapTrade is purpose-built for investment data, so connecting your broker
> imports your **actual positions** (shares + cost basis) straight into your
> portfolio. No test/sandbox toggle needed.
""")
            else:
                try:
                    connections = snap.list_connections()
                except Exception as ex:
                    connections = []
                    st.error(f"Could not reach SnapTrade: {ex}")

                is_connected = len(connections) > 0

                if is_connected:
                    names = ", ".join(
                        c.get("brokerage", {}).get("name", "Broker")
                        for c in connections
                    ) or "your brokerage"
                    st.success(f"✅ Connected: {names}")

                    c1, c2 = st.columns([1, 1])
                    with c1:
                        if st.button("🔄 Sync Holdings", type="primary", key="snap_sync"):
                            with st.spinner("Fetching holdings from SnapTrade…"):
                                try:
                                    snap_holdings = snap.fetch_holdings()
                                    if not snap_holdings:
                                        st.warning("No positions found in your connected account(s).")
                                    else:
                                        if st.session_state.get("snap_clear", False):
                                            save_portfolio({"holdings": []})
                                        imported, errors = 0, []
                                        for h in snap_holdings:
                                            try:
                                                add_holding(
                                                    h["ticker"],
                                                    h["shares"],
                                                    h["purchase_price"],
                                                    h["purchase_date"],
                                                )
                                                imported += 1
                                            except Exception as ex:
                                                errors.append(f"{h['ticker']}: {ex}")
                                        if imported:
                                            st.success(f"✅ Synced {imported} holding(s) from SnapTrade.")
                                        for err in errors:
                                            st.error(err)
                                        st.rerun()
                                except Exception as ex:
                                    st.error(f"Sync failed: {ex}")

                    with c2:
                        st.session_state["snap_clear"] = st.checkbox(
                            "Replace existing portfolio on sync", value=False, key="snap_clear_cb"
                        )

                    st.divider()
                    cc1, cc2 = st.columns([1, 1])
                    with cc1:
                        if st.button("➕ Connect Another Broker", key="snap_add"):
                            try:
                                snap.open_connection_portal()
                                st.info("A new browser tab opened. Connect your broker, then click **Check Connection**.")
                            except Exception as ex:
                                st.error(f"Could not open portal: {ex}")
                    with cc2:
                        if st.button("🔌 Disconnect All", key="snap_disconnect"):
                            snap.disconnect()
                            st.success("Disconnected. Your portfolio.json is unchanged.")
                            st.rerun()

                else:
                    st.info("No brokerage connected yet.")
                    if st.button("🏦 Connect Brokerage", type="primary", key="snap_open"):
                        try:
                            with st.spinner("Opening SnapTrade connection portal…"):
                                snap.open_connection_portal()
                            st.info(
                                "A new browser tab has opened with the SnapTrade connection page. "
                                "Log into your brokerage there, then click **Check Connection** below."
                            )
                        except Exception as ex:
                            st.error(f"Could not open connection portal: {ex}")

                    if st.button("✅ Check Connection", key="snap_check"):
                        st.rerun()

    st.divider()
    st.subheader("Current Holdings")
    if not holdings:
        st.info("No holdings yet.")
    else:
        for i, h in enumerate(holdings):
            c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 1])
            c1.markdown(f"**{h['ticker']}**")
            c2.write(f"{h['shares']} shares")
            c3.write(f"@ avg {fmt(h['purchase_price'])}")
            c4.write(h.get("purchase_date", ""))
            if c5.button("Remove", key=f"del_{i}"):
                remove_holding(i); st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Stock Analysis
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Stock Analysis":
    st.header("Stock Analysis")

    tickers_held = [h["ticker"] for h in holdings]
    use_custom   = st.checkbox("Analyze a ticker not in my portfolio")
    ticker = None
    if use_custom:
        ticker = st.text_input("Ticker", value="SPY").upper().strip()
    elif tickers_held:
        ticker = st.selectbox("Stock", tickers_held)
    else:
        st.info("No holdings — tick the box above to analyze any ticker.")

    if ticker:
        with st.spinner(f"Loading {ticker}…"):
            info    = get_stock_info(ticker)
        company = info.get("longName", ticker)

        tab_tech, tab_fund, tab_geo, tab_news = st.tabs([
            "📈 Technical", "📊 Fundamentals & Earnings",
            "🌐 Geopolitical & Macro", "📰 News",
        ])

        # ══ Technical ════════════════════════════════════════════════════
        with tab_tech:
            candle  = st.radio("Candles", ["Daily","Weekly"], horizontal=True)
            iv      = "1d" if candle=="Daily" else "1wk"
            p_opts  = ["6mo","1y","2y","5y"] if iv=="1wk" else ["1mo","3mo","6mo","1y","2y","5y"]
            period  = st.select_slider("Period", options=p_opts,
                                        value="1y" if iv=="1wk" else "6mo")

            with st.spinner("Loading chart…"):
                data = get_historical_data(ticker, period, iv)

            if data.empty:
                st.error(f"No data for {ticker}.")
            else:
                cur  = data["Close"].iloc[-1]
                prev = data["Close"].iloc[-2] if len(data)>1 else cur
                dpct = (cur-prev)/prev*100 if prev else 0.
                rets = calculate_returns(data["Close"])
                pr   = (cur/data["Close"].iloc[0]-1)*100
                vol  = annualized_volatility(rets)*100
                sr   = sharpe_ratio(rets)
                mdd  = max_drawdown(data["Close"])*100

                c1,c2,c3,c4,c5 = st.columns(5)
                c1.metric("Price",            fmt(cur), pct(dpct))
                c2.metric("Period Return",     pct(pr))
                c3.metric("Volatility (Ann.)", f"{vol:.2f}%")
                c4.metric("Sharpe",            f"{sr:.2f}")
                c5.metric("Max Drawdown",      f"{mdd:.2f}%")

                ci, cs = st.columns([2,1])
                with ci:
                    overlays = st.multiselect("Overlays",
                        ["SMA 20","SMA 50","SMA 200","EMA 20","Bollinger Bands"],
                        default=["SMA 20","SMA 50"])
                with cs:
                    show_sr = st.checkbox("Support & Resistance", value=True)
                    show_pv = st.checkbox("Pivot Points", value=False)

                fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                    vertical_spacing=0.04, row_heights=[0.6,0.18,0.22],
                    subplot_titles=("Price","Volume","RSI (14)"))

                fig.add_trace(go.Candlestick(x=data.index,
                    open=data["Open"], high=data["High"],
                    low=data["Low"],   close=data["Close"], name="Price",
                    increasing_line_color="#2ecc71", decreasing_line_color="#e74c3c"),
                    row=1, col=1)

                ind_cfg = [
                    ("SMA 20",  lambda: sma(data["Close"],20),  "orange",    None),
                    ("SMA 50",  lambda: sma(data["Close"],50),  "dodgerblue",None),
                    ("SMA 200", lambda: sma(data["Close"],200), "purple",    None),
                    ("EMA 20",  lambda: ema(data["Close"],20),  "green",     "dash"),
                ]
                for name, fn, col, dash in ind_cfg:
                    if name in overlays:
                        ld = dict(color=col, width=1.2)
                        if dash: ld["dash"] = dash
                        fig.add_trace(go.Scatter(x=data.index, y=fn(),
                            name=name, line=ld), row=1, col=1)

                if "Bollinger Bands" in overlays:
                    upper, mid, lower = bollinger_bands(data["Close"])
                    fig.add_trace(go.Scatter(x=data.index, y=upper, name="BB Upper",
                        line=dict(color="gray",width=1)), row=1, col=1)
                    fig.add_trace(go.Scatter(x=data.index, y=lower, name="BB Lower",
                        line=dict(color="gray",width=1), fill="tonexty",
                        fillcolor="rgba(128,128,128,0.1)"), row=1, col=1)

                if show_sr and len(data)>=25:
                    win = 5 if iv=="1wk" else 10
                    sups, ress = support_resistance_levels(
                        data["High"], data["Low"], data["Close"], window=win, n_levels=4)
                    x0, x1 = data.index[0], data.index[-1]
                    for lvl in sups:
                        fig.add_shape(type="line", x0=x0, x1=x1, y0=lvl, y1=lvl,
                            line=dict(color="rgba(46,204,113,0.65)",width=1.2,dash="dot"),
                            row=1, col=1)
                        fig.add_annotation(x=x1, y=lvl, text=f"S {lvl:.2f}",
                            font=dict(size=9,color="#2ecc71"), showarrow=False,
                            xanchor="left", row=1, col=1)
                    for lvl in ress:
                        fig.add_shape(type="line", x0=x0, x1=x1, y0=lvl, y1=lvl,
                            line=dict(color="rgba(231,76,60,0.65)",width=1.2,dash="dot"),
                            row=1, col=1)
                        fig.add_annotation(x=x1, y=lvl, text=f"R {lvl:.2f}",
                            font=dict(size=9,color="#e74c3c"), showarrow=False,
                            xanchor="left", row=1, col=1)

                if show_pv and len(data)>=2:
                    pc = data.iloc[-2]
                    pp_d = pivot_points(float(pc["High"]),float(pc["Low"]),float(pc["Close"]))
                    pp_col = {"PP":"purple","R1":"#e74c3c","R2":"#c0392b","R3":"#922b21",
                              "S1":"#2ecc71","S2":"#27ae60","S3":"#1e8449"}
                    for k,c in pp_col.items():
                        fig.add_hline(y=pp_d[k], line_dash="longdash", line_color=c,
                            line_width=1, annotation_text=f"{k}: {pp_d[k]:.2f}",
                            annotation_position="right", annotation_font_size=9,
                            row=1, col=1)

                vcol = ["#2ecc71" if c>=o else "#e74c3c"
                        for c,o in zip(data["Close"],data["Open"])]
                fig.add_trace(go.Bar(x=data.index, y=data["Volume"],
                    name="Volume", marker_color=vcol, showlegend=False), row=2, col=1)

                rsi_v = rsi(data["Close"])
                fig.add_trace(go.Scatter(x=data.index, y=rsi_v, name="RSI",
                    line=dict(color="purple"), showlegend=False), row=3, col=1)
                for y, c in [(70,"red"),(30,"green")]:
                    fig.add_hline(y=y, line_dash="dash", line_color=c, row=3, col=1)
                fig.add_hrect(y0=70,y1=100,fillcolor="red",  opacity=0.05,line_width=0,row=3,col=1)
                fig.add_hrect(y0=0, y1=30, fillcolor="green",opacity=0.05,line_width=0,row=3,col=1)

                fig.update_layout(height=720, xaxis_rangeslider_visible=False,
                    margin=dict(t=40,b=20,l=0,r=90),
                    legend=dict(orientation="h",yanchor="bottom",y=1.02))
                fig.update_yaxes(title_text="Price ($)",row=1,col=1)
                fig.update_yaxes(title_text="Volume",   row=2,col=1)
                fig.update_yaxes(title_text="RSI",      row=3,col=1,range=[0,100])
                st.plotly_chart(fig, use_container_width=True)

                st.subheader("MACD")
                ml,sl,hist = macd(data["Close"])
                mf = go.Figure()
                mf.add_trace(go.Scatter(x=data.index,y=ml,  name="MACD",  line=dict(color="dodgerblue")))
                mf.add_trace(go.Scatter(x=data.index,y=sl,  name="Signal",line=dict(color="orange")))
                mf.add_trace(go.Bar(   x=data.index,y=hist, name="Histogram",
                    marker_color=["#2ecc71" if v>=0 else "#e74c3c" for v in hist]))
                mf.update_layout(height=280, margin=dict(t=10,b=10,l=0,r=0))
                st.plotly_chart(mf, use_container_width=True)

        # ══ Fundamentals & Earnings ═══════════════════════════════════════
        with tab_fund:
            with st.spinner("Loading fundamentals…"):
                earnings = get_earnings_info(ticker)
                filings  = get_recent_filings(ticker, days_back=180,
                               form_types=["8-K","10-K","10-Q","DEF 14A"])

            st.subheader("Company Snapshot")
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Sector",     info.get("sector","N/A"))
            c2.metric("Industry",   info.get("industry","N/A"))
            c3.metric("Market Cap", safe_money(info.get("marketCap")))
            emp = info.get("fullTimeEmployees")
            c4.metric("Employees",  f"{emp:,}" if emp else "N/A")
            c1,c2,c3,c4 = st.columns(4)
            pe=info.get("trailingPE"); fpe=info.get("forwardPE")
            dv=info.get("dividendYield"); bv=info.get("beta")
            c1.metric("P/E (TTM)",    f"{pe:.2f}"    if pe  else "N/A")
            c2.metric("P/E (Fwd)",    f"{fpe:.2f}"   if fpe else "N/A")
            c3.metric("Div. Yield",   f"{dv*100:.2f}%" if dv else "N/A")
            c4.metric("Beta",         f"{bv:.2f}"    if bv  else "N/A")
            if info.get("longBusinessSummary"):
                with st.expander("Business Description"):
                    st.write(info["longBusinessSummary"])

            st.divider()
            st.subheader("AI Fundamental Analysis")
            if llm_btn("Generate Fundamental Memo", "fund_ai"):
                news  = get_company_news_rss(ticker, company, max_articles=8)
                heads = [a["title"] for a in news]
                eh    = earnings.get("earnings_history")
                earn_str = "No earnings history."
                if eh is not None and not eh.empty:
                    cm = {c.lower():c for c in eh.columns}
                    ac = next((cm[k] for k in cm if "actual"   in k), None)
                    ec = next((cm[k] for k in cm if "estimate" in k), None)
                    if ac and ec:
                        earn_str = eh[[ac,ec]].tail(4).to_string(index=False)
                with st.spinner("Claude Sonnet 4.6 is analyzing…"):
                    memo = analyze_fundamentals(ticker,info,earn_str,filings,heads)
                st.markdown(memo)
                st.caption("Generated by Claude Sonnet 4.6 via OpenRouter")

            st.divider()
            st.subheader("Next Earnings")
            cal = earnings.get("calendar")
            if cal:
                try:
                    def pick(keys):
                        for k in keys:
                            if k in cal:
                                v = cal[k]
                                if hasattr(v,"__iter__") and not isinstance(v,str):
                                    v = list(v); return v[0] if v else "N/A"
                                return v
                        return "N/A"
                    nd = pick(["Earnings Date","earningsDate"])
                    ee = pick(["EPS Estimate","epsEstimate","Earnings Average"])
                    re = pick(["Revenue Estimate","revenueAverage","Revenue Average"])
                    c1,c2,c3 = st.columns(3)
                    c1.metric("Earnings Date", str(nd))
                    c2.metric("EPS Estimate",  f"${float(ee):.2f}" if ee!="N/A" else "N/A")
                    c3.metric("Revenue Est.",  safe_money(float(re) if re!="N/A" else None))
                except Exception:
                    st.info("Calendar format varies — check Yahoo Finance directly.")
            else:
                st.info("No upcoming earnings date found.")

            st.divider()
            st.subheader("EPS: Actual vs Estimate")
            eh = earnings.get("earnings_history")
            if eh is not None and not eh.empty:
                cm = {}
                for c in eh.columns:
                    cl = c.lower()
                    if "actual"   in cl: cm[c]="EPS Actual"
                    elif "estimate" in cl: cm[c]="EPS Estimate"
                    elif "surprise" in cl and "%" in cl: cm[c]="Surprise %"
                    elif "quarter" in cl: cm[c]="Quarter"
                    elif "date"    in cl: cm[c]="Date"
                eh = eh.rename(columns=cm)
                if "EPS Actual" in eh.columns and "EPS Estimate" in eh.columns:
                    xc = "Quarter" if "Quarter" in eh.columns else \
                         "Date"    if "Date"    in eh.columns else "idx"
                    if xc=="idx": eh["idx"]=[f"Q{i+1}" for i in range(len(eh))]
                    eh[xc] = eh[xc].astype(str)
                    eh["Beat"] = eh["EPS Actual"]>=eh["EPS Estimate"]
                    fig = go.Figure()
                    fig.add_trace(go.Bar(x=eh[xc], y=eh["EPS Actual"], name="Actual EPS",
                        marker_color=["#2ecc71" if b else "#e74c3c" for b in eh["Beat"]]))
                    fig.add_trace(go.Scatter(x=eh[xc], y=eh["EPS Estimate"],
                        name="Estimate", mode="markers+lines",
                        marker=dict(color="white",size=8,symbol="diamond",
                                    line=dict(color="gray",width=2)),
                        line=dict(color="gray",dash="dash")))
                    fig.update_layout(height=340, yaxis_title="EPS ($)",
                                      margin=dict(t=10,b=10,l=0,r=0))
                    st.plotly_chart(fig, use_container_width=True)
                    st.caption("🟢 Beat  |  🔴 Miss  |  ◇ Analyst estimate")
            else:
                st.info("No EPS history available.")

            st.divider()
            st.subheader("Quarterly Financials")
            qf = earnings.get("quarterly_financials")
            if qf is not None and not qf.empty:
                want  = ["Total Revenue","Gross Profit","Net Income","Operating Income","EBITDA"]
                avail = [r for r in want if r in qf.index]
                if avail:
                    qt = qf.loc[avail].T.sort_index()
                    qt.index = qt.index.astype(str).str[:10]
                    cols = ["dodgerblue","#2ecc71","#e74c3c","orange","purple"]
                    fig = go.Figure()
                    for i,row in enumerate(avail):
                        if row in qt.columns:
                            fig.add_trace(go.Bar(x=qt.index, y=qt[row]/1e6,
                                name=row, marker_color=cols[i%len(cols)]))
                    fig.update_layout(height=360, barmode="group", yaxis_title="USD Millions",
                        margin=dict(t=10,b=10,l=0,r=0),
                        legend=dict(orientation="h",yanchor="bottom",y=1.02))
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No quarterly financial data available.")

            st.divider()
            st.subheader("SEC Filings (last 6 months)")
            if not filings:
                st.info("No recent SEC filings found.")
            else:
                for f in filings:
                    with st.expander(f"**{f['form']}** — {f['date']}  |  {f['description']}"):
                        cl, cb = st.columns([3,1])
                        cl.markdown(f"[📄 Open on SEC.gov]({f['url']})")
                        if cb.button("🤖 Summarize", key=f"sec_{f['accession']}",
                                     disabled=not llm_ready,
                                     help="AI summary" if llm_ready else "Needs API key"):
                            with st.spinner("Fetching filing…"):
                                text = get_filing_text(f["url"])
                            with st.spinner("Claude is reading…"):
                                summ = summarize_sec_filing(f["form"],text,ticker)
                            st.markdown(summ)
                            st.caption("Generated by Claude Sonnet 4.6 via OpenRouter")

        # ══ Geopolitical & Macro ══════════════════════════════════════════
        with tab_geo:
            st.subheader(f"Geopolitical & Macro Risk — {company}")
            st.caption("Claude reads the company's sector, geography, business model, and news to assess risk.")
            c1,c2,c3 = st.columns(3)
            c1.metric("HQ Country", info.get("country","N/A"))
            c2.metric("Sector",     info.get("sector","N/A"))
            c3.metric("Industry",   info.get("industry","N/A"))
            with st.expander("Business Overview"):
                st.write(info.get("longBusinessSummary","Not available."))
            st.divider()
            if llm_btn("Run Geopolitical Risk Assessment", "geo_ai"):
                news  = get_company_news_rss(ticker, company, max_articles=10)
                heads = [a["title"] for a in news]
                with st.spinner("Claude Sonnet 4.6 is assessing risks…"):
                    geo = analyze_geopolitical(ticker, info, heads)
                st.markdown(geo)
                st.caption("Generated by Claude Sonnet 4.6 via OpenRouter")
            st.divider()
            st.subheader("Useful Macro References")
            st.info(
                "- [FRED Economic Data](https://fred.stlouisfed.org/) — rates, inflation, GDP\n"
                "- [US Trade Representative](https://ustr.gov/) — tariff & trade policy\n"
                "- [SEC 10-K Item 1A](https://www.sec.gov/) — company's own risk disclosures\n"
                "- [Geopolitical Risk Index](https://www.matteoiacoviello.com/gpr.htm)"
            )

        # ══ News ══════════════════════════════════════════════════════════
        with tab_news:
            st.subheader(f"News & Announcements — {company}")
            st.caption("Google News + Yahoo Finance RSS  ·  30 min cache")
            with st.spinner("Fetching news…"):
                articles = get_company_news_rss(ticker, company, max_articles=25)
            if not articles:
                st.warning("No news found. Try again in a moment.")
            else:
                search = st.text_input("Filter headlines", placeholder="earnings, CEO, acquisition…")
                if search:
                    articles = [a for a in articles
                                if search.lower() in a["title"].lower()
                                or search.lower() in a.get("summary","").lower()]
                    st.caption(f"{len(articles)} results for '{search}'")
                for a in articles:
                    with st.container():
                        ct, cd = st.columns([5,1])
                        with ct:
                            st.markdown(f"**[{a['title']}]({a['link']})**" if a["link"]
                                        else f"**{a['title']}**")
                            if a.get("summary"):
                                clean = _re.sub(r"<[^>]+>","",a["summary"])[:280]
                                st.caption(clean + ("…" if len(a.get("summary",""))>280 else ""))
                        with cd:
                            st.caption(a.get("published","")[:16])
                            if a.get("source"): st.caption(a["source"][:25])
                        st.divider()


# ─────────────────────────────────────────────────────────────────────────────
# Performance
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Performance":
    st.header("Portfolio Performance")
    if not holdings:
        st.info("Add holdings to see performance.")
    else:
        period = st.select_slider("Period",
            options=["1mo","3mo","6mo","1y","2y","5y"], value="1y")
        with st.spinner("Computing history…"):
            history  = portfolio_history(holdings, period)
        if history.empty or "Total" not in history.columns:
            st.warning("Couldn't compute history.")
        else:
            fig = go.Figure(go.Scatter(x=history.index, y=history["Total"],
                fill="tozeroy", name="Portfolio Value",
                line=dict(color="#2ecc71",width=2), fillcolor="rgba(46,204,113,0.15)"))
            fig.update_layout(height=400, yaxis_title="Value ($)", margin=dict(t=20,b=20,l=0,r=0))
            st.plotly_chart(fig, use_container_width=True)

            rets = calculate_returns(history["Total"])
            pr   = (history["Total"].iloc[-1]/history["Total"].iloc[0]-1)*100
            vol  = annualized_volatility(rets)*100
            sr   = sharpe_ratio(rets)
            mdd  = max_drawdown(history["Total"])*100
            spy  = get_historical_data("SPY", period)
            beta = beta_vs_benchmark(rets,calculate_returns(spy["Close"])) if not spy.empty else 0.

            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("Period Return",    pct(pr))
            c2.metric("Volatility (Ann.)",f"{vol:.2f}%")
            c3.metric("Sharpe",           f"{sr:.2f}")
            c4.metric("Max Drawdown",     f"{mdd:.2f}%")
            c5.metric("Beta vs SPY",      f"{beta:.2f}")

            if not spy.empty:
                st.subheader("vs S&P 500 (normalized to 100)")
                pn = (history["Total"]/history["Total"].iloc[0])*100
                sn = (spy["Close"]/spy["Close"].iloc[0])*100
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=pn.index, y=pn,
                    name="Portfolio",   line=dict(color="#2ecc71",width=2)))
                fig.add_trace(go.Scatter(x=sn.index, y=sn,
                    name="S&P 500 (SPY)", line=dict(color="#3498db",width=2)))
                fig.update_layout(height=380, yaxis_title="Normalized Value",
                    margin=dict(t=20,b=20,l=0,r=0),
                    legend=dict(orientation="h",yanchor="bottom",y=1.02))
                st.plotly_chart(fig, use_container_width=True)

            st.subheader("Daily Returns Distribution")
            fig = px.histogram(rets*100, nbins=40, labels={"value":"Daily Return (%)"})
            fig.update_layout(height=280, showlegend=False, margin=dict(t=10,b=10,l=0,r=0))
            st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
elif page == "📋 Summary":
    st.header("Portfolio Summary")
    st.caption(
        "Claude Sonnet 4.6 reads your holdings, SEC filings, and news "
        "for the selected period and writes a personal investment memo."
    )

    if not holdings:
        st.info("Add holdings to generate a summary.")
    else:
        cp, cg = st.columns([2,1])
        with cp:
            period_label = st.radio("Period", ["Daily","Weekly","Monthly"],
                                     horizontal=True, index=1)
        with cg:
            st.write(""); st.write("")
            go_btn = llm_btn("Generate Summary", "gen_summary")

        if go_btn:
            bar  = st.progress(0.)
            stat = st.empty()
            try:
                summary_text, metrics, h_data = run_summary_pipeline(
                    holdings=holdings,
                    period_label=period_label,
                    progress_callback=lambda p,m: (bar.progress(p), stat.text(m)),
                )
                bar.empty(); stat.empty()
                st.success("Summary saved to data/summaries/")
                st.divider()
                st.markdown(summary_text)
                st.caption("Generated by Claude Sonnet 4.6 via OpenRouter")
            except Exception as e:
                bar.empty(); stat.empty()
                st.error(f"Failed: {e}")

        st.divider()
        st.subheader("Past Summaries")
        saved = list_saved_summaries()
        if not saved:
            st.info("No saved summaries yet.")
        else:
            load_col, btn_col = st.columns([3, 1])
            with load_col:
                sel = st.selectbox("Load a past summary", [s["name"] for s in saved])
            with btn_col:
                st.write(""); st.write("")
                load_btn = st.button("Load", key="load_past")
            if load_btn:
                chosen = next((s for s in saved if s["name"]==sel), None)
                if chosen:
                    content = open(chosen["path"]).read()
                    st.markdown(content)
                    st.download_button("⬇️ Download as Markdown", data=content,
                        file_name=chosen["name"]+".md", mime="text/markdown")



# ─────────────────────────────────────────────────────────────────────────────
# Monitor  — real-time news alerts
# ─────────────────────────────────────────────────────────────────────────────
elif page == "🔔 Monitor":
    try:
        from streamlit_autorefresh import st_autorefresh
        HAS_AUTOREFRESH = True
    except ImportError:
        HAS_AUTOREFRESH = False

    st.header("🔔 News Monitor")
    st.caption(
        "Polls SEC EDGAR 8-K filings, Business Wire, PR Newswire, Yahoo Finance, "
        "and Google News. Typically faster than major news outlets."
    )

    # ── Session state ─────────────────────────────────────────────────────
    if "monitor_seen"      not in st.session_state: st.session_state.monitor_seen      = set()
    if "monitor_alerts"    not in st.session_state: st.session_state.monitor_alerts    = []
    if "monitor_watchlist" not in st.session_state:
        st.session_state.monitor_watchlist = [h["ticker"] for h in holdings]

    # ── Controls ──────────────────────────────────────────────────────────
    col_wl, col_ctrl = st.columns([3, 2])
    with col_wl:
        st.subheader("Watchlist")
        add_col, btn_col = st.columns([3, 1])
        new_tick = add_col.text_input("Add ticker", placeholder="NVDA",
                                       label_visibility="collapsed")
        if btn_col.button("Add", key="wl_add"):
            t = new_tick.strip().upper()
            if t and t not in st.session_state.monitor_watchlist:
                st.session_state.monitor_watchlist.append(t)
                st.rerun()
        if st.session_state.monitor_watchlist:
            tick_cols = st.columns(min(len(st.session_state.monitor_watchlist), 6))
            for i, t in enumerate(st.session_state.monitor_watchlist):
                with tick_cols[i % 6]:
                    if st.button(f"{t} ✕", key=f"rem_{t}"):
                        st.session_state.monitor_watchlist.remove(t); st.rerun()

    with col_ctrl:
        st.subheader("Settings")
        min_score = st.slider("Min. significance to alert", 1, 10, 6,
            help="6=deals/earnings/legal, 9=critical only (M&A, FDA, bankruptcy)")
        if HAS_AUTOREFRESH:
            interval_sec = st.select_slider("Auto-refresh", [60,90,120,180,300],
                value=90, format_func=lambda x: f"every {x}s")
            if not st.checkbox("Pause auto-refresh"):
                st_autorefresh(interval=interval_sec*1000, key="monitor_ar")
        else:
            st.caption("Tip: `pip install streamlit-autorefresh` for auto-refresh")
            if st.button("🔄 Refresh now"):
                st.cache_data.clear(); st.rerun()

    st.divider()

    if not st.session_state.monitor_watchlist:
        st.info("Add tickers above to start monitoring.")
        st.stop()

    # ── Fetch & detect new ────────────────────────────────────────────────
    from src.data_fetcher import get_stock_info as _gsi
    from concurrent.futures import ThreadPoolExecutor

    def _fetch(tick):
        info    = _gsi(tick)
        company = info.get("longName", tick)
        arts    = fetch_all(tick, company)
        return tick, company, arts

    all_new, ticker_data = [], {}
    with st.spinner(f"Fetching news for {len(st.session_state.monitor_watchlist)} tickers…"):
        with ThreadPoolExecutor(max_workers=8) as ex:
            for tick, company, arts in ex.map(_fetch, st.session_state.monitor_watchlist):
                ticker_data[tick] = {"articles": arts, "company": company}
                for a in arts:
                    if a["id"] not in st.session_state.monitor_seen:
                        st.session_state.monitor_seen.add(a["id"])
                        if a["score"] >= min_score:
                            a["ticker"] = tick; a["company"] = company
                            all_new.append(a)

    if all_new:
        st.session_state.monitor_alerts = (all_new + st.session_state.monitor_alerts)[:50]

    # ── Alert banners ─────────────────────────────────────────────────────
    critical = [a for a in st.session_state.monitor_alerts if a["score"] >= 9]
    high     = [a for a in st.session_state.monitor_alerts if 7 <= a["score"] < 9]
    if critical:
        st.error("🚨 **CRITICAL** — " + "  |  ".join(
            f"**{a['ticker']}**: {a['title'][:80]}" for a in critical[:3]))
    if high:
        st.warning("⚠️ **High-Impact** — " + "  |  ".join(
            f"**{a['ticker']}**: {a['title'][:70]}" for a in high[:3]))

    # Browser push notification for new critical items
    new_critical = [a for a in all_new if a["score"] >= 9]
    if new_critical:
        nc = new_critical[0]
        st.components.v1.html(f"""<script>
        function notify() {{
            if (Notification.permission==="granted") {{
                new Notification("🚨 {nc['ticker']}: {nc['title'][:55].replace('"',"'")}",
                    {{body:"{nc['label']} | {nc['source']}"}});
            }} else if (Notification.permission!=="denied") {{
                Notification.requestPermission().then(p=>{{if(p==="granted")notify();}});
            }}
        }}
        notify();
        </script>""", height=0)

    st.caption(
        f"Last checked: **{datetime.now().strftime('%H:%M:%S')}**  ·  "
        f"{len(st.session_state.monitor_watchlist)} ticker(s)  ·  "
        f"{len(st.session_state.monitor_seen)} articles seen this session"
    )

    # ── Per-ticker feeds ──────────────────────────────────────────────────
    show_all = st.checkbox("Show all articles (not just high-significance)", value=False)

    for tick, td in ticker_data.items():
        arts    = td["articles"]
        company = td["company"]
        top_s   = max((a["score"] for a in arts), default=0)
        badge   = " 🚨" if top_s>=9 else (" ⚠️" if top_s>=7 else "")
        visible = arts if show_all else [a for a in arts if a["score"]>=min_score]

        with st.expander(
            f"**{tick}** — {company}{badge}  ({len(arts)} articles, {len(visible)} above threshold)",
            expanded=(top_s >= min_score),
        ):
            if not arts:
                st.info("No articles found. Feeds update every 90 s.")
                continue
            display = visible or arts[:3]

            new_ids    = {x["id"] for x in all_new}
            cards_html = ""
            for a in display[:15]:
                is_new       = a["id"] in new_ids
                bc           = score_color(a["score"])
                bg           = score_bg(a["score"])
                new_tag      = ('<span style="background:#2ecc71;color:#fff;padding:1px 6px;'
                                'border-radius:3px;font-size:11px;font-weight:bold;margin-right:5px;">NEW</span>'
                                if is_new else "")
                title_html   = (f'<a href="{a["link"]}" target="_blank" '
                                f'style="color:inherit;text-decoration:none;">{a["title"]}</a>'
                                if a.get("link") else a["title"])
                summary_html = (f'<br><span style="font-size:12px;color:#aaa;">{a["summary"][:180]}</span>'
                                if a.get("summary") else "")
                cards_html += (
                    f'<div style="border-left:3px solid {bc};background:{bg};padding:8px 12px;margin:4px 0;border-radius:0 4px 4px 0;">'
                    f'{new_tag}<span style="background:{bc};color:#fff;padding:1px 8px;border-radius:4px;font-size:11px;font-weight:bold;">{a["score"]}/10 {a["label"]}</span>'
                    f'<span style="margin-left:8px;font-size:11px;color:#888;">{a["speed"]} {a["source"]}</span>'
                    f'<br><span style="font-size:14px;font-weight:600;line-height:1.5;">{title_html}</span>'
                    f'{summary_html}'
                    f'<br><span style="font-size:11px;color:#777;">{a.get("published","")[:22]}</span>'
                    f'</div>'
                )
            st.components.v1.html(
                f'<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;">{cards_html}</div>',
                height=min(len(display[:15]) * 105, 1500),
                scrolling=True,
            )

    # ── Alert history ─────────────────────────────────────────────────────
    if st.session_state.monitor_alerts:
        st.divider()
        with st.expander(f"📜 Alert History ({len(st.session_state.monitor_alerts)} this session)"):
            for a in st.session_state.monitor_alerts[:20]:
                st.markdown(
                    f"`{a.get('ticker','')}` **{a['score']}/10** {a['label']} — "
                    f"[{a['title'][:85]}]({a['link']})  "
                    f"<span style='color:#888;font-size:11px;'>{a.get('source','')} · "
                    f"{a.get('published','')[:16]}</span>",
                    unsafe_allow_html=True,
                )
            if st.button("Clear history", key="clr"):
                st.session_state.monitor_alerts = []; st.rerun()

    # ── Legend ────────────────────────────────────────────────────────────
    with st.expander("ℹ️ Source Speed Guide & Scoring"):
        st.markdown("""
**Source speed tiers:**

| Speed | Source | Typical lag | Notes |
|-------|--------|-------------|-------|
| ⚡⚡⚡⚡ | SEC EDGAR 8-K | Instant | Companies file *before* press release |
| ⚡⚡⚡ | Business Wire | 0-2 min | Primary press release wire |
| ⚡⚡⚡ | PR Newswire | 0-2 min | Second major wire |
| ⚡⚡ | Yahoo Finance | 2-5 min | Syndicates wires quickly |
| ⚡ | Google News | 5-15 min | Broad aggregation |

**Significance scores:**
🔴 **9-10** — M&A, FDA approvals, bankruptcy, criminal charges  
🟠 **7-8** — Earnings, major contracts, CEO changes, lawsuits  
🟡 **5-6** — Analyst ratings, dividends, product launches  
⚪ **1-4** — General news, market commentary  

**Pro tip:** SEC 8-K item codes tell you *exactly* what happened before you read the filing:
`2.02` = Earnings · `2.01` = M&A · `5.02` = Leadership change · `1.05` = Cybersecurity
        """)


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR FOOTER ANCHOR
# ─────────────────────────────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.caption(
    "Data: Yahoo Finance · ~15 min delay\n"
    "SEC: EDGAR API (free)\n"
    "AI: Claude Sonnet 4.6 via OpenRouter\n"
    "Personal use only — not investment advice."
)
