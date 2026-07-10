"""
Execution-timing convention test on synthetic data.

The repo-wide convention: a signal decided at the close of day D is entered
at that close and earns the return of D → D+1. Two failure modes bracket it:

  • Lookahead — the position somehow earns (or dodges) the return ending
    on D itself, i.e. it reacted to data before the decision was possible.
  • Lag — the position only starts earning from D+2 (the TRIAD Leaders
    double-shift bug fixed in July 2026).

Setup: one steadily up-trending asset, so the strategy is long after
warmup. Build two price panels that are IDENTICAL through a month-end
decision day D, then diverge: one crashes −10% on D+1. Assertions:

  1. Strategy P&L is identical through D (no lookahead — the future
     divergence cannot leak backwards).
  2. The crash-panel P&L on D+1 is deeply negative (the position decided
     at D's close was held over D → D+1 — no lag).
"""

import types

import numpy as np
import pandas as pd


def _make_cfg():
    return types.SimpleNamespace(
        LOOKBACK_DAYS=[63, 126, 252],
        ASSET_VOL_LOOKBACK=60,
        MAX_WEIGHT=0.20,
        TARGET_VOL=0.10,
        VOL_LOOKBACK=20,
        MAX_LEVERAGE=1.0,
        LONG_SHORT=True,
        TRANSACTION_COST=0.0,     # isolate timing from cost effects
    )


def test_decision_enters_at_decision_close():
    from strategies.broad_trend.backtest import run_trend_backtest, _month_end_dates

    dates = pd.bdate_range("2020-01-01", periods=460)
    up = 100 * (1.001) ** np.arange(len(dates))          # +0.1%/day, mom > 0
    base = pd.DataFrame({"UP": up}, index=dates)

    # Pick a month-end decision day D well past the 13-month warmup,
    # with the crash on the next trading day.
    month_ends = _month_end_dates(dates)
    D = [d for d in month_ends if d > dates[380]][0]
    d_next = dates[dates.get_loc(D) + 1]

    crash = base.copy()
    crash.loc[d_next:, "UP"] *= 0.90                     # −10% on D+1 only

    tbill = pd.Series(0.0, index=dates)
    cfg = _make_cfg()
    pf_base  = run_trend_backtest(base, tbill, 100_000, cfg)
    pf_crash = run_trend_backtest(crash, tbill, 100_000, cfg)

    # 1) No lookahead: everything through D is identical.
    pd.testing.assert_series_equal(
        pf_base.loc[:D, "daily_return"], pf_crash.loc[:D, "daily_return"],
        rtol=1e-12, atol=1e-14)

    # 2) No lag: the position decided at D's close eats the D+1 crash.
    w = cfg.MAX_WEIGHT                                   # single asset, capped
    crash_day = pf_crash.loc[d_next, "daily_return"]
    base_day  = pf_base.loc[d_next, "daily_return"]
    assert crash_day < -0.5 * 0.10 * w, (
        f"crash-day return {crash_day:.4%} too small — position entered late?")
    assert abs(base_day) < 0.001                          # sanity: calm without crash
