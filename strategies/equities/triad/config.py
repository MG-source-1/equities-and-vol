"""
TRIAD — Tri-Timescale TMT — strategy-specific parameters.

Three long-only sleeves on the same TMT universe, at three timescales:
  Leaders sleeve — months:  top-3 momentum concentration, vol-targeted
  Stock-dip sleeve — days:  buy IBS panic closes in uptrending names
  Index-dip sleeve — days:  DTQ's QQQ mean-reversion sleeve (index level)

The sleeves share one factor (TMT beta) but harvest it through three
behaviours — continuation, single-name overreaction, index overreaction —
whose daily P&L correlations are 0.33-0.56, which is what lifts the
combined Sharpe above any sleeve alone.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from config import START_DATE, INITIAL_CAPITAL, OUTPUT_DIR, DATA_CACHE_DIR  # noqa: F401

# TRIAD extends past the shared END_DATE (2024-12-31): the strategy was
# developed with parameters frozen on 2016-2024 data, and 2025-01 → 2026-06
# serves as its out-of-sample validation window (see README).
END_DATE = "2026-06-30"

# ── Universe: same 15 TMT names as GARP Momentum ──────────────
TICKERS = ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMD", "AVGO", "QCOM",
           "ORCL", "CRM", "ADBE", "NFLX", "AMZN", "TSLA", "INTC"]
INDEX_TICKER      = "QQQ"

# ── Sleeve capital split ──────────────────────────────────────
LEADERS_WEIGHT    = 0.60     # slow engine — where the return comes from
STOCK_DIP_WEIGHT  = 0.25     # fast engine — single-name panic harvesting
INDEX_DIP_WEIGHT  = 0.15     # fast engine — index panic harvesting (from DTQ)

# ── Leaders sleeve (months) ───────────────────────────────────
LOOKBACK_DAYS     = [63, 126, 252]   # 3m / 6m / 12m momentum blend (GARP convention)
TOP_N             = 3                # hold the 3 strongest names
LEADERS_TARGET_VOL = 0.25            # sleeve-level annualised vol target
REGIME_FLOOR      = 0.3              # exposure multiplier when QQQ < 200d SMA
SMA_WINDOW        = 200

# ── Stock-dip sleeve (days) ───────────────────────────────────
# Entry: IBS < 0.10 (close pinned to the bottom decile of the day's range)
# AND price > 200d SMA AND 6-month momentum > 0 — panic inside an uptrend.
DIP_ENTRY_IBS     = 0.10
DIP_EXIT_IBS      = 0.75
DIP_MAX_HOLD      = 3
DIP_PER_NAME      = 0.25     # each active dip gets 25% of the sleeve
DIP_MAX_GROSS     = 1.00     # sleeve never levered
DIP_MOM_DAYS      = 126      # 6-month momentum qualifier

# ── Index-dip sleeve (days) — identical to DTQ's MR sleeve ────
IDX_ENTRY_IBS     = 0.10
IDX_EXIT_IBS      = 0.75
IDX_MAX_HOLD      = 3
IDX_TARGET_VOL    = 0.20
IDX_MAX_SIZE      = 1.5

# ── Common ────────────────────────────────────────────────────
VOL_LOOKBACK      = 20
TRANSACTION_COST  = 0.001    # 10 bps per unit turnover
