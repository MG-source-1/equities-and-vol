"""
Core data fetching — Alpaca for prices, CBOE for the VIX. Zero yfinance.

T-bill proxy:
  BIL (SPDR Bloomberg 1-3 Month T-Bill ETF) replaces ^IRX.
  BIL tracks the 1-3 month US T-bill yield with an expense ratio of 0.135%/yr —
  a negligibly conservative proxy for the risk-free rate.

VIX:
  fetch_vix() pulls the official daily VIX history straight from CBOE's
  public CSV (no key required, data back to 1990). The VIX is 30-day SPX
  implied vol — the implied-vol input for the options/VRP layer.
"""

import sys
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pandas as pd
from core.alpaca import fetch_bars
from config import DATA_CACHE_DIR


def fetch_prices(tickers: list, start: str, end: str) -> pd.DataFrame:
    """Daily closing prices for a list of ETF/stock tickers from Alpaca."""
    closes = {}
    for ticker in tickers:
        try:
            df = fetch_bars(ticker, start, end, "1Day",
                            cache_dir=DATA_CACHE_DIR, verbose=False)
            if not df.empty:
                closes[ticker] = df["close"]
        except Exception as e:
            print(f"[data] WARNING: could not fetch {ticker} — {e}")

    result  = pd.DataFrame(closes).dropna(how="all")
    missing = [t for t in tickers if t not in result.columns]
    if missing:
        print(f"[data] WARNING: no data for {missing}, dropping them.")
    return result[[t for t in tickers if t in result.columns]]


def fetch_spy(start: str, end: str, initial_capital: float) -> pd.Series:
    """SPY cumulative value series starting at initial_capital (equity benchmark)."""
    df  = fetch_bars("SPY", start, end, "1Day", cache_dir=DATA_CACHE_DIR)
    ret = df["close"].pct_change().fillna(0)
    cumulative      = (1 + ret).cumprod() * initial_capital
    cumulative.name = "SPY"
    return cumulative


VIX_HISTORY_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"


def fetch_vix(start: str, end: str, use_cache: bool = True) -> pd.Series:
    """
    Daily VIX closes from CBOE's public history file (30-day SPX implied
    vol, in vol points, e.g. 16.5). Cached to data_cache/ like Alpaca data;
    pass use_cache=False to force a refresh (live usage).
    """
    import urllib.request

    cache_path = os.path.join(DATA_CACHE_DIR, "vix_history_cboe.csv")
    if not (use_cache and os.path.exists(cache_path)):
        os.makedirs(DATA_CACHE_DIR, exist_ok=True)
        with urllib.request.urlopen(VIX_HISTORY_URL, timeout=30) as resp:
            raw = resp.read()
        with open(cache_path, "wb") as f:
            f.write(raw)

    df = pd.read_csv(cache_path)
    df["DATE"] = pd.to_datetime(df["DATE"], format="%m/%d/%Y")
    vix = df.set_index("DATE")["CLOSE"].sort_index()
    vix.name = "VIX"
    return vix.loc[start:end]


def fetch_tbill(start: str, end: str, initial_capital: float) -> tuple:
    """
    Risk-free rate using BIL (SPDR Bloomberg 1-3 Month T-Bill ETF).

    Returns
    -------
    daily_rate : pd.Series — daily return of BIL (≈ daily T-bill rate)
    cumulative : pd.Series — BIL value index starting at initial_capital
    """
    df         = fetch_bars("BIL", start, end, "1Day", cache_dir=DATA_CACHE_DIR)
    daily_rate = df["close"].pct_change().fillna(0)
    daily_rate.name = "BIL"

    cumulative      = (1 + daily_rate).cumprod() * initial_capital
    cumulative.name = "T-bill (BIL)"

    return daily_rate, cumulative
