"""
SnapTrade integration — auto-import brokerage holdings into portfolio.json.

Why SnapTrade (vs Plaid)
------------------------
SnapTrade is purpose-built for *investment* data (positions, balances, trades).
There is no public_token exchange and no local callback server: you register a
user once, open the hosted Connection Portal in the browser, the user logs into
their broker on SnapTrade's side, then you read their positions directly.

Flow
----
1. App registers a single local user (once) -> {userId, userSecret} saved to disk.
2. "Connect Brokerage" calls login_snap_trade_user -> a redirectURI (portal link).
3. We open that link in the browser; the user connects their broker there.
4. "Sync Holdings" lists the user's accounts, reads positions, and writes them
   into portfolio.json.

Setup (free)
------------
1. Sign up at https://dashboard.snaptrade.com and verify your email.
2. Generate an API key -> you get a Client ID and a Consumer Key.
3. Put them in .env:
       SNAPTRADE_CLIENT_ID=...
       SNAPTRADE_CONSUMER_KEY=...
4. pip install snaptrade-python-sdk

The free tier allows a limited number of concurrent connections — plenty for a
personal portfolio (you only connect your own account).
"""

from __future__ import annotations

import json
import os
import uuid
import webbrowser
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────────
_ROOT      = Path(__file__).parent.parent
_USER_FILE = _ROOT / "data" / ".snaptrade_user.json"


# ─────────────────────────────────────────────────────────────────────────────
# Client
# ─────────────────────────────────────────────────────────────────────────────

def _client():
    """Return an authenticated SnapTrade client."""
    try:
        from snaptrade_client import SnapTrade
    except ImportError:
        raise ImportError("Run: pip install snaptrade-python-sdk")

    client_id    = os.getenv("SNAPTRADE_CLIENT_ID", "").strip()
    consumer_key = os.getenv("SNAPTRADE_CONSUMER_KEY", "").strip()

    if not client_id or not consumer_key:
        raise ValueError(
            "Set SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY in your .env file."
        )

    return SnapTrade(consumer_key=consumer_key, client_id=client_id)


def is_configured() -> bool:
    """True if API keys are present in the environment."""
    return bool(
        os.getenv("SNAPTRADE_CLIENT_ID", "").strip()
        and os.getenv("SNAPTRADE_CONSUMER_KEY", "").strip()
    )


# ─────────────────────────────────────────────────────────────────────────────
# Local user registration  (step 1)
# ─────────────────────────────────────────────────────────────────────────────

def _load_user() -> dict | None:
    if _USER_FILE.exists():
        try:
            return json.loads(_USER_FILE.read_text())
        except Exception:
            return None
    return None


def _save_user(user: dict) -> None:
    _USER_FILE.parent.mkdir(parents=True, exist_ok=True)
    _USER_FILE.write_text(json.dumps(user))


def get_or_register_user() -> dict:
    """
    Return the saved {userId, userSecret}, registering a new SnapTrade user the
    first time. The userSecret is generated once and stored locally.
    """
    user = _load_user()
    if user and user.get("userId") and user.get("userSecret"):
        return user

    user_id = f"portfolio-tracker-{uuid.uuid4()}"
    resp = _client().authentication.register_snap_trade_user(body={"userId": user_id})
    user = {"userId": user_id, "userSecret": resp.body["userSecret"]}
    _save_user(user)
    return user


def is_registered() -> bool:
    return _load_user() is not None


def disconnect() -> None:
    """
    Forget the local user (and ask SnapTrade to delete it). This removes all
    brokerage connections associated with the user on SnapTrade's side.
    """
    user = _load_user()
    if user:
        try:
            _client().authentication.delete_snap_trade_user(
                query_params={"userId": user["userId"]}
            )
        except Exception:
            pass
    if _USER_FILE.exists():
        _USER_FILE.unlink()


# ─────────────────────────────────────────────────────────────────────────────
# Connection portal  (steps 2–3)
# ─────────────────────────────────────────────────────────────────────────────

def get_connection_portal_url() -> str:
    """
    Register the user if needed, then return a SnapTrade Connection Portal URL.
    Opening it lets the user log into their brokerage on SnapTrade's side.
    """
    user = get_or_register_user()
    resp = _client().authentication.login_snap_trade_user(
        query_params={"userId": user["userId"], "userSecret": user["userSecret"]}
    )
    body = resp.body
    # body is normally {"redirectURI": "https://app.snaptrade.com/..."}
    if isinstance(body, dict):
        return body.get("redirectURI") or body.get("redirectUri") or str(body)
    return str(body)


def open_connection_portal() -> str:
    """Open the SnapTrade Connection Portal in the default browser. Returns the URL."""
    url = get_connection_portal_url()
    webbrowser.open(url)
    return url


def list_connections() -> list[dict]:
    """Return the user's active brokerage connections (empty list if none)."""
    user = _load_user()
    if not user:
        return []
    resp = _client().connections.list_brokerage_authorizations(
        user_id=user["userId"], user_secret=user["userSecret"]
    )
    body = resp.body
    return list(body) if isinstance(body, list) else []


# ─────────────────────────────────────────────────────────────────────────────
# Holdings sync  (step 4)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_holdings() -> list[dict]:
    """
    Fetch positions across all connected accounts and return them in
    portfolio.json format:
        [{"ticker": "AAPL", "shares": 10, "purchase_price": 150.0,
          "purchase_date": "2024-01-15"}]

    Positions for the same ticker across multiple accounts are merged with a
    share-weighted average purchase price.
    """
    user = _load_user()
    if not user:
        raise ValueError("No SnapTrade user — connect a brokerage first.")

    client    = _client()
    user_id   = user["userId"]
    secret    = user["userSecret"]

    accounts_resp = client.account_information.list_user_accounts(
        user_id=user_id, user_secret=secret
    )
    accounts = accounts_resp.body if isinstance(accounts_resp.body, list) else []

    # ticker -> {"shares": float, "cost": float}  (cost = shares * avg_price)
    merged: dict[str, dict] = {}

    for acct in accounts:
        account_id = acct.get("id")
        if not account_id:
            continue

        pos_resp = client.account_information.get_user_account_positions(
            user_id=user_id, user_secret=secret, account_id=account_id
        )
        positions = pos_resp.body if isinstance(pos_resp.body, list) else []

        for p in positions:
            sym = (p.get("symbol") or {}).get("symbol") or {}
            ticker = (sym.get("symbol") or sym.get("raw_symbol") or "").upper().strip()
            if not ticker:
                continue

            shares = float(p.get("units") or 0)
            if shares <= 0:
                continue

            # Prefer real cost basis; fall back to last market price.
            avg = p.get("average_purchase_price")
            price = float(avg) if avg else float(p.get("price") or 0)
            if price <= 0:
                continue

            slot = merged.setdefault(ticker, {"shares": 0.0, "cost": 0.0})
            slot["shares"] += shares
            slot["cost"]   += shares * price

    holdings = []
    for ticker, slot in merged.items():
        shares = round(slot["shares"], 6)
        if shares <= 0:
            continue
        avg_price = round(slot["cost"] / slot["shares"], 4)
        holdings.append({
            "ticker":         ticker,
            "shares":         shares,
            "purchase_price": avg_price,
            "purchase_date":  "2024-01-01",  # SnapTrade positions don't expose a lot date
        })

    return holdings
