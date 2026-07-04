"""
Shared Alpaca Market Data API utilities.

Used by:
  core/data.py                                  — daily bars
  strategies/spy_intraday_short/data_intraday.py — 5-minute bars

Handles credential loading, authentication, paginated requests, and disk caching.
All timestamps are converted from UTC to US/Eastern (tz-naive) so that
09:30 always means market open regardless of DST.
"""

import os
import time
import json
import urllib.request
import urllib.parse
import pandas as pd


# ── Credentials ───────────────────────────────────────────────

def load_env() -> None:
    """Walk up the directory tree to find .env and load into os.environ."""
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        candidate = os.path.join(here, ".env")
        if os.path.exists(candidate):
            with open(candidate) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            return
        here = os.path.dirname(here)


def get_headers() -> dict:
    load_env()
    key    = os.getenv("ALPACA_KEY", "")
    secret = os.getenv("ALPACA_SECRET", "")
    if not key or key == "your-key-id-here":
        raise ValueError("ALPACA_KEY not set in .env")
    if not secret or secret == "your-secret-here":
        raise ValueError("ALPACA_SECRET not set in .env")
    return {
        "APCA-API-KEY-ID":     key,
        "APCA-API-SECRET-KEY": secret,
    }


# ── Bar fetching ──────────────────────────────────────────────

def fetch_bars(
    symbol: str,
    start: str,
    end: str,
    timeframe: str = "1Day",
    feed: str = "sip",
    adjustment: str = "all",   # "all" = split + dividend → total return prices
    cache_dir: str = "data_cache",
    verbose: bool = True,
    use_cache: bool = True,    # False = always fetch fresh, never read/write cache (live trading)
) -> pd.DataFrame:
    """
    Fetches historical OHLCV bars from Alpaca for any timeframe.
    Caches results to disk so the API is only called once per
    (symbol, timeframe, start, end) combination.

    Returns a DataFrame with a tz-naive US/Eastern DatetimeIndex and
    columns: open, high, low, close, volume.
    For daily bars the index is normalised to midnight (date only).
    """
    os.makedirs(cache_dir, exist_ok=True)
    # Include adjustment in filename so split-adjusted and total-return caches don't clash
    cache = os.path.join(cache_dir, f"{symbol}_{timeframe}_{adjustment}_{start}_{end}.csv")

    if use_cache and os.path.exists(cache):
        if verbose:
            print(f"[data] {symbol} {timeframe} loaded from cache.")
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df

    if verbose:
        print(f"[data] Downloading {symbol} {timeframe} from Alpaca …")

    headers    = get_headers()
    url        = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
    all_bars   = []
    page_token = None

    while True:
        params = {
            "start":      start,
            "end":        end,
            "timeframe":  timeframe,
            "adjustment": adjustment,
            "feed":       feed,
            "limit":      10000,
        }
        if page_token:
            params["page_token"] = page_token

        full_url = url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(full_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())

        batch = body.get("bars", [])
        all_bars.extend(batch)
        if verbose and len(all_bars) % 50000 == 0 and len(all_bars) > 0:
            print(f"  … {len(all_bars):,} bars", end="\r")

        page_token = body.get("next_page_token")
        if not page_token:
            break
        time.sleep(0.2)

    if verbose:
        print(f"  {len(all_bars):,} bars downloaded.")

    df = pd.DataFrame(all_bars)
    df = df.rename(columns={
        "t": "datetime", "o": "open", "h": "high",
        "l": "low",      "c": "close", "v": "volume",
    })
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.set_index("datetime")
    df.index = df.index.tz_convert("America/New_York").tz_localize(None)

    # For daily bars: normalise to midnight (strip the time component)
    if timeframe in ("1Day", "1d"):
        df.index = df.index.normalize()

    df = df[["open", "high", "low", "close", "volume"]]
    if use_cache:
        df.to_csv(cache)
        if verbose:
            print(f"[data] Cached → {cache}")
    return df
