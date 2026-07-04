"""
Alpaca paper-trading API wrapper.

Thin urllib client (no SDK dependency, matching core/alpaca.py's style)
for the handful of endpoints the live system needs. All calls go to the
PAPER endpoint from live/config.py — never a real-money URL.
"""

import json
import urllib.request
import urllib.parse

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from core.alpaca import get_headers
from live.config import PAPER_BASE_URL


def _request(method: str, path: str, params: dict = None, body: dict = None):
    url = f"{PAPER_BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    headers = {**get_headers(), "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


# ── Read endpoints ────────────────────────────────────────────

def get_clock() -> dict:
    """Market clock: {is_open, next_open, next_close, timestamp}."""
    return _request("GET", "/v2/clock")


def get_account() -> dict:
    """Account snapshot: equity, cash, buying_power, status …"""
    return _request("GET", "/v2/account")


def get_positions() -> dict:
    """Current positions as {symbol: signed share qty (float)}."""
    positions = _request("GET", "/v2/positions") or []
    return {p["symbol"]: float(p["qty"]) for p in positions}


def list_orders(status: str = "closed", after: str = None, limit: int = 500) -> list:
    """Orders filtered by status; `after` is an ISO timestamp."""
    params = {"status": status, "limit": limit, "direction": "desc"}
    if after:
        params["after"] = after
    return _request("GET", "/v2/orders", params=params) or []


# ── Write endpoints (paper account only) ──────────────────────

def submit_order(symbol: str, qty: int, side: str,
                 time_in_force: str = "cls") -> dict:
    """
    Whole-share market order. Default time_in_force "cls" = market-on-close,
    matching the backtest's trade-at-the-close execution assumption.
    """
    return _request("POST", "/v2/orders", body={
        "symbol":        symbol,
        "qty":           str(int(qty)),
        "side":          side,
        "type":          "market",
        "time_in_force": time_in_force,
    })


def cancel_open_orders() -> None:
    """Cancel anything still pending (safety before a fresh rebalance)."""
    _request("DELETE", "/v2/orders")
