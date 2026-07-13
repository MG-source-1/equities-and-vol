"""
5-minute bar fetcher for the SPY intraday strategy.

Thin wrapper around core.alpaca.fetch_bars that:
  1. Defaults to the SIP feed and the shared data_cache directory.
  2. Filters results to regular trading hours (09:30–16:00 ET).

All Alpaca auth, pagination, and caching logic lives in core/alpaca.py.
"""

import sys
import os
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
if os.path.abspath(ROOT) not in sys.path:
    sys.path.insert(0, os.path.abspath(ROOT))

from core.alpaca import fetch_bars as _fetch_bars
from config import DATA_CACHE_DIR


def fetch_bars(
    symbol: str,
    start: str,
    end: str,
    timeframe: str = "5Min",
    cache_dir: str = None,
) -> "pd.DataFrame":
    """
    Returns 5-minute OHLCV bars filtered to regular trading hours.
    Results are cached in data_cache/ so Alpaca is only called once.
    """
    import pandas as pd

    if cache_dir is None:
        cache_dir = DATA_CACHE_DIR

    df = _fetch_bars(symbol, start, end, timeframe,
                     feed="sip", cache_dir=cache_dir)

    # Keep only regular session (09:30–16:00 ET) for intraday bars
    if timeframe not in ("1Day", "1d"):
        df = df.between_time("09:30", "16:00")

    return df
