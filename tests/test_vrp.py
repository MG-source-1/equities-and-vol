"""
VRP engine tests — same discipline as the equity engines, plus the
options-specific invariant: greeks attribution must reconcile with total
P&L exactly (theta + gamma + vega + delta + residual + interest − costs
= equity change), because a risk report whose rows don't sum is worse
than no risk report.
"""

import pandas as pd
import pytest

from config import DATA_CACHE_DIR


@pytest.fixture(scope="module")
def vrp_inputs():
    from core.data import fetch_prices, fetch_tbill, fetch_vix
    from strategies.vrp_short_vol import config as cfg
    try:
        px = fetch_prices([cfg.UNDERLYING], "2018-01-01", "2021-12-31")[cfg.UNDERLYING]
        vix = fetch_vix("2018-01-01", "2021-12-31")
        tbill, _ = fetch_tbill("2018-01-01", "2021-12-31", 100_000)
    except Exception as e:
        pytest.skip(f"data unavailable ({e})")
    if px.empty or vix.empty:
        pytest.skip("data cache empty")
    return px, vix, tbill


@pytest.fixture(scope="module")
def vrp_run(vrp_inputs):
    from strategies.vrp_short_vol.backtest import run_vrp_backtest
    from strategies.vrp_short_vol import config as cfg
    px, vix, tbill = vrp_inputs
    return run_vrp_backtest(px, vix, tbill, 100_000, cfg)


def test_attribution_reconciles_to_the_dollar(vrp_run):
    pf = vrp_run
    total = pf["equity"].iloc[-1] - 100_000
    explained = (pf[["theta_pnl", "gamma_pnl", "vega_pnl", "delta_pnl",
                     "residual_pnl", "interest"]].sum().sum()
                 - pf["costs"].sum())
    assert explained == pytest.approx(total, abs=0.01)


def test_hedged_book_has_no_delta_pnl(vrp_run):
    # daily re-hedge flattens book delta at each close, so next-day
    # attributed delta P&L must be identically zero
    assert vrp_run["delta_pnl"].abs().max() < 1e-6


def test_residual_is_small(vrp_run):
    """The first-order greeks should explain nearly all option P&L; a fat
    residual means the attribution (or the greeks) is wrong. Includes the
    COVID window, so the tolerance is generous but bounded."""
    pf = vrp_run
    gross_moves = pf[["theta_pnl", "gamma_pnl", "vega_pnl"]].abs().sum().sum()
    assert abs(pf["residual_pnl"].sum()) < 0.10 * gross_moves


def test_no_lookahead_truncation(vrp_inputs):
    """Causality: removing the last 40 days must not change any earlier
    equity value (decisions at t use PRICE data through t only).

    One legitimate exception: a strangle's expiry is the NEXT month-end,
    which truncation shifts for the final roll. Expiry dates come from the
    exchange calendar — known in advance, not price lookahead — so the
    comparison stops strictly before the last roll date the two runs share
    with different calendars ahead of them."""
    from strategies.vrp_short_vol.backtest import run_vrp_backtest, _month_end_dates
    from strategies.vrp_short_vol import config as cfg
    px, vix, tbill = vrp_inputs
    full = run_vrp_backtest(px, vix, tbill, 100_000, cfg)
    cut_px = px.iloc[:-40]
    cut = run_vrp_backtest(cut_px, vix, tbill, 100_000, cfg)

    # last month-end in the truncated calendar whose NEXT month-end still
    # matches the full calendar; compare equity strictly before it
    boundary = _month_end_dates(cut.index)[-2]
    a = full["equity"].loc[:boundary].iloc[:-1]
    b = cut["equity"].loc[:boundary].iloc[:-1]
    assert len(a) > 500
    pd.testing.assert_series_equal(a, b, rtol=1e-12, atol=1e-9)


def test_stop_loss_bounds_position_loss(vrp_run):
    """No single position cycle may lose much more than the stop implies:
    (STOP_MULT − 1) × premium + spread + one day of gap risk. We check the
    coarser invariant that every stop event is followed by a flat book."""
    pf = vrp_run
    stops = pf.index[pf["action"].str.contains("stop", na=False)]
    for d in stops:
        nxt = pf.index[pf.index > d]
        if len(nxt):
            assert not pf.loc[nxt[0], "in_position"] or \
                "sell" in pf.loc[nxt[0], "action"]
