"""
Investor Portfolio — capital allocation config.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from config import START_DATE, END_DATE, INITIAL_CAPITAL, OUTPUT_DIR, DATA_CACHE_DIR  # noqa: F401

# ── Allocation weights ────────────────────────────────────────
WEIGHT_AFP = 0.50   # Adaptive Factor Portfolio  (equity factors, Sharpe 0.97)
WEIGHT_XAT = 0.30   # Cross-Asset Trend          (SPY · TLT · GLD)
WEIGHT_SIS = 0.20   # SPY Intraday Short          (market-neutral alpha)

# ── Cross-asset universe ──────────────────────────────────────
XAT_TICKERS = {
    "SPY": "SPDR S&P 500 ETF",
    "TLT": "iShares 20+ Year Treasury Bond",
    "GLD": "SPDR Gold Shares",
}
