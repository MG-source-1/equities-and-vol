"""
Live paper-trading configuration.

The live system trades the investor portfolio (45% GARP · 45% TRIAD ·
10% T-bills) on the Alpaca PAPER account daily. It never touches a
real-money endpoint.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config import ROOT_DIR, DATA_CACHE_DIR  # noqa: F401

# ── Endpoints ─────────────────────────────────────────────────
# Trading API (paper). Market data still comes from data.alpaca.markets
# via core/alpaca.py.
PAPER_BASE_URL = "https://paper-api.alpaca.markets"

# ── Sleeve allocation (kept in sync with the backtested portfolio) ─
from strategies.combined_portfolio.config import (   # noqa: E402
    WEIGHT_GARP, WEIGHT_TRIAD, WEIGHT_TBILL, TBILL_TICKER,
)

# ── Signal data window ────────────────────────────────────────
# Longest warm-up requirement is GARP's 12m momentum + 1m skip + month-end
# grid (~13 months). 3 years gives every signal full history with margin.
DATA_YEARS = 3

# ── Execution ─────────────────────────────────────────────────
# Orders are market-on-close (time_in_force="cls") so live fills match the
# backtest's trade-at-the-close assumption. Alpaca's MOC submission cutoff
# is 15:45 ET — run the rebalance job between ~15:20 and 15:40 ET.
MIN_TRADE_VALUE   = 200.0    # skip rebalance trades smaller than this ($)
MOC_CUTOFF_ET     = "15:45"  # informational — enforced by Alpaca

# ── Portfolio-level drawdown guard ────────────────────────────
# The backtest applies drawdown stops per sleeve; live applies one guard at
# the account level (a documented deviation — see README). Matches GARP's
# stop parameters.
DD_STOP           = 0.15     # flatten if live equity falls 15% from its peak
DD_COOLDOWN_DAYS  = 21       # stay in cash this many trading days

# ── EDGAR freshness ───────────────────────────────────────────
# Backtest caches are permanent; live refreshes fundamentals weekly so new
# 10-Q/10-K filings flow into the GARP score.
EDGAR_REFRESH_DAYS = 7

# ── State and logs ────────────────────────────────────────────
LIVE_DIR      = os.path.join(ROOT_DIR, "outputs", "live")
DECISIONS_DIR = os.path.join(LIVE_DIR, "decisions")
STATE_PATH    = os.path.join(LIVE_DIR, "state.json")
EQUITY_CSV    = os.path.join(LIVE_DIR, "equity_curve.csv")
