"""Portfolio storage. Holdings live in data/portfolio.json as a simple list."""
import json
from pathlib import Path

PORTFOLIO_FILE = Path("data/portfolio.json")


def load_portfolio():
    if not PORTFOLIO_FILE.exists():
        return {"holdings": []}
    with open(PORTFOLIO_FILE, "r") as f:
        return json.load(f)


def save_portfolio(portfolio):
    PORTFOLIO_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(portfolio, f, indent=2)


def add_holding(ticker, shares, purchase_price, purchase_date):
    """Buy shares. If ticker already exists, recalculate weighted average price."""
    portfolio = load_portfolio()
    ticker = ticker.upper().strip()
    shares = float(shares)
    purchase_price = float(purchase_price)

    for h in portfolio["holdings"]:
        if h["ticker"] == ticker:
            old_cost = h["shares"] * h["purchase_price"]
            new_cost = shares * purchase_price
            h["shares"] = round(h["shares"] + shares, 6)
            h["purchase_price"] = round((old_cost + new_cost) / h["shares"], 4)
            save_portfolio(portfolio)
            return

    # New position
    portfolio["holdings"].append({
        "ticker": ticker,
        "shares": shares,
        "purchase_price": purchase_price,
        "purchase_date": str(purchase_date),
    })
    save_portfolio(portfolio)


def sell_holding(ticker, shares_to_sell):
    """
    Sell shares from an existing position. Raises ValueError if ticker not found
    or shares_to_sell exceeds current holdings. Removes the position entirely
    if all shares are sold.
    Returns remaining shares (0 if fully closed).
    """
    portfolio = load_portfolio()
    ticker = ticker.upper().strip()
    shares_to_sell = float(shares_to_sell)

    for i, h in enumerate(portfolio["holdings"]):
        if h["ticker"] == ticker:
            if shares_to_sell > h["shares"] + 1e-9:
                raise ValueError(
                    f"Cannot sell {shares_to_sell} shares of {ticker} — "
                    f"you only hold {h['shares']}."
                )
            remaining = round(h["shares"] - shares_to_sell, 6)
            if remaining < 1e-6:
                portfolio["holdings"].pop(i)
                save_portfolio(portfolio)
                return 0.0
            h["shares"] = remaining
            save_portfolio(portfolio)
            return remaining

    raise ValueError(f"{ticker} not found in portfolio.")


def remove_holding(index):
    portfolio = load_portfolio()
    if 0 <= index < len(portfolio["holdings"]):
        portfolio["holdings"].pop(index)
        save_portfolio(portfolio)
