"""
Golden-number regression tests.

Each engine must reproduce its documented results on the cached window.
Any change to an engine that silently moves these numbers — a refactor, a
"cleanup", a timing tweak — fails here first, instead of surfacing months
later as a README/live mismatch.

Price data is cache-permanent, so price-only engines get tight tolerances.
GARP depends on the EDGAR fundamentals cache, which the live system
refreshes weekly (new filings genuinely shift its scores), so GARP gets a
documented band rather than a point value.

Golden values recorded 2026-07-10, after the July 2026 methodology fixes.
"""

import numpy as np
import pytest


def _stats(pf):
    v   = pf["portfolio_value"]
    tot = v.iloc[-1] / (v.iloc[0] / (1 + pf["daily_return"].iloc[0])) - 1
    dd  = ((v - v.cummax()) / v.cummax()).min()
    return tot, dd


# ── TRIAD (price-only, tight) ─────────────────────────────────

def test_triad_golden(tmt_bars, qqq_bars, tbill_rate):
    from strategies.equities.triad.backtest import run_triad_backtest
    from strategies.equities.triad import config as cfg

    pf = run_triad_backtest(tmt_bars, qqq_bars, tbill_rate, 100_000, cfg)
    tot, dd = _stats(pf)
    assert tot == pytest.approx(6.206, abs=0.02)      # +620.6% (2016–2024)
    assert dd  == pytest.approx(-0.1860, abs=0.002)   # −18.60%


# ── AFP (price-only, tight) ───────────────────────────────────

def test_afp_golden(factor_prices, tbill_rate):
    from strategies.equities.equity_factor_rotation.backtest import run_factor_backtest
    from strategies.equities.equity_factor_rotation import config as cfg

    pf = run_factor_backtest(
        factor_prices, tbill_rate, 100_000,
        cfg.LOOKBACK_MONTHS, cfg.RANK_TILT,
        cfg.CORR_WINDOW, cfg.CORR_HIGH, cfg.CORR_MID,
        cfg.TARGET_VOL, cfg.MAX_WEIGHT, cfg.MAX_LEVERAGE, cfg.VOL_LOOKBACK,
        cfg.TRANSACTION_COST, cfg.DRAWDOWN_STOP)
    tot, dd = _stats(pf)
    assert tot == pytest.approx(1.0235, abs=0.01)     # +102.35%
    assert dd  == pytest.approx(-0.1355, abs=0.002)   # −13.55%


# ── BTREND (price-only, tight; its own 2016–2026 window) ─────

def test_btrend_golden(btrend_prices):
    from core.data import fetch_tbill
    from strategies.cross_asset.broad_trend.backtest import run_trend_backtest
    from strategies.cross_asset.broad_trend import config as cfg

    tbill, _ = fetch_tbill(cfg.START_DATE, cfg.END_DATE, 100_000)
    pf = run_trend_backtest(btrend_prices, tbill, 100_000, cfg)
    tot, dd = _stats(pf)
    assert tot == pytest.approx(0.4613, abs=0.01)     # +46.13% (2016–2026)
    assert dd  == pytest.approx(-0.0777, abs=0.002)   # −7.77%


# ── DTQ (price-only, tight) ───────────────────────────────────

def test_dtq_golden(qqq_bars, tbill_rate):
    from strategies.equities.dual_timescale_qqq.backtest import run_dtq_backtest
    from strategies.equities.dual_timescale_qqq import config as cfg

    pf, _trades = run_dtq_backtest(
        qqq_bars, tbill_rate, 100_000,
        trend_weight=cfg.TREND_WEIGHT, mr_weight=cfg.MR_WEIGHT,
        sma_window=cfg.SMA_WINDOW, trend_target_vol=cfg.TREND_TARGET_VOL,
        trend_max_size=cfg.TREND_MAX_SIZE, mr_entry_ibs=cfg.MR_ENTRY_IBS,
        mr_exit_ibs=cfg.MR_EXIT_IBS, mr_max_hold=cfg.MR_MAX_HOLD,
        mr_target_vol=cfg.MR_TARGET_VOL, mr_max_size=cfg.MR_MAX_SIZE,
        vol_lookback=cfg.VOL_LOOKBACK, transaction_cost=cfg.TRANSACTION_COST)
    tot, dd = _stats(pf)
    assert tot == pytest.approx(1.85, abs=0.03)       # +185%
    assert dd  == pytest.approx(-0.098, abs=0.003)    # −9.8%


# ── GARP (EDGAR-dependent, banded) ────────────────────────────

def test_garp_golden_band(tmt_closes, tbill_rate):
    """The EDGAR cache refreshes weekly live, and new/amended filings move
    the score, so assert a band: drift inside it is data, outside it is code."""
    from strategies.equities.garp_momentum.fundamentals import build_garp_history
    from strategies.equities.garp_momentum.backtest import run_garp_backtest
    from strategies.equities.garp_momentum import config as cfg
    from config import DATA_CACHE_DIR

    prices = tmt_closes[[t for t in cfg.TICKERS if t in tmt_closes.columns]]
    spy    = tmt_closes["SPY"]
    hist   = build_garp_history(list(prices.columns), prices,
                                cache_dir=DATA_CACHE_DIR)
    pf = run_garp_backtest(
        prices, hist, spy, tbill_rate, 100_000,
        cfg.TOP_N, cfg.LOOKBACK_MONTHS, cfg.SKIP_MONTHS,
        cfg.GARP_WEIGHT, cfg.MOM_WEIGHT, cfg.MAX_WEIGHT,
        cfg.TARGET_VOL, cfg.MAX_LEVERAGE, cfg.VOL_LOOKBACK,
        cfg.TRANSACTION_COST, cfg.DRAWDOWN_STOP)
    tot, dd = _stats(pf)
    r   = pf["daily_return"].dropna()
    ann = (1 + tot) ** (252 / len(r)) - 1
    vol = r.std() * np.sqrt(252)

    assert 3.5 < tot < 7.5,   f"total return {tot:+.1%} outside band"  # ~+529%
    assert -0.26 < dd < -0.15, f"max DD {dd:.1%} outside band"          # ~−20.5%
    assert 0.9 < (ann - 0.018) / vol < 1.4                              # Sharpe ~1.14
