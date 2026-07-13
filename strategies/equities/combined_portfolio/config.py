"""
Investor Portfolio — capital allocation config.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
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
#
# 2026-07 revision 2: the 20% XAT sleeve replaced with 10% T-bills (BIL),
# freeing 5% each to GARP/TRIAD. Under the daily-rebalanced constant mix,
# T-bills strictly dominated XAT at every weight tested — more return, equal
# or better Sharpe, smaller drawdown, including in the COVID and 2022
# crisis episodes XAT was meant to defend. XAT is retained as a reference
# strategy (equity_factor_rotation engine on SPY/TLT/GLD — see README).
# The T-bill sleeve is held as an actual BIL position live, matching the
# backtest's assumption that the sleeve earns the BIL return.
WEIGHT_GARP  = 0.45   # Alpha engine 1 — fundamental quality (EDGAR) + momentum
WEIGHT_TRIAD = 0.45   # Alpha engine 2 — tri-timescale momentum + dip harvesting
WEIGHT_TBILL = 0.10   # T-bills (BIL) — dry powder; both alpha engines share one TMT regime bet

TBILL_TICKER = "BIL"  # SPDR Bloomberg 1-3 Month T-Bill ETF
