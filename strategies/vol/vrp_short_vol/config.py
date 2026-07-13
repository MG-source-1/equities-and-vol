"""
VRP — Volatility Risk Premium — strategy parameters.

The classic equity-derivatives trade: implied vol persistently trades above
subsequently-realised vol (the VRP), because option sellers demand a
premium for carrying gamma risk through jumps. This strategy sells that
premium — short 25-delta SPY strangles when implied is rich to realised —
and manages it the way a desk would: vega-budgeted sizing, daily delta
hedging, a hard premium-multiple stop, and greeks-attributed P&L.

Pricing model honesty: with no free historical option chains, options are
priced synthetically — Black-Scholes with the VIX (CBOE official history)
as the implied vol for both legs. That means a FLAT skew and FLAT term
structure. Flat skew misprices the put wing cheap, which UNDERSTATES the
premium collected by real-world put sellers — the simplification is
conservative for a short-vol book, not flattering. All entry/exit/greeks
math is unaffected.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
from config import INITIAL_CAPITAL, OUTPUT_DIR, DATA_CACHE_DIR  # noqa: F401

# VIX history covers the full window; extend past the shared END_DATE so
# the strategy sees Volmageddon (2018), COVID (2020), GameStop (2021) AND
# the recent out-of-window regime.
START_DATE = "2016-01-01"
END_DATE   = "2026-06-30"

# ── Instrument ────────────────────────────────────────────────
UNDERLYING     = "SPY"    # VIX measures 30-day SPX implied vol; SPY ≈ SPX/10
DIV_YIELD      = 0.013    # SPY continuous dividend yield (approx, constant)
CONTRACT_MULT  = 100      # shares per option contract

# ── Position structure (monthly roll cycle) ───────────────────
# At each month-end close: settle anything expiring, then — if the signal
# is on — sell a new strangle expiring at the next month-end.
DELTA_TARGET   = 0.25     # short the 25-delta call and 25-delta put

# ── Signal ────────────────────────────────────────────────────
# VRP = VIX − EWMA realised vol (RiskMetrics λ=0.94), in vol points.
# Sell only when implied is meaningfully rich to realised.
EWMA_LAMBDA    = 0.94
VRP_ENTRY      = 1.0      # vol points of IV-RV spread required to sell

# ── Risk management ───────────────────────────────────────────
VEGA_BUDGET    = 0.005    # short vega sized to the STRESS case, not the
                          # average day: at 0.5% equity per vol point, a
                          # COVID-scale +50pt VIX shock marks ≈ −25% before
                          # gamma. (At 1% it backtests near-double the
                          # return — and −49% through March 2020.)
STOP_MULT      = 3.0      # hard stop: buy back if the strangle marks at 3×
                          # the premium received (desk-standard loss limit)
DELTA_HEDGE    = True     # flatten book delta daily with underlying shares

# ── Frictions ─────────────────────────────────────────────────
HALF_SPREAD_VOLPTS = 0.5  # options cross half the spread ≈ 0.5 vol pt per
                          # leg per transaction (charged via leg vega)
HEDGE_COST_BPS     = 1.0  # underlying hedge trades pay 1 bp of notional
