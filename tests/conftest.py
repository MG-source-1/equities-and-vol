"""
Shared fixtures — load cached market data once per test session.

Tests run entirely from data_cache/ (no network): if the cache is missing
(fresh clone, CI), the data-dependent tests skip rather than fail. Run any
strategy main once to populate the cache.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import START_DATE, END_DATE, DATA_CACHE_DIR  # noqa: E402


def _cached(func, *args, **kwargs):
    """Call a fetch function; skip the test if its cache isn't on disk."""
    try:
        out = func(*args, **kwargs)
    except Exception as e:                       # no cache AND no network/keys
        pytest.skip(f"data unavailable ({e})")
    if hasattr(out, "empty") and out.empty:
        pytest.skip("data cache empty")
    return out


@pytest.fixture(scope="session")
def tmt_closes():
    """Daily closes for the 15-stock TMT universe + SPY, 2016–2024."""
    from core.data import fetch_prices
    from strategies.equities.garp_momentum.config import TICKERS
    return _cached(fetch_prices, TICKERS + ["SPY"], START_DATE, END_DATE)


@pytest.fixture(scope="session")
def tmt_bars():
    """OHLC bars for the TMT universe (TRIAD's input), 2016–2024."""
    from core.alpaca import fetch_bars
    from strategies.equities.triad import config as tc
    bars = {}
    for t in tc.TICKERS:
        bars[t] = _cached(fetch_bars, t, START_DATE, END_DATE, "1Day",
                          cache_dir=DATA_CACHE_DIR, verbose=False)
    return bars


@pytest.fixture(scope="session")
def qqq_bars():
    from core.alpaca import fetch_bars
    return _cached(fetch_bars, "QQQ", START_DATE, END_DATE, "1Day",
                   cache_dir=DATA_CACHE_DIR, verbose=False)


@pytest.fixture(scope="session")
def factor_prices():
    """AFP's four factor ETFs, 2016–2024."""
    from core.data import fetch_prices
    return _cached(fetch_prices, ["QQQ", "QUAL", "MTUM", "USMV"],
                   START_DATE, END_DATE)


@pytest.fixture(scope="session")
def btrend_prices():
    """BTREND's 17-ETF universe over its own (extended) window."""
    from core.data import fetch_prices
    from strategies.cross_asset.broad_trend import config as bt
    return _cached(fetch_prices, list(bt.TICKERS), bt.START_DATE, bt.END_DATE)


@pytest.fixture(scope="session")
def tbill_rate():
    from core.data import fetch_tbill
    rate, _ = _cached(lambda *a: fetch_tbill(*a), START_DATE, END_DATE, 100_000)
    return rate
