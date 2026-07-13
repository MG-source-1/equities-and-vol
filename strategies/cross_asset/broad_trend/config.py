"""
BTREND — Broad Cross-Asset Trend — strategy parameters.

The diversifier XAT should have been: per-asset LONG/SHORT time-series
momentum (Moskowitz-Ooi-Pedersen 2012) over a BROAD universe — 17 ETFs
across five asset classes — instead of a 3-asset long-only rank rotation.
Each asset is judged on its own trend, so the sleeve can be long bonds and
gold while SHORT equities and the yen; XAT could only hold its single
leader or cash.

Design discipline: every parameter is a standard literature value shared
with the rest of the repo (3/6/12m momentum blend, 10 bps costs). Nothing
was optimised on the backtest window — the strategy was built to test a
hypothesis (was XAT's failure about trend, or about its implementation?),
and an optimised version couldn't answer it. Findings (see README research
log): breadth alone is NOT the answer — the long-only variant is dominated
by T-bills, like XAT. The shorts are the answer: the long/short variant is
the first diversifier tested that T-bills do not dominate, and it made
money in both COVID and the 2022 rate shock.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from config import START_DATE, INITIAL_CAPITAL, OUTPUT_DIR, DATA_CACHE_DIR  # noqa: F401

# Like TRIAD, BTREND extends past the shared END_DATE: its parameters are
# untuned literature values, so 2025-01 → 2026-06 serves as a forward
# validation window (see README research log).
END_DATE = "2026-06-30"

# ── Universe: 17 liquid ETFs across five asset classes ────────
# All available on Alpaca from ~2016. Assets with insufficient history are
# dropped automatically by the data layer; the engine trades what exists.
TICKERS = {
    # US equity
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    # International equity
    "EFA": "Developed ex-US",
    "EEM": "Emerging markets",
    # Real estate
    "VNQ": "US REITs",
    # Bonds / rates
    "TLT": "20+yr Treasuries",
    "IEF": "7-10yr Treasuries",
    "LQD": "IG corporates",
    "HYG": "High yield",
    "TIP": "TIPS",
    # Commodities
    "GLD": "Gold",
    "SLV": "Silver",
    "DBC": "Broad commodities",
    "USO": "Crude oil",
    # Currencies
    "UUP": "US dollar index",
    "FXY": "Japanese yen",
}

# ── Signal (per asset, monthly at month-end close) ────────────
LOOKBACK_DAYS      = [63, 126, 252]  # 3/6/12m blend — repo-wide convention
LONG_SHORT         = True            # long up-trends, SHORT down-trends.
                                     # The shorts are where managed-futures
                                     # crisis convexity lives (2022: short
                                     # bonds). The long-only variant is
                                     # dominated by T-bills — see README.

# ── Sizing ────────────────────────────────────────────────────
ASSET_VOL_LOOKBACK = 60              # days, per-asset vol for inverse-vol weights
MAX_WEIGHT         = 0.20            # per-asset cap; capped excess stays in cash
TARGET_VOL         = 0.10            # portfolio-level annualised vol target
VOL_LOOKBACK       = 20              # days, for the daily vol-target scale
MAX_LEVERAGE       = 1.0             # never levered

# ── Costs ─────────────────────────────────────────────────────
TRANSACTION_COST   = 0.001           # 10 bps per unit turnover
