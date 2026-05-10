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
    portfolio = load_portfolio()
    portfolio["holdings"].append({
        "ticker": ticker.upper().strip(),
        "shares": float(shares),
        "purchase_price": float(purchase_price),
        "purchase_date": str(purchase_date),
    })
    save_portfolio(portfolio)


def remove_holding(index):
    portfolio = load_portfolio()
    if 0 <= index < len(portfolio["holdings"]):
        portfolio["holdings"].pop(index)
        save_portfolio(portfolio)
