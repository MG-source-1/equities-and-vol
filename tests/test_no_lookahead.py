"""
No-lookahead property tests. Two complementary properties per engine:

1. TRUNCATION — compute weights on full history, recompute with the last
   40 days removed, assert all surviving rows are identical. Catches
   dependence on data beyond day t (e.g. full-sample normalisation).

2. LAST-DAY PERTURBATION — bump the final day's prices by 5%, recompute,
   assert the weights that were already decided do not move. This catches
   the subtler off-by-one class actually fixed in July 2026: a position
   entered at the close of t-1 whose size used data from day t. A
   truncation test cannot see that bug; this one fails on it immediately.

The perturbation assertion depends on each engine's entry convention:
  "prev"  — weights row t is entered at t-1's close (AFP/XAT, BTREND,
            TRIAD Leaders): perturbing day T must leave ALL rows ≤ T
            unchanged, including row T itself.
  "same"  — weights row t is the signal at t's own close, shifted by the
            runner before earning (TRIAD dips, DTQ): row T may legitimately
            react to day T's bar; rows ≤ T-1 must be unchanged.

All comparisons are exact: the same causal computation on the same data
prefix must be bit-for-bit reproducible.
"""

import pandas as pd
import pytest

TRUNC = 40   # trading days to cut — spans a month-end boundary
BUMP  = 1.05


def _eq(a, b):
    if isinstance(a, pd.Series):
        pd.testing.assert_series_equal(a, b, rtol=1e-12, atol=1e-14)
    else:
        pd.testing.assert_frame_equal(a, b, rtol=1e-12, atol=1e-14)


def _check(run, data, convention, perturb, truncate):
    """Run both properties for one engine.

    run        — data -> weights (DataFrame or Series, indexed like data)
    perturb    — data -> copy with only the FINAL day's prices bumped
    truncate   — data -> copy with the last TRUNC days removed
    """
    full = run(data)

    # 1) Truncation
    cut = run(truncate(data))
    _eq(full.loc[:cut.index[-1]], cut)

    # 2) Last-day perturbation
    bumped = run(perturb(data))
    T = full.index[-1]
    if convention == "prev":
        _eq(full, bumped)                       # nothing may move, even row T
    else:  # "same"
        _eq(full.loc[:full.index[-2]], bumped.loc[:bumped.index[-2]])


# ── helpers for the two data shapes ───────────────────────────

def _bump_last_frame(px: pd.DataFrame) -> pd.DataFrame:
    out = px.copy()
    out.iloc[-1] = out.iloc[-1] * BUMP
    return out


def _bump_last_bars(bars: pd.DataFrame) -> pd.DataFrame:
    out = bars.copy()
    for col in ("open", "high", "low", "close"):
        if col in out.columns:
            out.iloc[-1, out.columns.get_loc(col)] *= BUMP
    return out


# ── TRIAD ─────────────────────────────────────────────────────

def test_triad_leaders(tmt_bars, qqq_bars):
    from strategies.triad.backtest import compute_leader_weights
    from strategies.triad import config as cfg

    calendar = qqq_bars.index
    closes = pd.DataFrame({t: b["close"].reindex(calendar)
                           for t, b in tmt_bars.items()}).ffill()
    idx = qqq_bars["close"]

    def run(pair):
        c, i = pair
        return compute_leader_weights(
            c, i, cfg.LOOKBACK_DAYS, cfg.TOP_N, cfg.LEADERS_TARGET_VOL,
            cfg.REGIME_FLOOR, cfg.SMA_WINDOW, cfg.VOL_LOOKBACK)

    _check(run, (closes, idx), "prev",
           perturb=lambda p: (_bump_last_frame(p[0]),
                              _bump_last_frame(p[1].to_frame()).iloc[:, 0]),
           truncate=lambda p: (p[0].iloc[:-TRUNC], p[1].iloc[:-TRUNC]))


def test_triad_stock_dips(tmt_bars, qqq_bars):
    from strategies.triad.backtest import compute_stock_dip_weights
    from strategies.triad import config as cfg

    calendar = qqq_bars.index

    def run(pair):
        bars, cal = pair
        return compute_stock_dip_weights(
            bars, cal, cfg.DIP_ENTRY_IBS, cfg.DIP_EXIT_IBS, cfg.DIP_MAX_HOLD,
            cfg.SMA_WINDOW, cfg.DIP_MOM_DAYS, cfg.DIP_PER_NAME,
            cfg.DIP_MAX_GROSS)

    _check(run, (tmt_bars, calendar), "same",
           perturb=lambda p: ({t: _bump_last_bars(b) for t, b in p[0].items()},
                              p[1]),
           truncate=lambda p: ({t: b.iloc[:-TRUNC] for t, b in p[0].items()},
                               p[1][:-TRUNC]))


