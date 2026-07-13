"""
Dual-Timescale QQQ (DTQ) — strategy-specific parameters.

Two sleeves on the same instrument, at opposite timescales:
  Trend sleeve — slow (months): long QQQ while it trades above its 200-day SMA
  MR sleeve    — fast (days):   buys 1-3 day panic dips (low IBS) inside uptrends

Parameters are deliberately standard values from the literature (200-day SMA,
IBS 0.10/0.75, 3-day hold) rather than optimised numbers — see the robustness
grid in the README.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from config import START_DATE, END_DATE, INITIAL_CAPITAL, OUTPUT_DIR, DATA_CACHE_DIR  # noqa: F401

# ── Instrument ────────────────────────────────────────────────
TICKER           = "QQQ"     # Nasdaq-100 — the mean-reversion signal is much
                             # stronger here than on SPY (tested: SPY MR Sharpe ≈ 0)

# ── Sleeve capital split ──────────────────────────────────────
TREND_WEIGHT     = 0.50      # slow sleeve
MR_WEIGHT        = 0.50      # fast sleeve

# ── Trend sleeve (slow) ───────────────────────────────────────
SMA_WINDOW       = 200       # classic long-term trend filter
TREND_TARGET_VOL = 0.15      # 15% annualised vol target on the sleeve
TREND_MAX_SIZE   = 1.0       # never levered

# ── Mean-reversion sleeve (fast) ──────────────────────────────
# IBS = (close - low) / (high - low): where today closed within its own range.
# IBS < 0.10 = closed in the bottom decile of the day's range (panic close).
MR_ENTRY_IBS     = 0.10      # enter when IBS < this AND price > 200-day SMA
MR_EXIT_IBS      = 0.75      # exit when the close is back in the top quartile
MR_MAX_HOLD      = 3         # or after 3 days, whichever comes first
MR_TARGET_VOL    = 0.20      # dip positions sized to 20% annualised vol
MR_MAX_SIZE      = 1.5       # per-trade sleeve exposure cap

# ── Common ────────────────────────────────────────────────────
VOL_LOOKBACK     = 20        # days of realised vol for position sizing
TRANSACTION_COST = 0.001     # 10 bps per unit turnover (matches other strategies)
