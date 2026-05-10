"""Portfolio Tracker & Analyzer — main Streamlit app.
Run with:  streamlit run app.py
"""
import re as _re
from datetime import datetime
from pathlib import Path

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
from src.portfolio import add_holding, load_portfolio, remove_holding
from src.sec_edgar import get_filing_text, get_recent_filings
from src.summary_pipeline import list_saved_summaries, run_summary_pipeline

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
    ["Dashboard", "Manage Holdings", "Stock Analysis", "Performance", "📋 Summary"],
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
    st.subheader("Add a Holding")
    with st.form("add_holding", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            ticker = st.text_input("Ticker", placeholder="AAPL")
            shares = st.number_input("Shares", min_value=0., step=0.01, format="%.4f")
        with c2:
            pp   = st.number_input("Purchase Price ($)", min_value=0., step=0.01, format="%.2f")
            pdate = st.date_input("Purchase Date", value=datetime.today())
        if st.form_submit_button("Add"):
            if not ticker or shares<=0 or pp<=0:
                st.error("Fill in all fields.")
            else:
                price = get_current_price(ticker)
                if price is None:
                    st.error(f"Couldn't verify '{ticker.upper()}'. Check the symbol.")
                else:
                    add_holding(ticker, shares, pp, pdate.isoformat())
                    st.success(f"Added {shares} shares of {ticker.upper()} (current: {fmt(price)})")
                    st.rerun()

    st.subheader("Current Holdings")
    if not holdings:
        st.info("No holdings yet.")
    else:
        for i, h in enumerate(holdings):
            c1,c2,c3,c4,c5 = st.columns([2,2,2,2,1])
            c1.markdown(f"**{h['ticker']}**")
            c2.write(f"{h['shares']} shares")
            c3.write(f"@ {fmt(h['purchase_price'])}")
            c4.write(h.get("purchase_date",""))
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
            sel = st.selectbox("Load a past summary", [s["name"] for s in saved])
            chosen = next((s for s in saved if s["name"]==sel), None)
            if chosen:
                content = open(chosen["path"]).read()
                st.markdown(content)
                st.download_button("⬇️ Download as Markdown", data=content,
                    file_name=chosen["name"]+".md", mime="text/markdown")


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar footer
# ─────────────────────────────────────────────────────────────────────────────
st.sidebar.markdown("---")
st.sidebar.caption(
    "Data: Yahoo Finance · ~15 min delay\n"
    "SEC: EDGAR API (free)\n"
    "AI: Claude Sonnet 4.6 via OpenRouter\n"
    "Personal use only — not investment advice."
)
