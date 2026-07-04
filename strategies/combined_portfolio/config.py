"""
Investor Portfolio — capital allocation config.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from config import START_DATE, END_DATE, INITIAL_CAPITAL, OUTPUT_DIR, DATA_CACHE_DIR  # noqa: F401

# ── Allocation weights ────────────────────────────────────────
# SIS removed from the live portfolio — it requires 5-min intraday data
# only available from 2020, which would shorten the backtest window by 4 years.
# SIS is retained as a reference strategy.
#
# 2026-07 revision: GARP's 80% split into 40% GARP + 40% TRIAD after TRIAD's
# 18-month out-of-sample validation (see README). The two engines trade the
# same TMT universe but select differently — fundamental quality vs pure
# momentum + panic dips — so the split diversifies MODEL risk, not market
# risk. A full swap to TRIAD backtests better still, but retiring a proven
# fundamentals engine on one in-sample comparison would be overfitting the
# research process itself.
WEIGHT_GARP  = 0.40   # Alpha engine 1 — fundamental quality (EDGAR) + momentum
WEIGHT_TRIAD = 0.40   # Alpha engine 2 — tri-timescale momentum + dip harvesting
WEIGHT_XAT   = 0.20   # Cross-asset trend — regime diversifier

# ── Cross-asset rotation universe ─────────────────────────────
XAT_TICKERS = {
    "SPY": "SPDR S&P 500 ETF",
    "TLT": "iShares 20+ Year Treasury Bond",
    "GLD": "SPDR Gold Shares",
}
