import re

with open("app.py", "r") as f:
    content = f.read()

replacement = """        BROKER_MAPPINGS = {
            "robinhood": {"date": "Activity Date", "ticker": "Instrument", "action": "Trans Code", "quantity": "Quantity", "price": "Price"},
            "fidelity": {"date": "Run Date", "ticker": "Symbol", "action": "Action", "quantity": "Quantity", "price": "Price"},
            "schwab": {"date": "Date", "ticker": "Security", "action": "Action", "quantity": "Quantity", "price": "Price"},
            "vanguard": {"date": "Trade Date", "ticker": "Symbol", "action": "Transaction Type", "quantity": "Shares", "price": "Share Price"}
        }

        def normalize_broker_data(df: pd.DataFrame, broker_name: str) -> pd.DataFrame:
            mapping = BROKER_MAPPINGS.get(broker_name.lower())
            if not mapping:
                return df
            
            # Find closest matching columns
            rename_dict = {}
            for std_key, expected_col in mapping.items():
                match = _exact_col(df, [expected_col]) or _fuzzy_col(df, [expected_col])
                if match:
                    rename_dict[match] = std_key
                    
            std_df = df.rename(columns=rename_dict)
            
            # Ensure price if missing but amount and qty exist (for Schwab)
            if "price" not in std_df.columns and "Amount" in df.columns and "quantity" in std_df.columns:
                try:
                    std_df["price"] = abs(df["Amount"] / std_df["quantity"])
                except:
                    pass
                    
            cols_to_keep = [c for c in ['date', 'ticker', 'action', 'quantity', 'price'] if c in std_df.columns]
            return std_df[cols_to_keep]

        uploaded = st.file_uploader(
            "Upload CSV from your broker (transaction history or positions export)",
            type=["csv"],
            key="csv_import",
        )
        
        broker_choice = st.selectbox("Select Broker Format", ["Auto-detect", "Robinhood", "Fidelity", "Schwab", "Vanguard", "Generic Positions Snapshot"])

        if uploaded is not None:"""

print("File path ready")
