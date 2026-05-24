import pandas as pd
import io

raw = open('/Users/aakashdivakar/Downloads/Robinhood.csv', 'rb').read()
_DETECT_KEYS = ["symbol", "ticker", "instrument", "qty", "quantity", "shares", "trans code", "activity date"]

df_raw = None
for skip in [0, 1, 2, 3]:
    try:
        df_try = pd.read_csv(
            io.BytesIO(raw), skiprows=skip,
            encoding="utf-8-sig", engine="python",
            on_bad_lines="skip",
        )
        cols_lower = " ".join(str(c).lower() for c in df_try.columns)
        print(f"skip={skip}, cols: {cols_lower}")
        if any(k in cols_lower for k in _DETECT_KEYS):
            df_raw = df_try
            print("Detected!")
            break
    except Exception as e:
        print(f"Error on skip {skip}: {e}")

