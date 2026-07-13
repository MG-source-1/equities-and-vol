"""
Tech-Tier Momentum Ladder — strategy-specific parameters.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from config import START_DATE, END_DATE, INITIAL_CAPITAL, OUTPUT_DIR, DATA_CACHE_DIR  # noqa: F401

# ── Ranked universe ───────────────────────────────────────────
# Each month, hold the single highest-momentum asset.
# When momentum is negative across all three: hold cash (BIL).
TICKERS = {
    "SOXX": "iShares Semiconductor ETF  (~550% 2016-2024)",
    "QQQ":  "Invesco Nasdaq-100 ETF     (~380% 2016-2024)",
    "SPY":  "SPDR S&P 500 ETF           (~237% 2016-2024, benchmark)",
}
CASH_TICKER   = "BIL"   # cash earns T-bill rate when no asset qualifies

# ── Signal ────────────────────────────────────────────────────
# Standard 12-1 month momentum (Jegadeesh & Titman 1993):
#   rank by return from 12 months ago to 1 month ago.
# Skip the most recent month to avoid short-term reversal noise.
LOOKBACK_MONTHS = 12
SKIP_MONTHS     = 1

# ── Risk management ───────────────────────────────────────────
DRAWDOWN_STOP    = 0.15    # 15% drawdown → cash for 21 days (wider than intraday — equity-like)
TRANSACTION_COST = 0.001   # 10 bps per trade