def test_triad_index_dips(qqq_bars):
    from strategies.triad.backtest import compute_index_dip_weights
    from strategies.triad import config as cfg

    def run(bars):
        return compute_index_dip_weights(
            bars, cfg.IDX_ENTRY_IBS, cfg.IDX_EXIT_IBS, cfg.IDX_MAX_HOLD,
            cfg.SMA_WINDOW, cfg.IDX_TARGET_VOL, cfg.VOL_LOOKBACK,
            cfg.IDX_MAX_SIZE)

    _check(run, qqq_bars, "same",
           perturb=_bump_last_bars, truncate=lambda b: b.iloc[:-TRUNC])


# ── AFP / XAT (shared engine) ─────────────────────────────────

def test_factor_weights(factor_prices):
    from strategies.equity_factor_rotation.backtest import get_factor_weights
    from strategies.equity_factor_rotation import config as cfg

    def run(px):
        return get_factor_weights(
            px, cfg.LOOKBACK_MONTHS, cfg.RANK_TILT,
            cfg.CORR_WINDOW, cfg.CORR_HIGH, cfg.CORR_MID,
            cfg.TARGET_VOL, cfg.MAX_WEIGHT, cfg.MAX_LEVERAGE,
            cfg.VOL_LOOKBACK)

    _check(run, factor_prices, "prev",
           perturb=_bump_last_frame, truncate=lambda p: p.iloc[:-TRUNC])


# ── BTREND ────────────────────────────────────────────────────

def test_btrend_weights(btrend_prices):
    from strategies.broad_trend.backtest import compute_trend_weights
    from strategies.broad_trend import config as cfg

    def run(px):
        return compute_trend_weights(
            px, cfg.LOOKBACK_DAYS, cfg.ASSET_VOL_LOOKBACK, cfg.MAX_WEIGHT,
            cfg.TARGET_VOL, cfg.VOL_LOOKBACK, cfg.MAX_LEVERAGE,
            long_short=cfg.LONG_SHORT)

    _check(run, btrend_prices, "prev",
           perturb=_bump_last_frame, truncate=lambda p: p.iloc[:-TRUNC])


# ── DTQ ───────────────────────────────────────────────────────

def test_dtq_trend_sleeve(qqq_bars):
    from strategies.dual_timescale_qqq.backtest import compute_trend_weights
    from strategies.dual_timescale_qqq import config as cfg

    def run(bars):
        return compute_trend_weights(
            bars, cfg.SMA_WINDOW, cfg.TREND_TARGET_VOL, cfg.VOL_LOOKBACK,
            cfg.TREND_MAX_SIZE)

    _check(run, qqq_bars, "same",
           perturb=_bump_last_bars, truncate=lambda b: b.iloc[:-TRUNC])


def test_dtq_mr_sleeve(qqq_bars):
    from strategies.dual_timescale_qqq.backtest import compute_mr_weights
    from strategies.dual_timescale_qqq import config as cfg

    def run(bars):
        return compute_mr_weights(
            bars, cfg.MR_ENTRY_IBS, cfg.MR_EXIT_IBS, cfg.MR_MAX_HOLD,
            cfg.SMA_WINDOW, cfg.MR_TARGET_VOL, cfg.VOL_LOOKBACK,
            cfg.MR_MAX_SIZE)[0]

    _check(run, qqq_bars, "same",
           perturb=_bump_last_bars, truncate=lambda b: b.iloc[:-TRUNC])


# ── GARP (monthly decision dict) ──────────────────────────────

def test_garp_monthly_weights(tmt_closes):
    """GARP returns {rebalance_date: weights}. Decisions made strictly
    before the truncation/perturbation point must be identical. GARP
    scores are held static to isolate the price-signal path from the
    EDGAR cache."""
    from strategies.garp_momentum.backtest import _compute_monthly_weights
    from strategies.garp_momentum import config as cfg

    prices = tmt_closes[[t for t in cfg.TICKERS if t in tmt_closes.columns]]
    spy    = tmt_closes["SPY"]
    static = pd.Series(0.5, index=prices.columns)   # neutral quality score

    def run(px, sp):
        return _compute_monthly_weights(
            px, static, sp, cfg.TOP_N, cfg.LOOKBACK_MONTHS, cfg.SKIP_MONTHS,
            cfg.GARP_WEIGHT, cfg.MOM_WEIGHT, cfg.MAX_WEIGHT)

    w_full, s_full = run(prices, spy)

    # Truncation: complete-month decisions common to both runs identical
    w_cut, s_cut = run(prices.iloc[:-TRUNC], spy.iloc[:-TRUNC])
    common = sorted(set(list(w_full)[:-1]) & set(list(w_cut)[:-1]))
    assert len(common) > 90
    for d in common:
        _eq(w_full[d], w_cut[d])
        assert s_full[d] == s_cut[d]

    # Perturbation: bump the final day; all decisions before it unchanged
    w_bump, s_bump = run(_bump_last_frame(prices), _bump_last_frame(
        spy.to_frame()).iloc[:, 0])
    T = prices.index[-1]
    for d in [d for d in w_full if d < T]:
        _eq(w_full[d], w_bump[d])
        assert s_full[d] == s_bump[d]
