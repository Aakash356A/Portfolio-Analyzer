import re

with open("app.py", "r") as f:
    text = f.read()

# find "                if df_raw is None:"
start_str = '                if df_raw is None:\n                    st.error("Could not parse this file. Make sure it is a CSV export from your broker.")\n                else:'
start_idx = text.find(start_str)

end_str = '            except Exception as e:\n                st.error(f"Failed to read file: {e}")'
end_idx = text.find(end_str)

if start_idx != -1 and end_idx != -1:
    old_block = text[start_idx:end_idx]
    
    new_block = """                if df_raw is None:
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
"""
    
    new_text = text[:start_idx] + new_block + text[end_idx:]
    with open("app.py", "w") as f:
        f.write(new_text)
    print("Patched successfully!")
else:
    print("Could not find blocks. Start idx:", start_idx, "End idx:", end_idx)
